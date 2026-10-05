"""Tests of DailyWeather on small hand-computed synthetic examples."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
import pytest

from sivin.core.daily import DAILY_COLUMNS, DailyWeather
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries, SchemaError

PRAGUE = "Europe/Prague"
EXCLUDE = int(QcFlag.DEFAULT_EXCLUDE)
SIX_HOURS_S = 6 * 3600.0
ONE_HOUR_S = 3600.0

SeriesFactory = Callable[..., MeasurementSeries]


@pytest.fixture
def two_days(make_series: SeriesFactory) -> DailyWeather:
    """Synthetic 6-hourly data: a full day, a day with a gap/excluded/NaN sample, an empty day.

    Day 2026-01-10: 4 valid samples           -> coverage 4 * 6 h / 24 h = 1.0
    Day 2026-01-11: 00:00 valid (STEP flag is informative), 03:00 valid,
                    06:00 SPIKE (excluded), 12:00 absent (gap),
                    18:00 temperature NaN, humidity 50 % (the whole row is invalid)
                    -> 2 valid samples        -> coverage 2 * 6 h / 24 h = 0.5
    Day 2026-01-12: no sample                 -> coverage 0
    Day 2026-01-13: 00:00 valid               -> coverage 0.25
    """
    series = make_series(
        [
            "2026-01-10 00:00",
            "2026-01-10 06:00",
            "2026-01-10 12:00",
            "2026-01-10 18:00",
            "2026-01-11 00:00",
            "2026-01-11 03:00",
            "2026-01-11 06:00",
            "2026-01-11 18:00",
            "2026-01-13 00:00",
        ],
        [2.0, 4.0, 10.0, 6.0, 1.0, 3.0, 30.0, np.nan, 0.0],
        [90.0, 80.0, 60.0, 70.0, 95.0, 85.0, 10.0, 50.0, 100.0],
        qc=[0, 0, 0, 0, int(QcFlag.STEP), 0, int(QcFlag.SPIKE), 0, 0],
    )
    return DailyWeather.from_series(series, PRAGUE, SIX_HOURS_S, EXCLUDE)


def test_hand_computed_aggregates(two_days: DailyWeather) -> None:
    frame = two_days.frame
    assert list(frame.columns) == list(DAILY_COLUMNS)
    assert frame.index.name == "date"
    assert two_days.dates == [date(2026, 1, d) for d in (10, 11, 12, 13)]
    day1, day2 = frame.loc[date(2026, 1, 10)], frame.loc[date(2026, 1, 11)]
    assert (day1["temp_min"], day1["temp_mean"], day1["temp_max"]) == (2.0, 5.5, 10.0)
    assert (day1["rh_min"], day1["rh_mean"], day1["rh_max"]) == (60.0, 75.0, 90.0)
    assert (day1["n_samples"], day1["coverage"]) == (4, 1.0)
    assert (day2["temp_min"], day2["temp_mean"], day2["temp_max"]) == (1.0, 2.0, 3.0)
    # The 18:00 humidity of 50 % is dropped with its row: (95 + 85) / 2 = 90.
    assert (day2["rh_min"], day2["rh_mean"], day2["rh_max"]) == (85.0, 90.0, 95.0)
    assert (day2["temp_n_samples"], day2["temp_coverage"]) == (2, 0.5)
    assert (day2["rh_n_samples"], day2["rh_coverage"]) == (2, 0.5)
    assert (day2["n_samples"], day2["coverage"]) == (2, 0.5)


@pytest.mark.parametrize(
    ("temp_c", "rh_pct"),
    [([1.0, 30.0], [50.0, np.nan]), ([1.0, np.nan], [50.0, 80.0])],
    ids=["humidity-missing", "temperature-missing"],
)
def test_one_missing_variable_invalidates_the_whole_row(
    make_series: SeriesFactory, temp_c: list[float], rh_pct: list[float]
) -> None:
    # Owner decision 2026-10-05: the 12:00 row lacks one variable, so neither of its values
    # counts, even with an exclusion mask of 0 (no MISSING flag needed).
    series = make_series(["2026-01-10 00:00", "2026-01-10 12:00"], temp_c, rh_pct)
    for exclude_mask in (EXCLUDE, 0):
        day = DailyWeather.from_series(series, PRAGUE, SIX_HOURS_S, exclude_mask).frame.iloc[0]
        assert (day["temp_min"], day["temp_max"], day["rh_min"], day["rh_max"]) == (
            1.0,
            1.0,
            50.0,
            50.0,
        )
        for prefix in ("", "temp_", "rh_"):
            assert (day[f"{prefix}n_samples"], day[f"{prefix}coverage"]) == (1, 0.25)


def test_day_without_samples_is_present_and_empty(two_days: DailyWeather) -> None:
    day3 = two_days.frame.loc[date(2026, 1, 12)]
    assert day3["n_samples"] == 0
    assert day3["coverage"] == 0.0
    assert math.isnan(day3["temp_mean"])
    assert two_days.frame.loc[date(2026, 1, 13), "coverage"] == 0.25
    assert two_days.frame["n_samples"].dtype == np.int64


def test_complete_days_and_between(two_days: DailyWeather) -> None:
    assert two_days.complete_days(0.5).dates == [date(2026, 1, 10), date(2026, 1, 11)]
    assert two_days.complete_days(0.9).dates == [date(2026, 1, 10)]
    assert two_days.between(date(2026, 1, 11), date(2026, 1, 12)).dates == [
        date(2026, 1, 11),
        date(2026, 1, 12),
    ]
    assert len(two_days) == 4
    assert two_days.sensor_id == SensorId("77678271")
    assert two_days.timezone == PRAGUE
    assert "days=4" in repr(two_days)


def test_local_day_boundaries_not_utc(make_series: SeriesFactory) -> None:
    # 00:30 local on Jan 10 is 23:30 UTC on Jan 9, but belongs to the local day Jan 10.
    series = make_series(["2026-01-10 00:30"], [1.0], [50.0])
    daily = DailyWeather.from_series(series, PRAGUE, SIX_HOURS_S, EXCLUDE)
    assert daily.dates == [date(2026, 1, 10)]


@pytest.mark.parametrize(
    ("day", "n_hours", "expected_coverage"),
    [
        ("2026-10-25", 25, 1.0),  # 25 h day, fully covered
        ("2026-10-25", 24, 24 / 25),  # one hour missing on a 25 h day: 0.96, not 1.0
        ("2026-03-29", 23, 1.0),  # 23 h day, fully covered
        ("2026-03-29", 22, 22 / 23),
        ("2026-07-01", 23, 23 / 24),
    ],
)
def test_coverage_uses_real_day_length(
    day: str, n_hours: int, expected_coverage: float, sensor_id: SensorId
) -> None:
    start_utc = pd.Timestamp(day).tz_localize(PRAGUE).tz_convert("UTC")
    stamps = pd.date_range(start_utc, periods=n_hours, freq="h")
    series = MeasurementSeries.from_records(sensor_id, stamps, [10.0] * n_hours, [50.0] * n_hours)
    daily = DailyWeather.from_series(series, PRAGUE, ONE_HOUR_S, EXCLUDE)
    assert daily.dates == [date.fromisoformat(day)]
    assert daily.frame["coverage"].iloc[0] == pytest.approx(expected_coverage)
    assert daily.frame["n_samples"].iloc[0] == n_hours


def test_nominal_interval_coverage(sensor_id: SensorId) -> None:
    # 47 samples 1825 s apart: 47 * 1825 / 86400 = 0.992766...
    start_utc = pd.Timestamp("2026-01-15").tz_localize(PRAGUE).tz_convert("UTC")
    stamps = pd.date_range(start_utc, periods=47, freq="1825s")
    series = MeasurementSeries.from_records(sensor_id, stamps, [1.0] * 47, [80.0] * 47)
    daily = DailyWeather.from_series(series, PRAGUE, 1825.0, EXCLUDE)
    assert daily.frame["coverage"].iloc[0] == pytest.approx(47 * 1825 / 86400)


def test_empty_and_fully_excluded_series(sensor_id: SensorId, make_series: SeriesFactory) -> None:
    empty = DailyWeather.from_series(MeasurementSeries.empty(sensor_id), PRAGUE, 1825.0, EXCLUDE)
    assert len(empty) == 0
    assert list(empty.frame.columns) == list(DAILY_COLUMNS)
    excluded = make_series(["2026-01-10 00:00"], [1.0], [50.0], qc=[int(QcFlag.MANUAL_EXCLUDE)])
    daily = DailyWeather.from_series(excluded, PRAGUE, 1825.0, EXCLUDE)
    assert daily.frame["n_samples"].tolist() == [0]
    assert daily.frame["coverage"].tolist() == [0.0]


def test_invalid_arguments(sensor_id: SensorId, two_days: DailyWeather) -> None:
    with pytest.raises(ValueError, match="expected_interval_s must be positive"):
        DailyWeather.from_series(MeasurementSeries.empty(sensor_id), PRAGUE, 0.0, EXCLUDE)
    with pytest.raises(SchemaError, match="columns"):
        DailyWeather(sensor_id, two_days.frame.drop(columns="coverage"), PRAGUE)
    with pytest.raises(SchemaError, match=r"datetime\.date"):
        DailyWeather(sensor_id, two_days.frame.reset_index(drop=True), PRAGUE)
    with pytest.raises(SchemaError, match="unique and increasing"):
        DailyWeather(sensor_id, two_days.frame.iloc[::-1], PRAGUE)
    frame = two_days.frame
    for column, value, message in [
        ("coverage", 5.0, "within 0-1"),
        ("rh_coverage", -0.1, "within 0-1"),
        ("rh_n_samples", -1, "must not be negative"),
        ("coverage", 0.3, "'temp_n_samples' and 'temp_coverage' must equal"),
        ("rh_coverage", 0.3, "'rh_n_samples' and 'rh_coverage' must equal"),
        ("rh_n_samples", 3, "whole-row validity"),
    ]:
        broken = frame.copy()
        broken.loc[date(2026, 1, 10), column] = value
        with pytest.raises(SchemaError, match=message):
            DailyWeather(sensor_id, broken, PRAGUE)
    with pytest.raises(SchemaError, match="'temp_min' must be float64"):
        DailyWeather(sensor_id, frame.assign(temp_min="x"), PRAGUE)
    with pytest.raises(SchemaError, match="'n_samples' must be int64"):
        DailyWeather(sensor_id, frame.assign(n_samples=frame["n_samples"] * 1.0), PRAGUE)
    with pytest.raises(ValueError, match="Unknown IANA"):
        DailyWeather(sensor_id, two_days.frame, "Mars/Olympus")
