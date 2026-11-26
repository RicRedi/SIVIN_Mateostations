"""TableCsvWriter: rows of the device table become a file the existing ingest path reads (WP-1.10).

The rows come from the excerpt of a real device page (public measured data).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from tests.ingest.conftest import make_settings
from tests.ingest.portal.table_fakes import raw_table, real_excerpt

from sivin.core.ids import SensorId
from sivin.ingest.parsers.base import parser_registry
from sivin.ingest.parsers.portal import PortalCsvParser
from sivin.ingest.portal.errors import TableReadError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.settings import PortalTableSettings
from sivin.ingest.portal.table import TableReading, TableRowParser
from sivin.ingest.portal.table_file import TableCsvWriter
from sivin.storage.source import ExportSourceIds

DEVICE = PortalDevice("8615620 77680921")
WRITTEN_AT = datetime(2026, 11, 26, 5, 0, 0, tzinfo=UTC)
"""06:00 CET, the time of the daily run."""

NAME = "MeteoData_8615620 77680921 (table)_20261126_060000.csv"


def _reading(count: int = 20) -> TableReading:
    excerpt = real_excerpt()
    parsed = TableRowParser(PortalTableSettings()).parse(
        raw_table(excerpt.rows[:count], excerpt.headers)
    )
    return TableReading(parsed.columns, parsed.rows, pages_read=1)


def _writer(directory: Path) -> TableCsvWriter:
    return TableCsvWriter(PortalTableSettings(), directory)


def test_the_file_has_the_layout_of_the_real_export(tmp_path: Path) -> None:
    path = _writer(tmp_path).write(DEVICE, _reading(2), WRITTEN_AT)

    assert path == tmp_path / NAME
    assert (
        path.read_bytes()
        == (
            "Meteo Data;\r\n"
            "Datum a čas;Teplota (°C);Vlhkost (%);Srážky (mm);Celkové srážky (mm);"
            "Nabití baterie (V)\r\n"
            "2026-11-18 13:49:25;24,3848;35,498;0;200,57;3,3\r\n"
            "2026-11-18 13:19:53;24,3848;35,6445;0;200,57;3,3\r\n"
            ";\r\n"
        ).encode()
    )
    assert list(tmp_path.iterdir()) == [path]  # no temporary file left


def test_the_name_names_the_sensor_and_the_source_time(tmp_path: Path) -> None:
    name = _writer(tmp_path).file_name(DEVICE, WRITTEN_AT)

    assert name == NAME
    assert SensorId.parse(name) == SensorId("77680921")
    assert ExportSourceIds().of(name) == "20261126T060000"


def test_a_second_file_in_the_same_second_gets_a_copy_suffix(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    first = writer.write(DEVICE, _reading(1), WRITTEN_AT)
    second = writer.write(DEVICE, _reading(1), WRITTEN_AT)

    assert first.name == NAME
    assert second.name == "MeteoData_8615620 77680921 (table)_20261126_060000 (1).csv"
    assert SensorId.parse(second.name) == SensorId("77680921")


def test_the_parser_reads_the_file_and_converts_local_time(tmp_path: Path) -> None:
    path = _writer(tmp_path).write(DEVICE, _reading(), WRITTEN_AT)

    parser = parser_registry.for_file(path, make_settings())
    parsed = parser.parse(path)

    assert isinstance(parser, PortalCsvParser)
    assert parsed.is_accepted, parsed.report.summary()
    (series,) = parsed.series
    frame = series.frame
    assert series.sensor_id == SensorId("77680921")
    assert len(frame) == 20
    # Oldest first after parsing; 18.11.2026 is CET (UTC+1): 04:28:17 local = 03:28:17 UTC.
    assert frame["timestamp_utc"].iloc[0] == pd.Timestamp("2026-11-18 03:28:17", tz="UTC")
    assert frame["timestamp_utc"].iloc[-1] == pd.Timestamp("2026-11-18 12:49:25", tz="UTC")
    assert frame["temp_c"].iloc[-1] == pytest.approx(24.3848)
    assert frame["rh_pct"].iloc[-1] == pytest.approx(35.498)
    assert frame["precip_total_mm"].iloc[-1] == pytest.approx(200.57)
    assert frame["battery_v"].iloc[-1] == pytest.approx(3.3)


@pytest.mark.parametrize("name", ["Unnamed device", "8615620 1234"])
def test_a_device_without_sensor_cannot_be_written(tmp_path: Path, name: str) -> None:
    with pytest.raises(TableReadError, match="does not name a sensor"):
        _writer(tmp_path).file_name(PortalDevice(name), WRITTEN_AT)


def test_a_naive_time_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _writer(tmp_path).file_name(DEVICE, datetime(2026, 11, 26, 5, 0))


def test_too_many_files_of_the_same_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sivin.ingest.portal.table_file.MAX_COPY_NUMBER", 1)
    writer = _writer(tmp_path)
    writer.write(DEVICE, _reading(1), WRITTEN_AT)
    writer.write(DEVICE, _reading(1), WRITTEN_AT)

    with pytest.raises(TableReadError, match="Too many files"):
        writer.write(DEVICE, _reading(1), WRITTEN_AT)
