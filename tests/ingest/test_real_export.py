"""Regression tests on the trimmed REAL export of sensor 77799986 (tests/fixtures/exports/real).

The file holds real measurements, public by owner decision 2026-10-05. Every expected value
below was read by hand from the raw lines of the file (see the README next to it).
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from sivin.core.daily import DailyWeather
from sivin.core.defaults import DEFAULT_SAMPLING_INTERVAL_S
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.ingest.parsers.base import ParsedExport, parser_registry
from sivin.ingest.parsers.legacy import LegacyWorkbookParser
from sivin.ingest.parsers.portal import PortalCsvParser, PortalXlsxParser, is_portal_export_name
from sivin.ingest.parsers.sources import CsvGridReader
from sivin.ingest.parsers.tabular import SensorTable, TabularExportReader

from .conftest import REAL_EXPORTS, make_settings

REAL_NAME = "MeteoData_8615620_77799986_VUT_20260301_223842.csv"
"""The file name exactly as the export arrived (underscores, owner question Q8)."""

SPACED_NAME = "MeteoData_8615620 77799986 (VUT)_20260301_223842.csv"
"""The same export under the spelling with spaces and parentheses."""

REAL_PATH = REAL_EXPORTS / REAL_NAME
SENSOR = SensorId("77799986")
N_DATA_ROWS = 300
"""150 newest + 150 oldest data rows of the 3520 rows of the original export."""

HEADER = "Datum a čas;Teplota (°C);Vlhkost (%);Srážky (mm);Celkové srážky (mm);Nabití baterie (V)"


@pytest.fixture(scope="module")
def parsed() -> ParsedExport:
    parser = parser_registry.for_file(REAL_PATH, make_settings())
    return parser.parse(REAL_PATH)


@pytest.fixture(scope="module")
def frame(parsed: ParsedExport) -> pd.DataFrame:
    assert parsed.is_accepted, parsed.report.summary()
    (series,) = parsed.series
    return series.frame


def test_raw_file_layout_is_the_original() -> None:
    raw = REAL_PATH.read_bytes()
    lines = raw.split(b"\r\n")
    assert b"\n" not in raw.replace(b"\r\n", b"")  # CRLF only
    assert not raw.startswith(b"\xef\xbb\xbf")  # UTF-8 without BOM
    assert lines[0] == b"Meteo Data;"
    assert lines[1].decode("utf-8") == HEADER
    assert lines[-2:] == [b";", b""]  # trailing ';' line, then the final CRLF
    assert len(lines) == 2 + N_DATA_ROWS + 2


def test_routed_to_the_portal_csv_parser_under_the_original_name() -> None:
    assert isinstance(parser_registry.for_file(REAL_PATH), PortalCsvParser)
    workbook = REAL_PATH.with_suffix(".xlsx")
    assert is_portal_export_name(workbook)
    assert isinstance(parser_registry.for_file(workbook), PortalXlsxParser)
    # Even with a legacy worksheet mapping, the legacy parser leaves the name alone.
    legacy = LegacyWorkbookParser(make_settings(legacy_sheet_sensors={"9986": "77799986"}))
    assert not legacy.can_parse(workbook)


def test_parsed_without_any_finding(parsed: ParsedExport, frame: pd.DataFrame) -> None:
    assert parsed.report.issues == ()
    assert parsed.series[0].sensor_id == SENSOR
    assert len(frame) == N_DATA_ROWS
    assert frame["source"].unique().tolist() == [REAL_NAME]
    assert not frame[["temp_c", "rh_pct"]].isna().to_numpy().any()
    assert (frame["qc"] == int(QcFlag.OK)).all()


def test_first_and_last_rows_in_utc(frame: pd.DataFrame) -> None:
    # Oldest line "2025-07-30 10:22:29;28,66;41,8" is CEST (UTC+2); newest line
    # "2026-03-01 22:27:05;23,79;31,1" is CET (UTC+1).
    first, last = frame.iloc[0], frame.iloc[-1]
    assert first["timestamp_utc"] == pd.Timestamp("2025-07-30 08:22:29", tz="UTC")
    assert (first["temp_c"], first["rh_pct"]) == (28.66, 41.8)
    assert last["timestamp_utc"] == pd.Timestamp("2026-03-01 21:27:05", tz="UTC")
    assert (last["temp_c"], last["rh_pct"]) == (23.79, 31.1)
    assert frame["timestamp_utc"].is_monotonic_increasing


def test_oldest_rows_gaps_and_the_december_transition(frame: pd.DataFrame) -> None:
    # The five oldest lines of the file, oldest first (local time -> UTC):
    # 2025-07-30 10:22:29 CEST, 2025-07-30 13:54:45 CEST, 2025-07-31 13:21:23 CEST,
    # 2025-07-31 13:22:12 CEST, 2025-12-17 12:58:06 CET (24,47 °C; 30,0 %).
    expected = pd.to_datetime(
        [
            "2025-07-30 08:22:29",
            "2025-07-30 11:54:45",
            "2025-07-31 11:21:23",
            "2025-07-31 11:22:12",
            "2025-12-17 11:58:06",
        ]
    ).tz_localize("UTC")
    assert frame["timestamp_utc"].iloc[:5].tolist() == expected.tolist()
    assert (frame["temp_c"].iloc[4], frame["rh_pct"].iloc[4]) == (24.47, 30.0)
    steps_s = frame["timestamp_utc"].iloc[:5].diff().dt.total_seconds().iloc[1:].tolist()
    # 3 h 32 min 16 s; 23 h 26 min 38 s; 49 s; 139 d 0 h 35 min 54 s (3336.6 h).
    assert steps_s == [12_736.0, 84_398.0, 49.0, 139 * 86_400.0 + 2_154.0]


def test_newest_first_rows_are_reversed() -> None:
    settings = make_settings()
    grid = CsvGridReader(settings.csv_delimiter, settings.csv_encodings).read(REAL_PATH)
    inspection = TabularExportReader(settings).inspect(SensorTable(grid, SENSOR))
    assert inspection.reversed_order
    assert inspection.source_rows is not None
    # Oldest data line is file line 302, newest is line 3 (title and header are lines 1-2).
    assert (inspection.source_rows[0], inspection.source_rows[-1]) == (302, 3)
    # The extra columns (precipitation, cumulative precipitation, battery) are ignored.
    assert inspection.missing_columns == ()
    assert inspection.column_problems == ()
    assert inspection.temp is not None
    assert inspection.rh is not None
    assert (inspection.temp.header, inspection.rh.header) == ("Teplota (°C)", "Vlhkost (%)")


def test_same_content_under_the_spaced_name_gives_the_same_series(
    frame: pd.DataFrame, tmp_path: Path
) -> None:
    spaced = tmp_path / SPACED_NAME
    shutil.copyfile(REAL_PATH, spaced)
    result = parser_registry.for_file(spaced, make_settings()).parse(spaced)
    (series,) = result.series
    assert series.sensor_id == SENSOR
    columns = ["timestamp_utc", "temp_c", "rh_pct", "qc"]
    pd.testing.assert_frame_equal(series.frame[columns], frame[columns])


def test_daily_coverage_with_the_measured_interval(parsed: ParsedExport) -> None:
    # 2026-02-28 (local) has 47 lines in the file: coverage 47 * 1830 s / 86 400 s = 0.99549.
    daily = DailyWeather.from_series(
        parsed.series[0],
        "Europe/Prague",
        DEFAULT_SAMPLING_INTERVAL_S,
        int(QcFlag.DEFAULT_EXCLUDE),
    ).frame
    day = daily.loc[date(2026, 2, 28)]
    assert day["n_samples"] == 47
    assert day["coverage"] == pytest.approx(47 * 1830 / 86_400)
