"""Sources of a device's data and the fallback from the export to the table (WP-1.10).

The fake portal of WP-1.3 with a SYNTHETIC device table on each meteorological tab; no browser,
no network.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from tests.ingest.portal.conftest import FakeClock, FakeDriverFactory
from tests.ingest.portal.table_fakes import TablePortalDriver, TableState, synthetic_rows

from sivin.core.ids import SensorId
from sivin.ingest.parsers.base import parser_registry
from sivin.ingest.portal.client import PortalClient
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.portal.errors import TableReadError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.session import PortalSession
from sivin.ingest.portal.settings import PortalSettings, PortalSource, PortalTableSettings
from sivin.ingest.portal.sources import (
    DeviceSource,
    DeviceSourceRegistry,
    ExportSource,
    NoStoredData,
    SourceContext,
    TableSource,
    device_source_registry,
    utc_now,
)

FIRST, SECOND, THIRD = "8615620 77678271", "8615621 77678272", "8615622 77678273"
NEWEST = datetime(2026, 11, 20, 12, 0, 0)
"""Local time (CET) of the newest SYNTHETIC table row."""
RUN_AT = datetime(2026, 11, 20, 12, 10, 0, tzinfo=UTC)


class FixedLastTimestamps:
    """Last stored times per sensor, for the incremental reading."""

    def __init__(self, times: dict[str, datetime]) -> None:
        self.times = times
        self.asked: list[SensorId] = []

    def last_timestamp(self, sensor_id: SensorId) -> datetime | None:
        self.asked.append(sensor_id)
        return self.times.get(sensor_id.serial)


@pytest.fixture
def table_settings(settings: PortalSettings) -> PortalSettings:
    """The fake portal's settings with small page sizes and a short wait for rows."""
    return settings.model_copy(
        update={
            "table": PortalTableSettings(
                incremental_page_size=5, full_history_page_size=10, rows_wait_s=0.2
            )
        }
    )


def _session(
    settings: PortalSettings,
    credentials: PortalCredentials,
    viewmodel_json: str,
    *,
    behaviours: dict[str, str] | None = None,
    tables: dict[str, TableState] | None = None,
    sources: tuple[PortalSource, ...] | None = None,
    last: FixedLastTimestamps | None = None,
) -> tuple[PortalSession, TablePortalDriver]:
    used = settings if sources is None else settings.model_copy(update={"sources": sources})
    driver = TablePortalDriver(used, viewmodel_json, behaviours, tables)
    client = PortalClient(used, credentials, FakeDriverFactory(used, driver), clock=FakeClock())
    context = SourceContext(last or NoStoredData(), clock=lambda: RUN_AT)
    return PortalSession(client, device_source_registry.create(used.sources, context)), driver


def _tables(count: int = 25) -> dict[str, TableState]:
    return {name: TableState(synthetic_rows(NEWEST, count)) for name in (FIRST, SECOND, THIRD)}


def test_a_working_export_never_reads_the_table(
    table_settings: PortalSettings, credentials: PortalCredentials, viewmodel_json: str
) -> None:
    tables = _tables()
    session, _ = _session(table_settings, credentials, viewmodel_json, tables=tables)

    result = session.run()

    assert result.ok
    assert [download.source for download in result.downloads] == ["export"] * 3
    assert all(state.clicks == [] for state in tables.values())


