"""Optional precipitation, counter and battery columns in the parsers (WP-1.9).

All files are SYNTHETIC, written by the ``write_csv`` fixture.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sivin.core.flags import QcFlag
from sivin.ingest.parsers.base import ParsedExport, parser_registry
from sivin.ingest.parsers.columns import (
    OPTIONAL_CANONICAL_COLUMNS,
    REQUIRED_CANONICAL_COLUMNS,
    CanonicalColumn,
    ColumnAliases,
    ColumnMapping,
)
from sivin.ingest.validation import Severity, ValidationSettings

from .conftest import CsvWriter, make_settings

PORTAL_HEADER = (
    "Datum a čas",
    "Teplota (°C)",
    "Vlhkost (%)",
    "Srážky (mm)",
    "Celkové srážky (mm)",
    "Nabití baterie (V)",
)
"""The header of the provider's CSV export (confirmed by the first real export)."""

ROWS = [
    ("2026-03-01 12:00:00", "5,0", "80,0", "0,0", "100,0", "3,60"),
    ("2026-03-01 12:30:00", "5,5", "81,0", "0,3", "100,3", "3,50"),
    ("2026-03-01 13:00:00", "6,0", "82,0", "0,0", "100,3", "3,50"),
]
"""Synthetic rows, oldest first, local time (CET)."""


def _parse(
    path_writer: CsvWriter, rows: list[tuple[str, ...]], header: tuple[str, ...]
) -> ParsedExport:
    path = path_writer(rows, header=header)
    return parser_registry.for_file(path, make_settings()).parse(path)


def test_required_and_optional_columns() -> None:
    assert REQUIRED_CANONICAL_COLUMNS == (
        CanonicalColumn.TIMESTAMP,
        CanonicalColumn.TEMP,
        CanonicalColumn.RH,
    )
    assert OPTIONAL_CANONICAL_COLUMNS == (
        CanonicalColumn.PRECIP,
        CanonicalColumn.PRECIP_TOTAL,
        CanonicalColumn.BATTERY,
    )


@pytest.mark.parametrize(
    ("text", "column"),
    [
        ("Srážky (mm)", CanonicalColumn.PRECIP),
        ("  SRAZKY  (mm) ", CanonicalColumn.PRECIP),
        ("Niederschlag [mm]", CanonicalColumn.PRECIP),
        ("Rainfall", CanonicalColumn.PRECIP),
        ("Celkové srážky (mm)", CanonicalColumn.PRECIP_TOTAL),
        ("celkove srazky", CanonicalColumn.PRECIP_TOTAL),
        ("Gesamtniederschlag (mm)", CanonicalColumn.PRECIP_TOTAL),
        ("Cumulative precipitation (mm)", CanonicalColumn.PRECIP_TOTAL),
        ("Nabití baterie (V)", CanonicalColumn.BATTERY),
        ("nabiti BATERIE", CanonicalColumn.BATTERY),
        ("Batteriespannung (V)", CanonicalColumn.BATTERY),
        ("Battery voltage [V]", CanonicalColumn.BATTERY),
    ],
)
def test_aliases_ignore_case_diacritics_and_units(text: str, column: CanonicalColumn) -> None:
    cell = ColumnMapping(ColumnAliases()).classify(text)
    assert (cell.column, cell.accepted) == (column, True)


def test_wrong_units_of_optional_columns_are_not_accepted() -> None:
    mapping = ColumnMapping(ColumnAliases())
    assert not mapping.classify("Srážky (in)").accepted
    assert not mapping.classify("Nabití baterie (mV)").accepted


def test_portal_header_reads_all_six_columns(write_csv: CsvWriter) -> None:
    parsed = _parse(write_csv, ROWS, PORTAL_HEADER)
    assert parsed.is_accepted
    assert parsed.report.issues == ()
    (series,) = parsed.series
    frame = series.frame
    assert frame["precip_mm"].tolist() == [0.0, 0.3, 0.0]
    assert frame["precip_total_mm"].tolist() == [100.0, 100.3, 100.3]
    assert frame["battery_v"].tolist() == [3.6, 3.5, 3.5]
    assert frame["temp_c"].tolist() == [5.0, 5.5, 6.0]


def test_german_and_english_headers_in_any_column_order(write_csv: CsvWriter) -> None:
    header = (
        "Batteriespannung (V)",
        "Zeitstempel",
        "Total precipitation (mm)",
        "Temperature (°C)",
        "Humidity (%)",
        "Niederschlag (mm)",
    )
    rows = [(r[5], r[0], r[4], r[1], r[2], r[3]) for r in ROWS]
    (series,) = _parse(write_csv, rows, header).series
    assert series.frame["precip_mm"].tolist() == [0.0, 0.3, 0.0]
    assert series.frame["precip_total_mm"].tolist() == [100.0, 100.3, 100.3]
    assert series.frame["battery_v"].tolist() == [3.6, 3.5, 3.5]


