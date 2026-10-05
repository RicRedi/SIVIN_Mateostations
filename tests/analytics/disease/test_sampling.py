"""Tests of sample durations and run detection (synthetic timestamps)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.analytics.disease import (
    RunFinder,
    SampleDurations,
    SampleRun,
    SampleTiming,
    SamplingParams,
    SeasonWindow,
)
from sivin.core.season import MonthDay, Season


def utc_seconds(*offsets_s: float) -> pd.Series:
    """Timestamps at the given offsets in seconds from 2026-06-01 00:00 UTC."""
    start = pd.Timestamp("2026-06-01", tz="UTC")
    return pd.Series([start + pd.Timedelta(seconds=s) for s in offsets_s])


def hourly_timing(n: int) -> SampleTiming:
    """n samples of 1 h each, no gaps."""
    followed = np.ones(n, dtype=bool)
    followed[-1] = False
    return SampleTiming(np.full(n, 3600.0), followed)


def test_durations_follow_the_actual_steps_and_stop_at_gaps() -> None:
    durations = SampleDurations(nominal_interval_s=1825.0, max_duration_s=4562.5)
    timing = durations.measure(utc_seconds(0, 1800, 3650, 9000, 10800))
    # steps 1800, 1850, 5350 (> 4562.5: gap -> nominal 1825), 1800; last sample: nominal 1825.
    np.testing.assert_array_equal(timing.durations_s, [1800.0, 1850.0, 1825.0, 1800.0, 1825.0])
    np.testing.assert_array_equal(timing.followed, [True, True, False, True, False])
    assert len(timing) == 5


def test_durations_of_regular_nominal_sampling() -> None:
    timing = SamplingParams().durations().measure(utc_seconds(*(n * 1830.0 for n in range(12))))
    # 12 samples, 1830 s each (the last one counts the nominal 1830 s) -> 21960 s = 6.1 h,
    # the threshold of 6 h is reached.
    assert timing.durations_s.sum() == 12 * 1830.0
    assert timing.durations_s.sum() / 3600 == pytest.approx(6.1)


def test_one_missing_sample_is_bridged_two_are_a_gap() -> None:
    timing = SamplingParams().durations().measure(utc_seconds(0, 3660, 3660 + 5490))
    # Default cap 2.5 x 1830 = 4575 s: 3660 s bridged, 5490 s is a gap (nominal 1830 s).
    np.testing.assert_array_equal(timing.durations_s, [3660.0, 1830.0, 1830.0])
    np.testing.assert_array_equal(timing.followed, [True, False, False])


def test_empty_series_has_empty_timing() -> None:
    timing = SamplingParams().durations().measure(pd.Series([], dtype="datetime64[ns, UTC]"))
    assert len(timing) == 0
    assert timing.followed.dtype == np.bool_


def test_invalid_sampling_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="nominal_interval_s"):
        SampleDurations(nominal_interval_s=1825.0, max_duration_s=1000.0)
    with pytest.raises(ValueError, match="nominal_interval_s"):
        SampleDurations(nominal_interval_s=0.0, max_duration_s=1000.0)
    with pytest.raises(ValidationError, match="must not be shorter"):
        SamplingParams(nominal_interval_s=1825.0, max_sample_duration_s=1000.0)


def test_subset_selects_durations_and_gap_flags() -> None:
    timing = SampleTiming(np.array([1.0, 2.0, 3.0]), np.array([True, True, False]))
    part = timing.subset(np.array([1, 2], dtype=np.intp))
    np.testing.assert_array_equal(part.durations_s, [2.0, 3.0])
    np.testing.assert_array_equal(part.followed, [True, False])


def test_runs_without_interruptions() -> None:
    condition = np.array([True, True, False, True, True])
    runs = RunFinder().find(hourly_timing(5), condition, np.ones(5, dtype=bool))
    assert runs == [SampleRun(0, 1, 7200.0, 0.0), SampleRun(3, 4, 7200.0, 0.0)]
    assert runs[0].duration_h == 2.0


def test_short_interruption_is_bridged_and_counted() -> None:
    condition = np.array([True, True, False, True, True])
    runs = RunFinder(max_interruption_s=3600.0).find(
        hourly_timing(5), condition, np.ones(5, dtype=bool)
    )
    # 2 h + 1 h bridged dry hour + 2 h = 5 h.
    assert runs == [SampleRun(0, 4, 5 * 3600.0, 3600.0)]


def test_long_interruption_splits_and_trailing_interruption_is_dropped() -> None:
    condition = np.array([True, False, False, True, False])
    runs = RunFinder(max_interruption_s=3600.0).find(
        hourly_timing(5), condition, np.ones(5, dtype=bool)
    )
    # 2 h dry > 1 h -> two runs; the dry hour after the last wet sample is not part of it.
    assert runs == [SampleRun(0, 0, 3600.0, 0.0), SampleRun(3, 3, 3600.0, 0.0)]


def test_invalid_samples_and_gaps_always_end_a_run() -> None:
    condition = np.array([True, True, True, True, True])
    valid = np.array([True, False, True, True, True])
    timing = hourly_timing(5)
    gapped = SampleTiming(timing.durations_s, np.array([True, True, False, True, False]))
    finder = RunFinder(max_interruption_s=10 * 3600.0)
    assert finder.find(timing, condition, valid) == [
        SampleRun(0, 0, 3600.0, 0.0),
        SampleRun(2, 4, 3 * 3600.0, 0.0),
    ]
    assert finder.find(gapped, condition, np.ones(5, dtype=bool)) == [
        SampleRun(0, 2, 3 * 3600.0, 0.0),
        SampleRun(3, 4, 2 * 3600.0, 0.0),
    ]


def test_run_finder_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="negative"):
        RunFinder(max_interruption_s=-1.0)
    with pytest.raises(ValueError, match="same length"):
        RunFinder().find(hourly_timing(2), np.ones(3, dtype=bool), np.ones(2, dtype=bool))


def test_season_window() -> None:
    assert SeasonWindow().to_season() == Season.vegetation()
    window = SeasonWindow(start_month=6, start_day=1, end_month=6, end_day=30)
    assert window.to_season() == Season(MonthDay(6, 1), MonthDay(6, 30))
    with pytest.raises(ValidationError, match="Invalid month-day"):
        SeasonWindow(start_month=2, start_day=30)
    with pytest.raises(ValidationError, match="crosses the new year"):
        SeasonWindow(start_month=11, start_day=1, end_month=3, end_day=31)
