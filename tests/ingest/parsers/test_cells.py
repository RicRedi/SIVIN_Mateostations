"""Tests of the cell readers (numbers with a decimal comma, local timestamps)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from sivin.ingest.parsers.cells import NumberParser, TimestampParser


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("12,5", 12.5),
        (" -3,25 ", -3.25),
        ("\u22121,5", -1.5),
        ("7", 7.0),
        ("1.5", 1.5),
        (",5", 0.5),
        ("1e2", 100.0),
        ("1 000", 1000.0),
        (4, 4.0),
        (2.5, 2.5),
        ("1.000,5", None),
        ("abc", None),
        ("nan", None),
        ("inf", None),
        ("1e999", None),
        (float("inf"), None),
        (True, None),
        (datetime(2026, 1, 1), None),
    ],
)
def test_parse_cell(cell: object, expected: float | None) -> None:
    assert NumberParser.parse_cell(cell) == expected


def test_parse_column() -> None:
    values, unparseable = NumberParser().parse(["1,5", None, "  ", "x", 2])
    np.testing.assert_array_equal(values, [1.5, np.nan, np.nan, np.nan, 2.0])
    assert unparseable.tolist() == [False, False, False, True, False]


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("2026-03-01 22:38:57", datetime(2026, 3, 1, 22, 38, 57)),
        ("2026-03-01T22:38", datetime(2026, 3, 1, 22, 38)),
        ("5.1.2026 17:33:01", datetime(2026, 1, 5, 17, 33, 1)),
        ("5. 1. 2026 17:33", datetime(2026, 1, 5, 17, 33)),
        ("05/01/2026 17:33:01", datetime(2026, 1, 5, 17, 33, 1)),
        (datetime(2026, 1, 5, 17, 33, 1), datetime(2026, 1, 5, 17, 33, 1)),
        (datetime(2026, 1, 5, tzinfo=UTC), None),
        (date(2026, 1, 5), None),
        ("31.02.2026 10:00", None),
        ("1.1.9999 00:00", None),
        ("2026-01-05", None),
        (45000.5, None),
        (None, None),
    ],
)
def test_parse_timestamp_cell(cell: object, expected: datetime | None) -> None:
    assert TimestampParser(day_first=True).parse_cell(cell) == expected


def test_month_first() -> None:
    parser = TimestampParser(day_first=False)
    assert parser.parse_cell("5.1.2026 17:33:01") == datetime(2026, 5, 1, 17, 33, 1)
    assert "%m.%d.%Y %H:%M:%S" in parser.formats


def test_parse_timestamp_column() -> None:
    result = TimestampParser(day_first=True).parse(["2026-01-01 00:00", "x"])
    assert result.dtype == "datetime64[ns]"
    assert result.iloc[0] == pd.Timestamp("2026-01-01")
    assert pd.isna(result.iloc[1])
