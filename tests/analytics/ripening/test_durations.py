"""SampleDurations: time represented by irregular samples, split at local midnight."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from sivin.analytics.ripening import SampleDurationParams, SampleDurations, masked_values
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries

from .conftest import PRAGUE, local_stamps

DAY = date(2026, 7, 1)


def series_at(
    sensor_id: SensorId, day: date, hours: list[float], temps: list[float]
) -> MeasurementSeries:
    return MeasurementSeries.from_records(
        sensor_id, local_stamps(day, hours), temps, [60.0] * len(temps)
    )


@pytest.fixture
def durations() -> SampleDurations:
    return SampleDurations(SampleDurationParams(), PRAGUE)


def test_durations_follow_the_next_sample_and_a_gap_counts_the_nominal_interval(
    sensor_id: SensorId, durations: SampleDurations
) -> None:
    # Samples at 0 h, 0.5 h, 1 h, 2.25 h, 4.25 h. Steps: 1800 s, 1800 s, 4500 s (one missed
    # sample plus drift, <= 4562.5 s cap -> counted in full), 7200 s (> cap: a gap, the sample
    # counts only the nominal 1825 s); the last sample has no successor -> 1825 s.
    series = series_at(sensor_id, DAY, [0, 0.5, 1, 2.25, 4.25], [1.0, 2.0, 3.0, 4.0, 5.0])
    assert durations.durations_s(series).tolist() == [1800.0, 1800.0, 4500.0, 1825.0, 1825.0]
    assert durations.params == SampleDurationParams()


def test_sample_before_a_gap_counts_only_the_nominal_interval(
    sensor_id: SensorId, durations: SampleDurations
) -> None:
    # -1 °C at 02:00, then nothing until 08:00: 1825 s of frost, not 6 h and not the cap.
    series = series_at(sensor_id, DAY, [2, 8], [-1.0, 5.0])
    hours = durations.hours_by_day(series, series.frame[Column.TEMP].to_numpy(), lambda t: t <= 0)
    assert hours[DAY] == pytest.approx(1825 / 3600)


def test_duration_weighted_means(sensor_id: SensorId, durations: SampleDurations) -> None:
    # 00:00 10 °C (1800 s), 00:30 10 °C (1800 s), 01:00 40 °C (step 4500 s, counted),
    # 02:15 40 °C (last, 1825 s): weighted mean (10*3600 + 40*6325) / 9925 = 289000 / 9925
    # = 29.12 °C, while the arithmetic sample mean would be 25.0 °C.
    series = series_at(sensor_id, DAY, [0, 0.5, 1, 2.25], [10.0, 10.0, 40.0, 40.0])
    values = series.frame[Column.TEMP].to_numpy()
    means = durations.daily_means(series, values, [DAY, date(2026, 7, 2)])
    assert means[DAY] == pytest.approx(289000 / 9925)
    assert np.isnan(means[date(2026, 7, 2)])
    first_two = np.array([True, True, False, False])
    assert durations.weighted_mean(series, values, first_two) == pytest.approx(10.0)
    assert np.isnan(durations.weighted_mean(series, values, np.zeros(4, dtype=bool)))


def test_empty_series(sensor_id: SensorId, durations: SampleDurations) -> None:
    empty = MeasurementSeries.empty(sensor_id)
    assert durations.durations_s(empty).size == 0
    assert durations.pieces(empty, np.empty(0)).empty
    assert durations.hours_by_day(empty, np.empty(0), np.isfinite).empty


def test_all_values_missing_gives_no_pieces(
    sensor_id: SensorId, durations: SampleDurations
) -> None:
    series = series_at(sensor_id, DAY, [0, 1], [1.0, 2.0])
    assert durations.pieces(series, np.array([np.nan, np.nan])).empty


def test_values_must_match_rows(sensor_id: SensorId, durations: SampleDurations) -> None:
    series = series_at(sensor_id, DAY, [0, 1], [1.0, 2.0])
    with pytest.raises(ValueError, match="Expected 2 values"):
        durations.pieces(series, np.array([1.0]))


def test_interval_crossing_midnight_is_split(
    sensor_id: SensorId, durations: SampleDurations
) -> None:
    # 23:30 (-1 °C) .. next sample 00:30 the next day: 1800 s on Jul 1 and 1800 s on Jul 2.
    series = series_at(sensor_id, DAY, [23.5, 24.5], [-1.0, 5.0])
    hours = durations.hours_by_day(series, series.frame[Column.TEMP].to_numpy(), lambda t: t <= 0)
    assert hours.to_dict() == {date(2026, 7, 1): 0.5, date(2026, 7, 2): 0.5}


def test_excluded_sample_leaves_its_own_interval_uncounted(
    sensor_id: SensorId, durations: SampleDurations
) -> None:
    # Three cold hourly samples; the middle one is a SPIKE (excluded): 2 h remain, not 3 h,
    # and the first sample is not stretched over the excluded one.
    stamps = local_stamps(DAY, [0, 1, 2, 3])
    series = MeasurementSeries.from_records(
        sensor_id, stamps, [-1.0, -1.0, -1.0, 5.0], [60.0] * 4, qc=[0, int(QcFlag.SPIKE), 0, 0]
    )
    temp_c = masked_values(series, Column.TEMP, int(QcFlag.DEFAULT_EXCLUDE))
    assert np.isnan(temp_c[1])
    hours = durations.hours_by_day(series, temp_c, lambda t: t <= 0)
    assert hours[DAY] == pytest.approx(2.0)


@pytest.mark.parametrize("missing", [Column.TEMP, Column.RH])
def test_unflagged_half_row_is_not_a_valid_sample(
    sensor_id: SensorId, durations: SampleDurations, missing: Column
) -> None:
    # Hour 1 misses one variable and carries no MISSING flag (qc = 0, as read from the
    # store). Whole-row rule checked on the values: both masked columns are NaN there, so the
    # frost hours count 2 h, not 3 h, whichever variable is missing.
    temps = [-1.0, -1.0, -1.0, 5.0]
    rh = [60.0] * 4
    (temps if missing is Column.TEMP else rh)[1] = float("nan")
    series = MeasurementSeries.from_records(
        sensor_id, local_stamps(DAY, [0, 1, 2, 3]), temps, rh, qc=[0] * 4
    )
    mask = int(QcFlag.DEFAULT_EXCLUDE)
    temp_c = masked_values(series, Column.TEMP, mask)
    rh_pct = masked_values(series, Column.RH, mask)
    assert np.isnan(temp_c[1])
    assert np.isnan(rh_pct[1])
    hours = durations.hours_by_day(series, temp_c, lambda t: t <= 0)
    assert hours[DAY] == pytest.approx(2.0)
    assert durations.weighted_mean(series, rh_pct, np.ones(4, dtype=bool)) == 60.0


def test_irregular_sampling_gives_the_same_hours(
    sensor_id: SensorId, durations: SampleDurations
) -> None:
    # Cold block 02:00-06:00 (4 h) sampled regularly (every 30 min) and irregularly; every
    # irregular step is shorter than the 4562.5 s cap, so both must give exactly 4 h.
    regular_hours = [h / 2 for h in range(0, 17)]  # 00:00 .. 08:00
    regular = series_at(
        sensor_id, DAY, regular_hours, [-2.0 if 2 <= h < 6 else 4.0 for h in regular_hours]
    )
    irregular_hours = [0, 0.7, 1.3, 2, 2.1, 2.9, 3.5, 4.4, 5.2, 5.95, 6, 6.6, 7.2, 8]
    irregular = series_at(
        sensor_id, DAY, irregular_hours, [-2.0 if 2 <= h < 6 else 4.0 for h in irregular_hours]
    )
    results = [
        durations.hours_by_day(s, s.frame[Column.TEMP].to_numpy(), lambda t: t <= 0)[DAY]
        for s in (regular, irregular)
    ]
    assert results == pytest.approx([4.0, 4.0])
    # Rows below zero differ (8 vs 7): counting rows, as the legacy script did, is wrong.
    assert (regular.frame[Column.TEMP] <= 0).sum() == 8
    assert (irregular.frame[Column.TEMP] <= 0).sum() == 7


def test_fall_back_day_has_25_observed_hours(
    sensor_id: SensorId, durations: SampleDurations
) -> None:
    # 2026-10-25 (CEST -> CET) lasts 25 h: hourly UTC samples from local midnight to the next.
    start = pd.Timestamp("2026-10-24 22:00", tz="UTC")  # 00:00 CEST on Oct 25
    stamps = pd.date_range(start, periods=26, freq="h")  # up to 00:00 CET on Oct 26
    series = MeasurementSeries.from_records(sensor_id, stamps, [5.0] * 26, [60.0] * 26)
    hours = durations.hours_by_day(series, series.frame[Column.TEMP].to_numpy(), np.isfinite)
    assert hours[date(2026, 10, 25)] == pytest.approx(25.0)


def test_requested_days_without_data_get_zero(
    sensor_id: SensorId, durations: SampleDurations
) -> None:
    series = series_at(sensor_id, DAY, [0, 1], [1.0, 2.0])
    other = date(2026, 7, 5)
    hours = durations.hours_by_day(
        series, series.frame[Column.TEMP].to_numpy(), np.isfinite, [other, DAY]
    )
    assert list(hours.index) == [other, DAY]
    assert hours.tolist() == pytest.approx([0.0, 1.0 + 1825 / 3600])
