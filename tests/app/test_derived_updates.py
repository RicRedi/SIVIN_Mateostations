"""Derived files are updated in place, never lost (WP-1.7 review, major 3). SYNTHETIC data."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tests.app.project import OUTDOOR_SENSOR, Project, write_synthetic_export

from sivin.analytics.base import index_registry
from sivin.app.factory import ServiceFactory
from sivin.app.outcome import Outcome
from sivin.app.workspace import Workspace
from sivin.core.ids import SensorId
from sivin.ingest.portal.credentials import PortalCredentials, Secret

OTHER_SENSOR = "77680921"
OUTDOOR = SensorId(OUTDOOR_SENSOR)
OTHER = SensorId(OTHER_SENSOR)
FIRST_RUN = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)


class Clock:
    """A clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = FIRST_RUN

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def services(project: Project, clock: Clock) -> ServiceFactory:
    factory = ServiceFactory(
        Workspace.open(start=project.root),
        credentials=lambda: PortalCredentials("u", Secret("p")),
        clock=clock,
    )
    files = [
        write_synthetic_export(project.downloads, days=2),
        write_synthetic_export(project.downloads, serial=OTHER_SENSOR, days=2),
    ]
    assert factory.ingest_service().ingest(files).outcome is Outcome.OK
    return factory


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def break_store(project: Project, serial: str) -> None:
    path = project.root / "data" / "raw" / serial / "2026.csv"
    path.write_text("broken\n", encoding="utf-8")


class TestIndicesFile:
    def test_restricted_run_replaces_only_the_selected_entries(
        self, services: ServiceFactory, clock: Clock
    ) -> None:
        full = services.indices_service().run(2026)
        assert full.file is not None
        before = read(full.file)
        assert set(before["sensors"]) == {OUTDOOR_SENSOR, OTHER_SENSOR}
        assert set(before["sensors"][OTHER_SENSOR]) == set(index_registry.ids())
        clock.now = FIRST_RUN + timedelta(days=1)
        services.indices_service().run(2026, [OUTDOOR], ["huglin"])
        after = read(full.file)
        assert after["sensors"][OTHER_SENSOR] == before["sensors"][OTHER_SENSOR]
        assert set(after["sensors"][OUTDOOR_SENSOR]) == set(index_registry.ids())
        assert after["sensors"][OUTDOOR_SENSOR]["huglin"]["computed_at"] == "2026-10-06T04:00:00Z"
        assert after["sensors"][OUTDOOR_SENSOR]["gst"]["computed_at"] == "2026-10-05T04:00:00Z"

    def test_failed_sensor_keeps_its_previous_entries(
        self, project: Project, services: ServiceFactory, clock: Clock
    ) -> None:
        file = services.indices_service().run(2026).file
        assert file is not None
        before = read(file)["sensors"][OTHER_SENSOR]["gst"]
        break_store(project, OTHER_SENSOR)
        clock.now = FIRST_RUN + timedelta(days=1)
        report = services.indices_service().run(2026)
        assert report.outcome is Outcome.PARTIAL_FAILURE
        gst = read(file)["sensors"][OTHER_SENSOR]["gst"]
        assert gst["status"] == "failed"
        assert gst["error"].startswith(f"{project.root / 'data/raw' / OTHER_SENSOR / '2026.csv'}")
        assert gst["computed_at"] == "2026-10-05T04:00:00Z"  # the last success
        assert gst["value"] == before["value"]
        assert read(file)["sensors"][OUTDOOR_SENSOR]["gst"]["status"] == "ok"

    def test_failure_without_a_previous_entry(
        self, project: Project, services: ServiceFactory
    ) -> None:
        break_store(project, OTHER_SENSOR)
        file = services.indices_service().run(2026, index_ids=["gst"]).file
        assert file is not None
        entry = read(file)["sensors"][OTHER_SENSOR]["gst"]
        assert (entry["status"], entry["computed_at"]) == ("failed", None)

    def test_a_season_without_data_writes_nothing(self, services: ServiceFactory) -> None:
        report = services.indices_service().run(2019)
        assert report.file is None
        assert not report.changes

    def test_an_unreadable_file_is_replaced(
        self, project: Project, services: ServiceFactory
    ) -> None:
        path = project.root / "data" / "derived" / "indices" / "2026.json"
        path.parent.mkdir(parents=True)
        path.write_text("[not json", encoding="utf-8")
        services.indices_service().run(2026, [OUTDOOR], ["gst"])
        assert set(read(path)["sensors"]) == {OUTDOOR_SENSOR}


class TestEventsFile:
    def test_report_bounds_never_shorten_the_file(
        self, services: ServiceFactory, clock: Clock
    ) -> None:
        full = services.quality_service().run([OUTDOOR]).sensors[OUTDOOR]
        assert full.events_file is not None
        document = read(full.events_file)
        assert document["n_samples"] == 94
        clock.now = FIRST_RUN + timedelta(days=1)
        start = datetime(2026, 6, 1, 12, tzinfo=UTC)
        part = (
            services.quality_service()
            .run([OUTDOOR], start, start + timedelta(hours=2))
            .sensors[OUTDOOR]
        )
        assert part.result is not None
        assert len(part.result.series) == 4  # the report shows the 2 h only
        after = read(full.events_file)
        assert after["n_samples"] == 94
        assert after["computed_at"] == "2026-10-06T04:00:00Z"
        assert {k: v for k, v in after.items() if k != "computed_at"} == {
            k: v for k, v in document.items() if k != "computed_at"
        }

    def test_failed_sensor_keeps_its_previous_file(
        self, project: Project, services: ServiceFactory, clock: Clock
    ) -> None:
        events = services.quality_service().run([OTHER]).sensors[OTHER].events_file
        assert events is not None
        before = read(events)
        break_store(project, OTHER_SENSOR)
        clock.now = FIRST_RUN + timedelta(days=1)
        report = services.quality_service().run([OTHER])
        assert report.outcome is Outcome.PARTIAL_FAILURE
        after = read(events)
        assert (after["status"], after["computed_at"]) == ("failed", "2026-10-05T04:00:00Z")
        assert after["events"] == before["events"]
        assert after["n_samples"] == before["n_samples"]
        assert "error" in after

    def test_failure_without_previous_file(
        self, project: Project, services: ServiceFactory
    ) -> None:
        break_store(project, OTHER_SENSOR)
        item = services.quality_service().run([OTHER]).sensors[OTHER]
        assert item.events_file is not None
        document = read(item.events_file)
        assert (document["status"], document["computed_at"], document["events"]) == (
            "failed",
            None,
            [],
        )


def test_empty_store_writes_nothing(project: Project) -> None:
    factory = ServiceFactory(Workspace.open(start=project.root), clock=lambda: FIRST_RUN)
    assert factory.quality_service().run().sensors == {}
    report = factory.indices_service().run(2026)
    assert report.file is None
    assert not (project.root / "data" / "derived").exists()
