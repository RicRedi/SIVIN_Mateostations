"""Indices built on daily aggregates: cool_night, dtr_ripening, tropical_days_nights,
winter_freeze. All data are synthetic, chosen so that the results can be computed by hand."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from sivin.analytics.base import IndexContext
from sivin.analytics.ripening import (
    CharacteristicDaysIndex,
    CoolNightIndex,
    DtrRipeningIndex,
    DtrRipeningParams,
    WinterFreezeIndex,
    WinterFreezeParams,
)

from .conftest import ContextFactory, DaySeriesFactory, two_level_day


class TestCoolNight:
    def test_hand_computed_mean_and_class(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # September minima 10, 13, 16 °C -> CI = 39/3 = 13.0 °C -> cool nights (12 < CI <= 14).
        # An August day (min 2 °C) lies outside the period. Coverage 3/30 = 0.1.
        series = hourly_days(
            {
                date(2026, 8, 31): two_level_day(2.0, 20.0),
                date(2026, 9, 1): two_level_day(10.0, 25.0),
                date(2026, 9, 2): two_level_day(13.0, 25.0),
                date(2026, 9, 3): two_level_day(16.0, 25.0),
            }
        )
        result = CoolNightIndex().compute(make_context(series, 2026))
        assert result.value == pytest.approx(13.0)
        assert result.classification == "cool_nights"
        assert result.coverage == pytest.approx(0.1)
        assert result.complete is False
        assert result.unit == "°C"
        assert result.details["n_days"] == 3
        assert result.daily is not None
        assert result.daily.tolist() == [10.0, 13.0, 16.0]

    def test_complete_with_low_season_threshold(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        series = hourly_days({date(2026, 9, 1): two_level_day(19.0, 30.0)})
        result = CoolNightIndex().compute(make_context(series, 2026, min_season_coverage=0.0))
        assert result.complete is True
        assert result.classification == "warm_nights"

    def test_incomplete_day_is_ignored(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # Sep 1 has only 12 valid hourly temperatures (coverage 0.5 < 0.9) and is ignored;
        # Sep 2 is complete with minimum 12 °C -> CI = 12.0 -> very cool nights (CI <= 12).
        temps = {
            date(2026, 9, 1): [float("nan")] * 12 + [30.0] * 12,
            date(2026, 9, 2): two_level_day(12.0, 22.0),
        }
        result = CoolNightIndex().compute(make_context(hourly_days(temps), 2026))
        assert result.value == pytest.approx(12.0)
        assert result.classification == "very_cool_nights"
        assert result.details["n_days"] == 1


class TestDtrRipening:
    @pytest.fixture
    def context(self, hourly_days: DaySeriesFactory, make_context: ContextFactory) -> IndexContext:
        # Aug 1-3: (Tmin, Tmax) = (15, 25), (14, 30), (18, 20) -> ranges 10, 16, 2 °C.
        series = hourly_days(
            {
                date(2026, 7, 31): two_level_day(0.0, 30.0),
                date(2026, 8, 1): two_level_day(15.0, 25.0),
                date(2026, 8, 2): two_level_day(14.0, 30.0),
                date(2026, 8, 3): two_level_day(18.0, 20.0),
            }
        )
        return make_context(series, 2026)

    def test_fixed_window(self, context: IndexContext) -> None:
        # (10 + 16 + 2) / 3 = 9.3333 °C over the default window Aug 1 - Sep 30 (61 days).
        result = DtrRipeningIndex().compute(context)
        assert result.value == pytest.approx(28.0 / 3.0)
        assert result.coverage == pytest.approx(3 / 61)
        assert result.details["window_start"] == "2026-08-01"
        assert result.details["window_end"] == "2026-09-30"
        assert result.daily is not None
        assert result.daily.tolist() == [10.0, 16.0, 2.0]

    def test_explicit_start_date(self, context: IndexContext) -> None:
        # From Aug 2 (e.g. modelled veraison): (16 + 2) / 2 = 9.0 °C over 60 days.
        params = DtrRipeningParams(start_date=date(2026, 8, 2))
        result = DtrRipeningIndex(params).compute(context)
        assert result.value == pytest.approx(9.0)
        assert result.coverage == pytest.approx(2 / 60)
        assert result.details["window_start"] == "2026-08-02"

    def test_start_date_in_other_year(self, context: IndexContext) -> None:
        params = DtrRipeningParams(start_date=date(2025, 8, 2))
        with pytest.raises(ValueError, match="season year 2026"):
            DtrRipeningIndex(params).compute(context)

    def test_start_date_after_window_end(self) -> None:
        with pytest.raises(ValidationError, match="after period_end"):
            DtrRipeningParams(start_date=date(2026, 10, 2))


class TestCharacteristicDays:
    def test_hand_computed_counts(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # (Tmin, Tmax) per day and the categories it belongs to:
        # Jan 10 (-5, -1): frost day, ice day        Jan 11 (-0.5, 3): frost day
        # Jan 12 (0, 5): none (frost day needs Tmin < 0)
        # Jul 10 (21, 31): tropical day + night, summer day
        # Jul 11 (15, 26): summer day                Jul 12 (19.9, 30): tropical day, summer day
        series = hourly_days(
            {
                date(2026, 1, 10): two_level_day(-5.0, -1.0),
                date(2026, 1, 11): two_level_day(-0.5, 3.0),
                date(2026, 1, 12): two_level_day(0.0, 5.0),
                date(2026, 7, 10): two_level_day(21.0, 31.0),
                date(2026, 7, 11): two_level_day(15.0, 26.0),
                date(2026, 7, 12): two_level_day(19.9, 30.0),
            }
        )
        result = CharacteristicDaysIndex().compute(make_context(series, 2026))
        assert result.value == 2.0
        assert result.unit == "d"
        assert dict(result.details) == {
            "n_days": 6,
            "tropical_days": 2,
            "tropical_nights": 1,
            "summer_days": 3,
            "frost_days": 2,
            "ice_days": 1,
        }
        assert result.coverage == pytest.approx(6 / 365)
        assert result.daily is not None
        assert result.daily.tolist() == [0.0, 0.0, 0.0, 1.0, 1.0, 2.0]


class TestWinterFreeze:
    def test_winter_ending_in_season_year(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # Season 2026 = 2025-11-01 .. 2026-03-31 (30 + 31 + 31 + 28 + 31 = 151 days).
        # Minima: Dec 15 -16 (damage), Jan 10 -21 (damage + severe), Feb 1 -15 (not below -15),
        # Nov 15 2026 -25 belongs to the winter 2027 and is ignored.
        series = hourly_days(
            {
                date(2025, 12, 15): two_level_day(-16.0, -5.0),
                date(2026, 1, 10): two_level_day(-21.0, -8.0),
                date(2026, 2, 1): two_level_day(-15.0, 0.0),
                date(2026, 11, 15): two_level_day(-25.0, -10.0),
            }
        )
        result = WinterFreezeIndex().compute(make_context(series, 2026))
        assert result.value == 2.0
        assert result.details["severe_days"] == 1
        assert result.details["min_temp_c"] == -21.0
        assert result.details["n_days"] == 3
        assert result.coverage == pytest.approx(3 / 151)
        assert result.complete is False
        assert result.daily is not None
        assert result.daily.tolist() == [-16.0, -21.0, -15.0]

    def test_missing_previous_autumn_gives_no_value(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # Only January data (as if the context held the season year only): two damage days
        # exist, but half a winter must not be reported as a count.
        series = hourly_days(
            {
                date(2026, 1, 10): two_level_day(-21.0, -8.0),
                date(2026, 1, 11): two_level_day(-16.0, -8.0),
            }
        )
        result = WinterFreezeIndex().compute(make_context(series, 2026))
        assert result.value is None
        assert result.details["status"] == "previous_autumn_missing"
        assert result.coverage == pytest.approx(2 / 151)
        assert result.complete is False

    def test_window_must_cross_new_year(self) -> None:
        with pytest.raises(ValidationError, match="cross New Year"):
            WinterFreezeParams(dormant_start="01-01", dormant_end="03-31")

    def test_thresholds_ordered(self) -> None:
        with pytest.raises(ValidationError, match="severe_threshold_c"):
            WinterFreezeParams(damage_threshold_c=-20.0, severe_threshold_c=-15.0)
