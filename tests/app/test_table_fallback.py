"""The table source through FetchService and the ingest into the store (WP-1.10).

The fake portal's export fails for the registered outdoor sensor; its device table holds
SYNTHETIC rows. No browser, no network.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from tests.app.fake_portal import VIEWMODEL_JSON, credentials
from tests.app.project import OUTDOOR_SENSOR, TEST_CONFIG, Project, make_project
from tests.ingest.portal.conftest import FakeDriverFactory
from tests.ingest.portal.table_fakes import TablePortalDriver, TableState, synthetic_rows

from sivin.app.factory import ServiceFactory
from sivin.app.fetch import FetchService, StoreLastTimestamps
from sivin.app.outcome import Outcome
from sivin.app.workspace import Workspace
from sivin.core.ids import SensorId
from sivin.ingest.portal.driver import WebDriverFactory
from sivin.ingest.portal.settings import PortalSettings, PortalSource
from sivin.storage.errors import StoreError
from sivin.storage.store import MeasurementStore

OUTDOOR = SensorId(OUTDOOR_SENSOR)
OUTDOOR_NAME = "8615620 77678271"
NEWEST = datetime(2026, 11, 20, 12, 0, 0)
"""Local time (CET) of the newest SYNTHETIC table row."""


def _drivers(table: TableState) -> Callable[[PortalSettings], WebDriverFactory]:
    def build(settings: PortalSettings) -> WebDriverFactory:
        driver = TablePortalDriver(
            settings, VIEWMODEL_JSON, {OUTDOOR_NAME: "no_button"}, {OUTDOOR_NAME: table}
        )
        return FakeDriverFactory(settings, driver)

    return build


def _fetch_service(
    factory: ServiceFactory, table: TableState, store: MeasurementStore
) -> FetchService:
    return FetchService(
        factory.portal_settings(),
        credentials,
        _drivers(table),
        factory.redactor,
        last_timestamps=StoreLastTimestamps(store),
    )


def test_the_table_fills_the_store_and_the_next_run_reads_only_new_rows(
    project: Project, caplog: pytest.LogCaptureFixture
) -> None:
    factory = ServiceFactory(Workspace.open(start=project.root), credentials=credentials)
    store = factory.store()
    table = TableState(synthetic_rows(NEWEST, 30))

    with caplog.at_level(logging.INFO):
        first = _fetch_service(factory, table, store).fetch([OUTDOOR])
    assert first.outcome is Outcome.OK
    (path,) = first.files
    assert "(table)" in path.name
    assert "(1 by table)" in caplog.text
    ingest = factory.ingest_service().ingest(first.files)
    assert ingest.appends[OUTDOOR].new_rows == 30
    # 12:00 CET = 11:00 UTC.
    assert store.time_range(OUTDOOR) == (
        pd.Timestamp("2026-11-19 20:30", tz="UTC"),
        pd.Timestamp("2026-11-20 11:00", tz="UTC"),
    )

    # Two new measurements; the table now starts 1 h later.
    table.rows = synthetic_rows(datetime(2026, 11, 20, 13, 0, 0), 32)
    table.page_index = 0
    second = _fetch_service(factory, table, store).fetch([OUTDOOR])
    (newer,) = second.files
    lines = newer.read_text(encoding="utf-8").splitlines()
    assert [line.split(";")[0] for line in lines[2:-1]] == [
        "2026-11-20 13:00:00",
        "2026-11-20 12:30:00",
    ]
    assert factory.ingest_service().ingest(second.files).appends[OUTDOOR].new_rows == 2

    third = _fetch_service(factory, table, store).fetch([OUTDOOR])
    assert third.files == ()
    assert third.outcome is Outcome.OK
    assert [item.device.name for item in third.result.up_to_date] == [OUTDOOR_NAME]


class _BrokenStore:
    def time_range(self, sensor_id: SensorId) -> None:
        raise StoreError("unreadable partition")


def test_last_timestamps_of_the_store(project: Project, caplog: pytest.LogCaptureFixture) -> None:
    store = ServiceFactory(Workspace.open(start=project.root)).store()
    assert StoreLastTimestamps(store).last_timestamp(OUTDOOR) is None

    broken: MeasurementStore = _BrokenStore()  # type: ignore[assignment]
    with caplog.at_level(logging.WARNING):
        assert StoreLastTimestamps(broken).last_timestamp(OUTDOOR) is None
    assert "reading its whole table history" in caplog.text


def test_the_last_timestamp_is_aware_utc(project: Project) -> None:
    factory = ServiceFactory(Workspace.open(start=project.root), credentials=credentials)
    store = factory.store()
    table = TableState(synthetic_rows(NEWEST, 3))
    report = _fetch_service(factory, table, store).fetch([OUTDOOR])
    factory.ingest_service().ingest(report.files)

    last = StoreLastTimestamps(store).last_timestamp(OUTDOOR)

    assert last == datetime(2026, 11, 20, 11, 0, tzinfo=UTC)


def test_sivin_run_reads_only_the_rows_newer_than_the_store(project: Project) -> None:
    table = TableState(synthetic_rows(NEWEST, 30))
    factory = ServiceFactory(
        Workspace.open(start=project.root), drivers=_drivers(table), credentials=credentials
    )

    first = factory.run_service(skip_site=True).run(2026, [OUTDOOR])
    assert first.ingest.appends[OUTDOOR].new_rows == 30

    table.rows = synthetic_rows(datetime(2026, 11, 20, 13, 0, 0), 32)
    table.page_index = 0
    second = factory.run_service(skip_site=True).run(2026, [OUTDOOR])

    (item,) = second.ingest.files
    assert "(table)" in item.path.name
    # Only the two new rows were read and written: no full-history file, no identical rows.
    assert second.ingest.appends[OUTDOOR].new_rows == 2
    assert second.ingest.appends[OUTDOOR].identical_skipped == 0


DEFAULT_ORDER_CONFIG = TEST_CONFIG.replace("    sources: [export, table]\n", "")
"""The test configuration without ``sources``: the default order ``[table, export]`` applies."""


def test_the_default_order_reads_the_table_although_the_export_works(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert DEFAULT_ORDER_CONFIG != TEST_CONFIG
    project = make_project(tmp_path / "project", config=DEFAULT_ORDER_CONFIG)
    built: list[TablePortalDriver] = []

    def build(settings: PortalSettings) -> WebDriverFactory:
        driver = TablePortalDriver(
            settings, VIEWMODEL_JSON, None, {OUTDOOR_NAME: TableState(synthetic_rows(NEWEST, 3))}
        )
        built.append(driver)
        return FakeDriverFactory(settings, driver)

    factory = ServiceFactory(Workspace.open(start=project.root), credentials=credentials)
    assert factory.portal_settings().sources == (PortalSource.TABLE, PortalSource.EXPORT)
    service = FetchService(factory.portal_settings(), credentials, build, factory.redactor)

    with caplog.at_level(logging.INFO):
        report = service.fetch([OUTDOOR])

    assert report.outcome is Outcome.OK
    (path,) = report.files
    assert "(table)" in path.name
    (driver,) = built
    assert not any(entry[0] == "click" and "excel" in entry[1] for entry in driver.log)
    assert factory.ingest_service().ingest(report.files).appends[OUTDOOR].new_rows == 3