def test_file_without_optional_columns_stays_valid(write_csv: CsvWriter) -> None:
    rows = [row[:3] for row in ROWS]
    parsed = _parse(write_csv, rows, PORTAL_HEADER[:3])
    assert parsed.report.issues == ()
    frame = parsed.series[0].frame
    assert frame[["precip_mm", "precip_total_mm", "battery_v"]].isna().all().all()
    assert (frame["qc"] == int(QcFlag.OK)).all()


def test_missing_optional_values_never_set_missing(write_csv: CsvWriter) -> None:
    rows = [
        ("2026-03-01 12:00:00", "5,0", "80,0", "", "", ""),
        ("2026-03-01 12:30:00", "5,5", "", "0,3", "100,3", "3,50"),
    ]
    frame = _parse(write_csv, rows, PORTAL_HEADER).series[0].frame
    assert frame["qc"].tolist() == [int(QcFlag.OK), int(QcFlag.MISSING)]
    assert math.isnan(frame["precip_mm"].iloc[0])
    assert frame["battery_v"].tolist()[1] == 3.5


def test_optional_column_with_a_wrong_unit_is_dropped_with_a_warning(
    write_csv: CsvWriter,
) -> None:
    header = (*PORTAL_HEADER[:3], "Srážky (in)", *PORTAL_HEADER[4:])
    parsed = _parse(write_csv, ROWS, header)
    assert parsed.is_accepted
    (issue,) = parsed.report.issues
    assert (issue.rule, issue.severity, issue.row) == ("optional-columns", Severity.WARNING, 2)
    assert "unit 'in' is not accepted for precip_mm" in issue.message
    frame = parsed.series[0].frame
    assert frame["precip_mm"].isna().all()
    assert frame["precip_total_mm"].tolist() == [100.0, 100.3, 100.3]


def test_two_headers_for_one_optional_column_drop_it(write_csv: CsvWriter) -> None:
    header = (*PORTAL_HEADER[:4], "Srážky (mm)", PORTAL_HEADER[5])
    parsed = _parse(write_csv, ROWS, header)
    assert parsed.is_accepted
    assert parsed.report.rules(Severity.WARNING) == frozenset({"optional-columns"})
    frame = parsed.series[0].frame
    assert frame[["precip_mm", "precip_total_mm"]].isna().all().all()
    assert frame["battery_v"].tolist() == [3.6, 3.5, 3.5]


def test_unparseable_optional_values_are_only_a_warning(write_csv: CsvWriter) -> None:
    rows = [(*row[:3], "n/a", row[4], row[5]) for row in ROWS]
    parsed = _parse(write_csv, rows, PORTAL_HEADER)
    assert parsed.is_accepted
    (issue,) = parsed.report.issues
    assert (issue.rule, issue.severity) == ("numbers-parseable", Severity.WARNING)
    assert "'Srážky (mm)': 3 of 3 value(s) are not numbers" in issue.message
    assert "read as missing" in issue.message
    assert parsed.series[0].frame["precip_mm"].isna().all()


def test_unparseable_temperature_still_rejects(write_csv: CsvWriter) -> None:
    rows = [(row[0], "x", *row[2:]) for row in ROWS]
    parsed = _parse(write_csv, rows, PORTAL_HEADER)
    assert not parsed.is_accepted
    assert "numbers-parseable" in parsed.report.rules(Severity.ERROR)


@pytest.mark.parametrize(
    ("position", "value", "rule", "bounds"),
    [
        (3, "-0,1", "precipitation-bounds", "[0, 500] mm"),
        (4, "-5,0", "precipitation-total-bounds", "[0, 100000] mm"),
        (5, "3600", "battery-bounds", "[0, 10] V"),
    ],
)
def test_gross_bounds_of_optional_columns_never_reject(
    write_csv: CsvWriter, position: int, value: str, rule: str, bounds: str
) -> None:
    rows = [tuple(value if i == position else cell for i, cell in enumerate(row)) for row in ROWS]
    parsed = _parse(write_csv, rows, PORTAL_HEADER)
    assert parsed.is_accepted
    (issue,) = parsed.report.issues
    assert (issue.rule, issue.severity, issue.row) == (rule, Severity.WARNING, 3)
    assert issue.message.startswith("3 ")
    assert bounds in issue.message
    assert "wrong unit" not in issue.message
    column = parsed.series[0].frame.iloc[:, position]
    assert np.all(column.to_numpy() == float(value.replace(",", ".")))


def test_duplicates_with_different_precipitation_count_as_conflicting(
    write_csv: CsvWriter,
) -> None:
    rows = [ROWS[0], (*ROWS[0][:3], "0,6", *ROWS[0][4:]), ROWS[1]]
    parsed = _parse(write_csv, rows, PORTAL_HEADER)
    (issue,) = parsed.report.issues
    assert issue.rule == "duplicate-timestamps"
    assert "1 row(s) repeat an earlier timestamp (1 with different values)" in issue.message


def test_settings_bounds_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="battery"):
        ValidationSettings(battery_min_v=5.0, battery_max_v=4.0)
    with pytest.raises(ValueError, match="precip_total"):
        ValidationSettings(precip_total_min_mm=1.0, precip_total_max_mm=1.0)
