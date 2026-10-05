"""Tests of MonthDay and Season."""

from __future__ import annotations

from datetime import date

import pytest

from sivin.core.season import MonthDay, Season


def test_month_day_validation_and_leap_day() -> None:
    assert MonthDay(2, 29).in_year(2024) == date(2024, 2, 29)
    assert MonthDay(2, 29).in_year(2026) == date(2026, 2, 28)
    assert str(MonthDay(4, 1)) == "04-01"
    for month, day in [(0, 1), (13, 1), (4, 31), (2, 30)]:
        with pytest.raises(ValueError, match="Invalid month-day"):
            MonthDay(month, day)


def test_named_seasons() -> None:
    assert Season.vegetation().dates(2026) == (date(2026, 4, 1), date(2026, 10, 31))
    assert Season.huglin().dates(2026) == (date(2026, 4, 1), date(2026, 9, 30))
    assert Season.month(9).dates(2026) == (date(2026, 9, 1), date(2026, 9, 30))
    assert Season.month(2).dates(2026) == (date(2026, 2, 1), date(2026, 2, 28))
    assert Season.month(2).dates(2028) == (date(2028, 2, 1), date(2028, 2, 29))
    assert str(Season.huglin()) == "04-01..09-30"


def test_n_days() -> None:
    # April 30 + May 31 + June 30 + July 31 + August 31 + September 30 = 183
    assert Season.huglin().n_days(2026) == 183
    assert Season.vegetation().n_days(2026) == 214
    assert Season.month(2).n_days(2028) == 29


def test_contains_is_inclusive() -> None:
    season = Season.huglin()
    assert season.contains(date(2026, 4, 1))
    assert season.contains(date(2026, 9, 30))
    assert not season.contains(date(2026, 3, 31))
    assert not season.contains(date(2026, 10, 1))


def test_season_crossing_new_year_is_rejected() -> None:
    with pytest.raises(ValueError, match="crosses the new year"):
        Season(MonthDay(11, 1), MonthDay(3, 31))
