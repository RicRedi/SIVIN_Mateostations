"""Pure column builders of the site files (hand-computed values; all data synthetic)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from sivin.site.columns import (
    iso_dates,
    iso_utc_seconds,
    local_years,
    rounded,
    rounded_value,
    unix_second,
    unix_seconds,
    utc_month_keys,
)

NEW_YEAR_2026_S = 1_767_225_600
"""2026-01-01T00:00:00Z in Unix seconds: 56 years since 1970 incl. 14 leap days =
(56 * 365 + 14) * 86 400 s."""


def test_new_year_constant_is_hand_computed() -> None:
    assert NEW_YEAR_2026_S == (56 * 365 + 14) * 86_400


def test_unix_seconds_any_zone_and_resolution() -> None:
    times = pd.Series(
        pd.DatetimeIndex(["2026-01-01T01:00:00", "2026-01-01T01:30:25.900"])
        .tz_localize("Europe/Prague")
        .as_unit("us")
    )
    # 01:00 CET = 00:00 UTC; fractions are cut (floor), not rounded.
    assert unix_seconds(times) == [NEW_YEAR_2026_S, NEW_YEAR_2026_S + 1825]


def test_unix_seconds_before_the_epoch_round_down() -> None:
    index = pd.DatetimeIndex(["1969-12-31T23:59:59.5Z"])
    assert unix_seconds(index) == [-1]


def test_unix_second_of_a_datetime() -> None:
    assert unix_second(datetime(2026, 1, 1, tzinfo=UTC)) == NEW_YEAR_2026_S


def test_rounded_keeps_missing_and_normalises_negative_zero() -> None:
    assert rounded([12.344, np.nan, -0.001, 3.6, 81.0], 2) == [12.34, None, 0.0, 3.6, 81.0]
    assert str(rounded([-0.001], 2)[0]) == "0.0"


def test_rounded_value() -> None:
    assert rounded_value(None, 2) is None
    assert rounded_value(float("nan"), 2) is None
    assert rounded_value(0.92857, 2) == 0.93


def test_utc_month_keys_follow_utc_not_local_time() -> None:
    times = pd.Series(
        [
            pd.Timestamp("2026-06-30T23:30:00Z"),
            pd.Timestamp("2026-07-01T00:30:00+02:00").tz_convert("UTC"),
            pd.Timestamp("2026-07-01T00:00:00Z"),
        ]
    )
    # 00:30 CEST on 1 July is 22:30 UTC on 30 June.
    assert list(utc_month_keys(times)) == ["2026-06", "2026-06", "2026-07"]


def test_local_years_in_the_display_zone() -> None:
    first = pd.Timestamp("2025-07-30T08:00:00Z")
    last = pd.Timestamp("2025-12-31T23:30:00Z")  # 00:30 local on 1 January 2026
    assert local_years(first, last, "Europe/Prague") == (2025, 2026)
    assert local_years(first, last, "UTC") == (2025,)


def test_iso_dates() -> None:
    assert iso_dates([datetime(2026, 1, 2).date()]) == ["2026-01-02"]


def test_iso_utc_seconds() -> None:
    moment = datetime(2026, 10, 5, 6, 0, 1, 900_000, tzinfo=pd.Timestamp(0, tz="Europe/Prague").tz)
    assert iso_utc_seconds(moment) == "2026-10-05T04:00:01Z"


def test_iso_utc_seconds_rejects_naive_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        iso_utc_seconds(datetime(2026, 10, 5))
