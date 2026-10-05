"""Tests of the cell readers (numbers with a decimal comma, local timestamps)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from sivin.ingest.parsers.cells import DateOrderCheck, NumberParser, TimestampParser


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
        (10**400, None),
        ("9" * 400, None),
        (-(10**309), None),
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
        (datetime(2026, 1, 5), datetime(2026, 1, 5)),  # date-formatted cell: local midnight
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


def test_date_order_check() -> None:
    check = DateOrderCheck(day_first=True, max_regular_step_s=86400)
    cells = ["1/3/2026 10:00", "1/3/2026 23:00", "1/4/2026 10:00", "1/5/2026 10:00"]
    parsed = TimestampParser(day_first=True).parse(cells)
    problem = check.problem(cells, parsed)
    assert problem is not None
    assert problem.startswith("Ambiguous date order: read as configured, 2 step(s)")
    unique = ["13/3/2026 10:00", "1/3/2026 10:00", "1/4/2026 10:00"]
    assert check.problem(unique, TimestampParser(day_first=True).parse(unique)) is None
    regular = ["1/3/2026 10:00", "1/3/2026 10:30"]
    assert check.problem(regular, TimestampParser(day_first=True).parse(regular)) is None


def test_date_order_check_counts_readable_cells() -> None:
    check = DateOrderCheck(day_first=True, max_regular_step_s=86400)
    cells = ["1/5/2026 17:33:01", "1/5/2026 18:03:26", "1/13/2026 18:03:26"]
    problem = check.problem(cells, TimestampParser(day_first=True).parse(cells))
    assert problem == (
        "Ambiguous date order: 2 of 3 timestamp(s) read as configured, 3 with day and month "
        "swapped. Check 'day_first'."
    )
    garbage = ["x", "1.3.2026 10:00"]
    assert check.problem(garbage, TimestampParser(day_first=True).parse(garbage)) is None