def test_the_table_delivers_when_the_export_fails(
    table_settings: PortalSettings,
    credentials: PortalCredentials,
    viewmodel_json: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tables = _tables(25)
    session, _ = _session(
        table_settings, credentials, viewmodel_json, behaviours={SECOND: "no_button"}, tables=tables
    )

    with caplog.at_level(logging.INFO):
        result = session.run()

    assert result.ok
    sources = {download.device.name: download.source for download in result.downloads}
    assert sources == {FIRST: "export", SECOND: "table", THIRD: "export"}
    path = result.downloads[1].path
    # 13:10 CET, the run time, in the name; the whole history (nothing stored) of 25 rows.
    assert path.name == "MeteoData_8615621 77678272 (table)_20261120_131000.csv"
    parsed = parser_registry.for_file(path).parse(path)
    assert parsed.is_accepted, parsed.report.summary()
    assert len(parsed.series[0].frame) == 25
    # 25 rows at 10 per page: three pages.
    assert tables[SECOND].clicks.count("next") == 2
    assert f"{SECOND}: delivered by the table source after 1 failed source(s)." in caplog.text


def test_the_table_is_read_incrementally(
    table_settings: PortalSettings, credentials: PortalCredentials, viewmodel_json: str
) -> None:
    settings = table_settings.model_copy(
        update={"table": table_settings.table.model_copy(update={"incremental_page_size": 15})}
    )
    tables = _tables(25)
    tables[SECOND].page_size = 10
    # 07:00 UTC = 08:00 CET: the newer rows are 12:00, 11:30, ..., 08:30 (8 rows).
    last = FixedLastTimestamps({"77678272": datetime(2026, 11, 20, 7, 0, tzinfo=UTC)})
    session, _ = _session(
        settings,
        credentials,
        viewmodel_json,
        behaviours={SECOND: "no_button"},
        tables=tables,
        last=last,
    )

    result = session.run([SensorId("77678272")])

    (download,) = result.downloads
    assert download.source == "table"
    assert last.asked == [SensorId("77678272")]
    # One click: 10 → 15 rows per page; 08:00 is row 9 of page 1, so no further page.
    assert tables[SECOND].clicks == ["size"]
    lines = download.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 + 8 + 1  # title, header, 8 rows, trailer
    assert lines[2].startswith("2026-11-20 12:00:00;")
    assert lines[-2].startswith("2026-11-20 08:30:00;")


def test_a_device_without_new_rows_is_up_to_date(
    table_settings: PortalSettings, credentials: PortalCredentials, viewmodel_json: str
) -> None:
    last = FixedLastTimestamps({"77678271": datetime(2026, 11, 20, 11, 0, tzinfo=UTC)})
    session, _ = _session(
        table_settings,
        credentials,
        viewmodel_json,
        tables=_tables(),
        sources=(PortalSource.TABLE,),
        last=last,
    )

    result = session.run([SensorId("77678271")])

    assert result.ok
    assert result.downloads == ()
    assert [(item.device.name, item.source) for item in result.up_to_date] == [(FIRST, "table")]


def test_a_device_fails_only_when_every_source_failed(
    table_settings: PortalSettings,
    credentials: PortalCredentials,
    viewmodel_json: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tables = _tables()
    tables[SECOND] = TableState([])  # the table shows no rows
    session, _ = _session(
        table_settings, credentials, viewmodel_json, behaviours={SECOND: "no_button"}, tables=tables
    )

    with caplog.at_level(logging.WARNING):
        result = session.run()

    (failure,) = result.failures
    assert failure.device == PortalDevice(SECOND)
    export_reason, table_reason = failure.reason.split("; table: ")
    assert export_reason.startswith("export: ExportButtonNotFoundError: No visible Excel button")
    assert export_reason.endswith("(2 attempts)")
    assert table_reason.startswith("TableReadError: No rows in the table")
    assert table_reason.endswith("(2 attempts)")
    assert f"Table read of {SECOND} failed (TableReadError); diagnostics:" in caplog.text


def test_table_only_never_clicks_the_export(
    table_settings: PortalSettings, credentials: PortalCredentials, viewmodel_json: str
) -> None:
    session, driver = _session(
        table_settings,
        credentials,
        viewmodel_json,
        tables=_tables(),
        sources=(PortalSource.TABLE,),
    )

    result = session.run()

    assert [download.source for download in result.downloads] == ["table"] * 3
    assert not any(entry[0] == "click" and "excel" in entry[1] for entry in driver.log)


def test_table_only_failure_has_no_source_prefix(
    table_settings: PortalSettings, credentials: PortalCredentials, viewmodel_json: str
) -> None:
    session, _ = _session(
        table_settings,
        credentials,
        viewmodel_json,
        tables={},
        sources=(PortalSource.TABLE,),
    )

    result = session.run([SensorId("77678271")])

    (failure,) = result.failures
    assert failure.reason.startswith("TableReadError: No rows in the table")


def test_export_only_never_reads_the_table(
    table_settings: PortalSettings, credentials: PortalCredentials, viewmodel_json: str
) -> None:
    tables = _tables()
    session, _ = _session(
        table_settings,
        credentials,
        viewmodel_json,
        behaviours={FIRST: "no_button"},
        tables=tables,
        sources=(PortalSource.EXPORT,),
    )

    result = session.run([SensorId("77678271")])

    (failure,) = result.failures
    assert failure.reason.startswith("ExportButtonNotFoundError")
    assert tables[FIRST].clicks == []


class _StubClient:
    def __init__(self, settings: PortalSettings) -> None:
        self.settings = settings
        self.read: list[PortalDevice] = []

    def read_table(self, device: PortalDevice, since_utc: datetime | None) -> Any:
        self.read.append(device)
        raise AssertionError("not reached")


def test_the_table_needs_a_device_that_names_a_sensor(settings: PortalSettings) -> None:
    client: Any = _StubClient(settings)

    with pytest.raises(TableReadError, match="does not name a sensor"):
        TableSource(SourceContext()).deliver(client, PortalDevice("Weather station"))
    assert client.read == []


class TestRegistry:
    def test_every_configurable_source_is_registered(self) -> None:
        assert device_source_registry.names() == sorted(source.value for source in PortalSource)

    def test_sources_are_created_in_order(self) -> None:
        sources = device_source_registry.create(["table", "export"], SourceContext())

        assert [type(source) for source in sources] == [TableSource, ExportSource]

    def test_an_unknown_name_is_an_error(self) -> None:
        with pytest.raises(KeyError, match=r"Unknown device source 'ftp'; registered: \["):
            device_source_registry.create(["ftp"], SourceContext())

    def test_names_must_be_unique_and_present(self) -> None:
        registry = DeviceSourceRegistry()
        registry.register(ExportSource)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(ExportSource)

        class Nameless(DeviceSource):
            def deliver(self, client: PortalClient, device: PortalDevice) -> Path | None:
                return None

        with pytest.raises(ValueError, match="has no 'name'"):
            registry.register(Nameless)

    def test_a_session_needs_a_source(self, settings: PortalSettings) -> None:
        client: Any = _StubClient(settings)

        with pytest.raises(ValueError, match="at least one source"):
            PortalSession(client, ())

    def test_the_default_sources_come_from_the_settings(self, settings: PortalSettings) -> None:
        client: Any = _StubClient(settings.model_copy(update={"sources": (PortalSource.TABLE,)}))

        session = PortalSession(client)

        assert [type(source) for source in session._sources] == [TableSource]


def test_no_stored_data_and_the_clock() -> None:
    assert NoStoredData().last_timestamp(SensorId("77678271")) is None
    assert utc_now().tzinfo is UTC


class TestSettings:
    def test_defaults(self) -> None:
        settings = PortalSettings()

        assert settings.sources == (PortalSource.EXPORT, PortalSource.TABLE)
        assert settings.table.incremental_page_size == 500
        assert settings.table.full_history_page_size == 5000
        assert next(iter(settings.table.columns)) == "Datum a čas"

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"sources": []}, "at least 1 item"),
            ({"sources": ["export", "export"]}, "must not repeat a source"),
            ({"sources": ["ftp"]}, "Input should be 'export' or 'table'"),
            ({"table": {"table_xpath": "//table"}}, "must start with './'"),
            ({"table": {"card_xpath_template": "//div"}}, "must contain {text}"),
            ({"table": {"paging_text_pattern": "Zobrazeno (?P<shown>\\d+)"}}, "named groups"),
            ({"table": {"paging_text_pattern": "("}}, "not a regular expression"),
            ({"table": {"columns": {}}}, "at least the timestamp column"),
            ({"table": {"source_timezone": "Mars/Base"}}, "unknown IANA time zone"),
            ({"table": {"file_label": "two words"}}, "String should match pattern"),
            ({"table": {"incremental_page_size": 0}}, "greater than or equal to 1"),
        ],
    )
    def test_invalid_values_are_rejected(self, changes: dict[str, Any], message: str) -> None:
        with pytest.raises(ValidationError, match=message):
            PortalSettings.model_validate(changes)

    def test_sources_read_from_yaml_names(self) -> None:
        settings = PortalSettings.model_validate({"sources": ["table"]})

        assert settings.sources == (PortalSource.TABLE,)
