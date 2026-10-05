"""Tests of YearPartitioning."""

from __future__ import annotations

import pandas as pd
import pytest

from sivin.storage.partitioning import YearPartitioning, partitioning_registry


def test_keys_are_utc_years_not_local_years() -> None:
    # 00:30 local time on 1 Jan 2026 in Prague (CET, UTC+1) is 23:30 UTC on 31 Dec 2025.
    local = pd.Series(pd.DatetimeIndex(["2026-01-01 00:30", "2026-07-01 12:00"]))
    times = local.dt.tz_localize("Europe/Prague")
    assert YearPartitioning().keys_of(times).tolist() == ["2025", "2026"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2026", True), ("0999", True), ("26", False), ("2026a", False), (".2026", False)],
)
def test_is_key(text: str, expected: bool) -> None:
    assert YearPartitioning().is_key(text) is expected


def test_bounds_are_half_open_utc_year() -> None:
    start, end = YearPartitioning().bounds("2026")
    assert start == pd.Timestamp("2026-01-01T00:00:00Z")
    assert end == pd.Timestamp("2027-01-01T00:00:00Z")


def test_bounds_reject_invalid_key() -> None:
    with pytest.raises(ValueError, match="four-digit year"):
        YearPartitioning().bounds("26")


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2025-06-01T00:00:00Z", "2025-12-31T23:59:59Z", False),
        ("2025-06-01T00:00:00Z", "2026-01-01T00:00:00Z", True),
        ("2026-12-31T23:59:59Z", "2027-06-01T00:00:00Z", True),
        ("2027-01-01T00:00:00Z", "2027-06-01T00:00:00Z", False),
    ],
)
def test_overlaps_with_inclusive_request(start: str, end: str, expected: bool) -> None:
    assert YearPartitioning().overlaps("2026", pd.Timestamp(start), pd.Timestamp(end)) is expected


def test_registered_as_year() -> None:
    assert partitioning_registry.get("year") is YearPartitioning
