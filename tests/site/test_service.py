"""The site service in a temporary project: the real export of 77799986 (public by owner
decision) and SYNTHETIC exports of other sensors, through ingest, QC and the indices."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pytest
from tests.app.conftest import make_factory
from tests.app.project import (
    OUTDOOR_SENSOR,
    REAL_SENSOR,
    Project,
    make_project,
    write_synthetic_export,
)

from sivin.analytics.base import index_registry
from sivin.app.factory import ServiceFactory
from sivin.app.outcome import Outcome
from sivin.app.site import SiteIndices, SiteService
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries
from sivin.site.indices import IndexBatch
from sivin.site.state import STATE_FILE

RETIRED_SENSOR = "77680921"


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def ingest(factory: ServiceFactory, directory: Path) -> None:
    report = factory.ingest_service().ingest(factory.export_paths([], directory))
    assert report.failures == ()


@pytest.fixture
def project(tmp_path: Path) -> Project:
    made = make_project(tmp_path / "project")
    made.real_export(made.root / "inbox")
    write_synthetic_export(made.root / "inbox", start_local=datetime(2026, 5, 30, 0, 0, 10), days=4)
    ingest(make_factory(made), made.root / "inbox")
    return made


def test_incremental_and_full_builds_are_byte_identical(project: Project) -> None:
    incremental = project.root / "site" / "data"
    make_factory(project).site_service().build()
    write_synthetic_export(
        project.root / "inbox2", start_local=datetime(2026, 6, 3, 0, 0, 10), days=2,
        stamp="20260606_060000",
    )  # fmt: skip
    ingest(make_factory(project), project.root / "inbox2")

    report = make_factory(project).site_service().build()
    assert report.built == (SensorId(OUTDOOR_SENSOR),)
    assert report.reused == (SensorId(REAL_SENSOR),)
    full = make_factory(project).site_service().build(project.root / "full", full=True)
    assert full.full
    assert tree(incremental) == tree(project.root / "full")
    manifest = json.loads((incremental / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sensors"][OUTDOOR_SENSOR]["raw_months"] == ["2026-05", "2026-06"]


def test_site_of_the_real_and_a_synthetic_sensor(project: Project) -> None:
    report = make_factory(project).site_service().build()
    assert report.failures == ()
    assert report.seasons == (2025, 2026)
    root = project.root / "site" / "data"
    latest = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    # 77799986 was off site for the whole export: no valid sample, not in latest.json.
    assert list(latest["sensors"]) == [OUTDOOR_SENSOR]
    assert latest["sensors"][OUTDOOR_SENSOR]["stale"] is True  # June data, generated in October
    events = json.loads((root / "events" / f"{REAL_SENSOR}.json").read_text(encoding="utf-8"))
    off_site = [event for event in events["events"] if event["type"] == "off_site"]
    # Log: 2025-07-30 10:00 CEST .. 2026-03-01 22:30 CET.
    assert [(e["t"], e["t_end"], e["source"]) for e in off_site] == [
        (1_753_862_400, 1_772_400_600, "log")
    ]
    raw = json.loads((root / "series" / REAL_SENSOR / "raw" / "2026-03.json").read_text("utf-8"))
    assert set(raw["qc"]) == {32}  # PRE_DEPLOYMENT on every sample
    assert (root / "sensors.geojson").read_bytes() == (
        project.root / "sensors" / "sensors.geojson"
    ).read_bytes()
    indices = json.loads((root / "indices" / "2026.json").read_text(encoding="utf-8"))
    assert indices["computed_at"] == "2026-10-05T04:00:00Z"
    huglin = indices["sensors"][OUTDOOR_SENSOR]["huglin"]
    assert set(huglin) == {
        "value", "unit", "coverage", "complete", "class", "estimated", "status",
    }  # fmt: skip
    assert huglin["complete"] is False
    assert not (project.root / "data" / "derived" / "indices").exists()  # dry-run indices
    assert huglin["class"] is None  # never a class for an incomplete result
    assert not (root / STATE_FILE).exists()  # the build state is not published
    state = (project.root / "data" / "derived" / STATE_FILE).read_text(encoding="utf-8")
    assert str(project.root) not in state


def test_retired_sensor_is_published_with_its_status(project: Project) -> None:
    registry_path = project.root / "sensors" / "sensors.geojson"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for feature in registry["features"]:
        if feature["properties"]["id"] == RETIRED_SENSOR:
            feature["properties"]["status"] = "retired"
            feature["properties"]["placements"][-1]["to"] = "2026-09-01T00:00:00Z"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    write_synthetic_export(project.root / "inbox3", serial=RETIRED_SENSOR, days=1)
    ingest(make_factory(project), project.root / "inbox3")

    make_factory(project).site_service().build()
    manifest = json.loads((project.root / "site/data/manifest.json").read_text(encoding="utf-8"))
    assert manifest["sensors"][RETIRED_SENSOR]["status"] == "retired"
    assert manifest["sensors"][OUTDOOR_SENSOR]["status"] == "active"


def test_stored_sensor_outside_the_registry_is_not_published(
    project: Project, caplog: pytest.LogCaptureFixture
) -> None:
    factory = make_factory(project)
    stray = SensorId("99999999")
    times = ["2026-06-01T00:00:00Z", "2026-06-01T00:30:30Z"]
    factory.store().append(MeasurementSeries.from_records(stray, times, [10.0, 11.0], [80.0, 81.0]))
    with caplog.at_level(logging.WARNING):
        factory.site_service().build()
    assert "99999999 has stored data but is not in the registry" in caplog.text
    assert not (project.root / "site" / "data" / "events" / "99999999.json").exists()


def test_run_builds_the_site_from_its_qc(project: Project) -> None:
    report = make_factory(project).run_service(skip_fetch=True).run(2026)
    assert report.site is not None
    assert set(report.site.built) == {SensorId(OUTDOOR_SENSOR), SensorId(REAL_SENSOR)}
    assert report.outcome == Outcome.OK
    assert (project.root / "site" / "data" / "manifest.json").exists()


def test_run_without_site(project: Project) -> None:
    skipped = make_factory(project).run_service(skip_fetch=True, skip_site=True).run(2026)
    dry = make_factory(project).run_service(dry_run=True).run(2026)
    assert skipped.site is None
    assert dry.site is None
    assert not (project.root / "site").exists()


def test_unwritable_site_fails_only_its_step(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError("site/data is read-only")

    monkeypatch.setattr(SiteService, "build", refuse)
    report = make_factory(project).run_service(skip_fetch=True).run(2026)
    assert report.site is None
    assert report.site_failures == ("site: site/data is read-only",)
    assert report.outcome == Outcome.PARTIAL_FAILURE
    assert report.record.failures == ("site: site/data is read-only",)


def test_site_indices_without_sensors(project: Project) -> None:
    indices = SiteIndices(make_factory(project).indices_service(dry_run=True), index_registry)
    assert indices.compute(2026, {}) == IndexBatch()
    assert [spec.id for spec in indices.specs()] == list(index_registry.ids())


def test_site_data_dir(project: Project) -> None:
    workspace = make_factory(project).workspace
    assert workspace.site_data_dir == project.root / "site" / "data"


OFF_SITE_ALL_SEASON = """\
entries:
  - sensor: "77799986"
    from: "2025-07-30 10:00"
    to: "2026-03-01 22:30"
    reason: service
  - sensor: "77678271"
    from: "2026-01-01 00:00"
    to: "2027-01-01 00:00"
    reason: office
    note: "SYNTHETIC test period"
"""


def test_no_index_value_or_class_without_data(project: Project) -> None:
    """A sensor off site for the whole season gets no value, class or risk statement."""
    project.write_offsite_log(OFF_SITE_ALL_SEASON)
    make_factory(project).site_service().build(seasons=[2026])
    indices = json.loads((project.root / "site/data/indices/2026.json").read_text("utf-8"))
    entries = indices["sensors"][OUTDOOR_SENSOR]
    for index_id in ("powdery_mildew_gt", "botrytis_broome", "huglin", "gdd_winkler"):
        entry = entries[index_id]
        assert entry["coverage"] == 0.0, index_id
        assert (entry["value"], entry["class"], entry["status"], entry["detail"]) == (
            None,
            None,
            "no_data",
            "no data",
        ), index_id
    assert all(entry["value"] is None for entry in entries.values() if entry["coverage"] == 0)
