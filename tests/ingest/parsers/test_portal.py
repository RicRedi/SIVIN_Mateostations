"""Tests of the portal CSV and XLSX parsers on SYNTHETIC fixtures (hand-read expectations)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import pytest

from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.ingest.parsers.base import ParsedExport
from sivin.ingest.parsers.columns import ParserSettings
from sivin.ingest.parsers.portal import PortalCsvParser, PortalXlsxParser, is_portal_export_name
from sivin.ingest.validation import Severity, ValidationReport

from ..conftest import EXPORTS, PORTAL_CSV_NAME, CsvWriter

VALID = EXPORTS / "valid"
BROKEN = EXPORTS / "broken"


def utc(*values: str) -> list[pd.Timestamp]:
    return [pd.Timestamp(value, tz="UTC") for value in values]


def only_series(result: ParsedExport) -> pd.DataFrame:
    assert result.is_accepted, result.report.summary()
    assert len(result.series) == 1
    return result.series[0].frame


def test_valid_portal_csv() -> None:
    path = VALID / PORTAL_CSV_NAME
    result = PortalCsvParser().parse(path)
    frame = only_series(result)
    assert result.series[0].sensor_id == SensorId("77678271")
    assert result.source == path
    assert result.report == ValidationReport()
    assert len(frame) == 48
    # First data line "2026-03-01 00:00:07;3,7;86,7" is CET (UTC+1).
    assert frame["timestamp_utc"].iloc[0] == pd.Timestamp("2026-02-28 23:00:07", tz="UTC")
    assert frame["temp_c"].iloc[0] == pytest.approx(3.7)
    assert frame["rh_pct"].iloc[0] == pytest.approx(86.7)
    assert frame["timestamp_utc"].diff().dropna().eq(pd.Timedelta(seconds=1825)).all()
    assert (frame["qc"] == 0).all()
    assert set(frame["source"]) == {PORTAL_CSV_NAME}
    assert frame["timestamp_utc"].dtype == pd.DatetimeTZDtype("ns", "UTC")


def test_valid_portal_xlsx_with_datetime_cells() -> None:
    path = VALID / "MeteoData_8615620 77678271.xlsx"
    frame = only_series(PortalXlsxParser().parse(path))
    workbook = openpyxl.load_workbook(path)
    first = [cell.value for cell in workbook.active[3]]
    assert isinstance(first[0], datetime)
    expected = pd.Timestamp(first[0]).tz_localize("Europe/Prague").tz_convert("UTC")
    assert len(frame) == 48
    assert frame["timestamp_utc"].iloc[0] == expected
    assert frame["temp_c"].iloc[0] == pytest.approx(first[1])
    assert frame["rh_pct"].iloc[0] == pytest.approx(first[2])


def test_portal_xlsx_with_day_first_text_newest_first() -> None:
    path = VALID / "MeteoData_8615620 77680921  (VUT)_20260105_173301.xlsx"
    result = PortalXlsxParser().parse(path)
    frame = only_series(result)
    workbook = openpyxl.load_workbook(path)
    newest = [cell.value for cell in workbook.active[3]]
    oldest = [cell.value for cell in workbook.active[16]]
    assert newest[0] == "5.1.2026 17:33:01"  # 16:33:01 UTC
    assert result.series[0].sensor_id == SensorId("77680921")
    assert len(frame) == 14
    assert frame["timestamp_utc"].iloc[-1] == pd.Timestamp("2026-01-05 16:33:01", tz="UTC")
    assert frame["timestamp_utc"].is_monotonic_increasing
    assert frame["temp_c"].iloc[-1] == pytest.approx(float(newest[1].replace(",", ".")))
    assert frame["rh_pct"].iloc[0] == pytest.approx(float(oldest[2].replace(",", ".")))
    assert result.report.warnings == ()


@pytest.mark.parametrize(
    ("case", "rule"),
    [
        ("empty", "file-not-empty"),
        ("header_only", "data-rows"),
        ("missing_humidity", "required-columns"),
        ("rh_fraction", "humidity-fraction"),
        ("garbage_numbers", "numbers-parseable"),
        ("garbage_timestamps", "timestamps-parseable"),
        ("fahrenheit_header", "required-columns"),
        ("kelvin_values", "temperature-bounds"),
    ],
)
def test_broken_csv_is_rejected(case: str, rule: str) -> None:
    result = PortalCsvParser().parse(BROKEN / case / PORTAL_CSV_NAME)
    assert not result.is_accepted
    assert result.series == ()
    assert result.report.rules(Severity.ERROR) == {rule}


def test_unknown_file_name_is_rejected() -> None:
    result = PortalCsvParser().parse(BROKEN / "unknown_name" / "export.csv")
    assert result.report.rules(Severity.ERROR) == {"sensor-id"}
    assert "export.csv" in result.report.errors[0].message


def test_truncated_xlsx_is_rejected() -> None:
    result = PortalXlsxParser().parse(BROKEN / "truncated_xlsx" / "MeteoData_8615620 77678271.xlsx")
    assert result.report.rules(Severity.ERROR) == {"file-readable"}


def test_duplicated_rows_keep_last_and_warn() -> None:
    result = PortalCsvParser().parse(BROKEN / "duplicated_rows" / PORTAL_CSV_NAME)
    frame = only_series(result)
    (issue,) = result.report.issues
    assert issue.rule == "duplicate-timestamps"
    assert issue.severity is Severity.WARNING
    assert issue.message.startswith("3 row(s) repeat an earlier timestamp (1 with different")
    assert issue.row == 12  # data line 10 (source row 12) is repeated twice after it
    assert len(frame) == 48
    # Source row 24 repeats row 23 with 9,9 °C; the last occurrence wins.
    assert frame["temp_c"].iloc[19] == pytest.approx(9.9)


def test_unsorted_rows_are_sorted_with_warning() -> None:
    result = PortalCsvParser().parse(BROKEN / "unsorted_rows" / PORTAL_CSV_NAME)
    frame = only_series(result)
    (issue,) = result.report.issues
    assert (issue.rule, issue.row) == ("monotonic-order", 9)
    assert issue.message.startswith("2 row(s)")
    assert len(frame) == 48
    assert frame["timestamp_utc"].is_monotonic_increasing


def test_truncated_last_csv_line_is_a_warning() -> None:
    result = PortalCsvParser().parse(BROKEN / "truncated_csv" / PORTAL_CSV_NAME)
    frame = only_series(result)
    (issue,) = result.report.issues
    assert (issue.rule, issue.row, issue.severity) == ("short-rows", 50, Severity.WARNING)
    assert frame["temp_c"].iloc[-1] == pytest.approx(3.9)
    assert np.isnan(frame["rh_pct"].iloc[-1])
    assert frame["qc"].iloc[-1] == 0  # temperature is present: the row is not MISSING


def test_missing_file(tmp_path: Path) -> None:
    result = PortalCsvParser().parse(tmp_path / PORTAL_CSV_NAME)
    assert result.report.rules() == {"file-exists"}
    assert PortalCsvParser().parse(tmp_path).report.rules() == {"file-exists"}


def test_few_unparseable_values_become_missing(write_csv: CsvWriter) -> None:
    rows = [[f"2026-01-01 {hour:02d}:00:00", "1,5", "80"] for hour in range(21)]
    rows[3] = ["2026-01-01 03:00:00", "x", "x"]
    rows[4] = ["2026-01-01 04:00:00", "", "81,5"]
    result = PortalCsvParser().parse(write_csv(rows))
    frame = only_series(result)
    (issue_temp, issue_rh) = result.report.issues
    assert issue_temp.severity is Severity.WARNING
    assert issue_temp.message.startswith("Column 'Teplota (°C)': 1 of 21 value(s)")
    assert issue_temp.row == 6
    assert "Vlhkost" in issue_rh.message
    assert frame["qc"].tolist()[3:5] == [int(QcFlag.MISSING), 0]
    assert np.isnan(frame["temp_c"].iloc[4])
    assert frame["rh_pct"].iloc[4] == pytest.approx(81.5)


def test_few_unparseable_timestamps_are_dropped(write_csv: CsvWriter) -> None:
    rows = [[f"2026-01-01 {hour:02d}:00:00", "1,5", "80"] for hour in range(21)]
    rows[5][0] = "31.02.2026 05:00:00"
    result = PortalCsvParser().parse(write_csv(rows))
    frame = only_series(result)
    (issue,) = result.report.issues
    assert (issue.rule, issue.severity, issue.row) == ("timestamps-parseable", "warning", 8)
    assert len(frame) == 20


def test_few_out_of_bounds_values_are_a_warning(write_csv: CsvWriter) -> None:
    rows = [[f"2026-01-01 {hour:02d}:00:00", "1,5", "80"] for hour in range(21)]
    rows[0][1] = "85"
    rows[1][2] = "100,1"
    result = PortalCsvParser().parse(write_csv(rows))
    frame = only_series(result)
    assert [issue.rule for issue in result.report.warnings] == [
        "temperature-bounds",
        "humidity-bounds",
    ]
    assert frame["temp_c"].iloc[0] == 85.0  # left to quality control (WP-1.5)


def test_header_variants(write_csv: CsvWriter) -> None:
    rows = [["2026-07-01 12:00", "21.5", "55", "x"], ["2026-07-01 12:30", "-0,5", "60", ""]]
    header = ("ZEITSTEMPEL", "Lufttemperatur [degC]", "rel. feuchte", "Poznámka")
    result = PortalCsvParser().parse(write_csv(rows, header=header, title="a;b\r\n;\r\nc"))
    assert result.report.rules(Severity.ERROR) == {"required-columns"}
    header = ("ZEITSTEMPEL", "Lufttemperatur [degC]", "Relative humidity (% RH)", "Poznámka")
    frame = only_series(PortalCsvParser().parse(write_csv(rows, header=header)))
    assert frame["timestamp_utc"].tolist() == utc("2026-07-01 10:00", "2026-07-01 10:30")
    assert frame["temp_c"].tolist() == [21.5, -0.5]


def test_duplicate_column_is_rejected(write_csv: CsvWriter) -> None:
    rows = [["2026-07-01 12:00", "21,5", "20", "55"]]
    header = ("Datum a čas", "Teplota", "Temperature (°C)", "Vlhkost")
    result = PortalCsvParser().parse(write_csv(rows, header=header))
    (issue,) = result.report.errors
    assert "'Teplota' and 'Temperature (°C)' both denote temp_c" in issue.message


def test_timestamp_with_qualifier_is_rejected(write_csv: CsvWriter) -> None:
    rows = [["2026-07-01 12:00", "21,5", "55"]]
    header = ("Datum a čas (UTC)", "Teplota", "Vlhkost")
    result = PortalCsvParser().parse(write_csv(rows, header=header))
    assert "unit 'UTC' is not accepted for timestamp" in result.report.errors[0].message


def test_no_header_in_search_rows(write_csv: CsvWriter) -> None:
    rows = [["2026-07-01 12:00", "21,5", "55"]]
    title = "\r\n".join(["x;y"] * 3)
    settings = ParserSettings(header_search_rows=3)
    result = PortalCsvParser(settings).parse(write_csv(rows, title=title))
    (issue,) = result.report.errors
    assert issue.message == "No header row with a timestamp column in the first 3 rows."
    assert PortalCsvParser().parse(write_csv(rows, title=title)).is_accepted


def test_cp1250_and_bom(write_csv: CsvWriter) -> None:
    rows = [["2026-07-01 12:00", "21,5", "55"]]
    assert PortalCsvParser().parse(write_csv(rows, encoding="cp1250")).is_accepted
    assert PortalCsvParser().parse(write_csv(rows, encoding="utf-8-sig")).is_accepted


def test_undecodable_and_binary_csv(tmp_path: Path) -> None:
    path = tmp_path / PORTAL_CSV_NAME
    path.write_bytes(b"\x81\x83\x88\x90\x98")
    result = PortalCsvParser().parse(path)
    assert result.report.rules() == {"file-readable"}
    assert "not valid text" in result.report.errors[0].message
    path.write_bytes(b"Datum a cas;Teplota\x00;Vlhkost\r\n")
    assert "NUL" in PortalCsvParser().parse(path).report.errors[0].message


def test_invalid_csv_field(tmp_path: Path) -> None:
    path = tmp_path / PORTAL_CSV_NAME
    path.write_text("Datum a čas;" + "9" * 200_000 + "\r\n", encoding="utf-8")
    result = PortalCsvParser().parse(path)
    assert result.report.rules() == {"file-readable"}
    assert "invalid CSV" in result.report.errors[0].message


def test_portal_xlsx_extra_sheets_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "MeteoData_8615620 77678271.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["Datum a čas", "Teplota (°C)", "Vlhkost (%)"])
    sheet.append([datetime(2026, 7, 1, 12), 21.5, 55])
    workbook.create_sheet("Info").append(["synthetic"])
    workbook.save(path)
    result = PortalXlsxParser().parse(path)
    assert result.is_accepted
    (issue,) = result.report.issues
    assert (issue.rule, issue.severity) == ("expected-tables", Severity.WARNING)
    assert "Info" in issue.message


def test_portal_xlsx_naming() -> None:
    parser = PortalXlsxParser()
    assert parser.can_parse(Path("MeteoData_8615620 77678271.xlsx"))
    assert parser.can_parse(Path("77678271 (VUT).XLSX"))
    assert parser.can_parse(Path("meteodata_unknown.xlsm"))
    assert not parser.can_parse(Path("data.xlsx"))
    assert not parser.can_parse(Path("MeteoData_8615620 77678271.csv"))
    assert PortalCsvParser().can_parse(Path("export.CSV"))
    assert not is_portal_export_name(Path("8271.xlsx"))
