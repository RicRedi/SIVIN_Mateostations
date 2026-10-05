"""Tests of the individual quality checks. All data are SYNTHETIC (see synthetic.py)."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError
from tests.quality.synthetic import INTERVAL_S, Trace, custom_trace, flat_trace

from sivin.core.flags import QcFlag
from sivin.quality.checks import (
    MissingRule,
    MissingValueCheck,
    MissingValueSettings,
    PersistenceCheck,
    PersistenceSettings,
    RangeCheck,
    RangeSettings,
    SamplingCheck,
    SamplingSettings,
    SpikeCheck,
    SpikeSettings,
    StepCheck,
    StepSettings,
    classify_intervals,
)
from sivin.quality.events import EventKind, Severity

# Default spike limit per nominal interval: 8 °C/h * 1825 s / 3600 s/h = 4.0556 °C.


def _flagged(flags: np.ndarray, flag: QcFlag) -> list[int]:
    return [int(i) for i in np.flatnonzero(flags & int(flag))]


class TestMissingValueCheck:
    def test_rule_all_flags_rows_without_any_value(self) -> None:
        nan = float("nan")
        trace = custom_trace([0, 1825, 3650], [1.0, nan, nan], [50.0, 50.0, nan])
        check = MissingValueCheck(MissingValueSettings(rule=MissingRule.ALL))
        outcome = check.check(trace.series())
        assert _flagged(outcome.flags, QcFlag.MISSING) == [2]
        assert outcome.events == ()

    def test_default_rule_any_flags_rows_with_one_missing_value(self) -> None:
        # Owner decision 2026-10-05: one missing variable invalidates the whole row.
        nan = float("nan")
        trace = custom_trace([0, 1825, 3650, 5475], [1.0, nan, nan, 2.0], [50.0, 50.0, nan, nan])
        assert MissingValueSettings().rule is MissingRule.ANY
        outcome = MissingValueCheck().check(trace.series())
        assert _flagged(outcome.flags, QcFlag.MISSING) == [1, 2, 3]
        assert outcome.events == ()

    def test_complete_series_has_no_flag(self) -> None:
        outcome = MissingValueCheck().check(flat_trace([1.0, 2.0]).series())
        assert outcome.count(QcFlag.MISSING) == 0


class TestRangeCheck:
    def test_flags_values_outside_climatological_limits(self) -> None:
        trace = custom_trace(
            [0, 1825, 3650, 5475, 7300],
            [-35.0, -30.0, 42.0, 42.5, 20.0],
            [50.0, 50.0, 50.0, 50.0, 100.5],
        )
        flags = RangeCheck().check(trace.series()).flags
        # -35 < -30, 42.5 > 42 and RH 100.5 > 100; the limits themselves are valid.
        assert _flagged(flags, QcFlag.OUT_OF_RANGE) == [0, 3, 4]

    def test_disabled_climate_limit_falls_back_to_physical_limit(self) -> None:
        trace = flat_trace([-35.0, -55.0, 59.0, 61.0])
        settings = RangeSettings(temp_climate_min_c=None, temp_climate_max_c=None)
        flags = RangeCheck(settings).check(trace.series()).flags
        assert _flagged(flags, QcFlag.OUT_OF_RANGE) == [1, 3]
        assert (settings.temp_min_c, settings.temp_max_c) == (-50.0, 60.0)

    def test_nan_is_not_out_of_range(self) -> None:
        trace = custom_trace([0, 1825], [float("nan"), 10.0], [float("nan"), 50.0])
        assert RangeCheck().check(trace.series()).count(QcFlag.OUT_OF_RANGE) == 0

    def test_settings_reject_empty_ranges(self) -> None:
        with pytest.raises(ValidationError, match="no valid range"):
            RangeSettings(temp_climate_min_c=10.0, temp_climate_max_c=5.0)
        with pytest.raises(ValidationError, match="rh_min_pct"):
            RangeSettings(rh_min_pct=60.0, rh_max_pct=50.0)
        with pytest.raises(ValidationError, match="extra"):
            RangeSettings.model_validate({"temp_max": 3})


class TestSpikeCheck:
    def test_isolated_departure_that_returns_is_a_spike(self) -> None:
        # +5 and -5 °C within 1825 s each: both exceed 4.06 °C with opposite signs.
        trace = flat_trace([10.0, 10.0, 15.0, 10.0, 10.0])
        assert _flagged(SpikeCheck().check(trace.series()).flags, QcFlag.SPIKE) == [2]

    def test_small_departure_is_not_a_spike(self) -> None:
        trace = flat_trace([10.0, 10.0, 14.0, 10.0, 10.0])  # 4.0 < 4.06 °C
        assert SpikeCheck().check(trace.series()).count(QcFlag.SPIKE) == 0

    def test_persistent_jump_is_not_a_spike(self) -> None:
        trace = flat_trace([10.0, 10.0, 15.0, 15.0, 15.0])
        assert SpikeCheck().check(trace.series()).count(QcFlag.SPIKE) == 0

    def test_threshold_scales_with_the_actual_interval(self) -> None:
        # Return after 5400 s: limit 8 * 5400 / 3600 = 12 °C > 6 °C, so not a spike.
        trace = custom_trace([0, 1825, 3650, 9050, 10875], [10.0, 10.0, 16.0, 10.0, 10.0])
        assert SpikeCheck().check(trace.series()).count(QcFlag.SPIKE) == 0
        # Same values on the nominal grid: 6 °C > 4.06 °C on both sides.
        regular = flat_trace([10.0, 10.0, 16.0, 10.0, 10.0])
        assert SpikeCheck().check(regular.series()).count(QcFlag.SPIKE) == 1

    def test_short_intervals_use_the_minimum_interval(self) -> None:
        # 600 s intervals are scaled as 1825 s: 3 °C < 4.06 °C, no spike ...
        trace = flat_trace([10.0, 10.0, 13.0, 10.0, 10.0], interval_s=600.0)
        assert SpikeCheck().check(trace.series()).count(QcFlag.SPIKE) == 0
        # ... unless the minimum interval is lowered: limit 8 * 600 / 3600 = 1.33 °C.
        check = SpikeCheck(SpikeSettings(min_interval_s=600.0))
        assert check.check(trace.series()).count(QcFlag.SPIKE) == 1

    def test_neighbour_beyond_max_interval_cannot_confirm(self) -> None:
        trace = custom_trace([0, 1825, 3650, 3650 + 6000], [10.0, 10.0, 30.0, 10.0])
        assert SpikeCheck().check(trace.series()).count(QcFlag.SPIKE) == 0

    def test_humidity_spike_and_missing_neighbours(self) -> None:
        nan = float("nan")
        # RH +45 % for one sample. The NaN row is skipped, so the next neighbour is 3650 s
        # away: limits 40 %/h * 1825 s = 20.3 % before and 40 %/h * 3650 s = 40.6 % after.
        trace = custom_trace(
            [0, 1825, 3650, 5475, 7300],
            [10.0, 10.0, 10.0, nan, 10.0],
            [50.0, 50.0, 95.0, nan, 50.0],
        )
        flags = SpikeCheck().check(trace.series()).flags
        assert _flagged(flags, QcFlag.SPIKE) == [2]

    def test_too_short_series(self) -> None:
        assert SpikeCheck().check(flat_trace([1.0, 9.0]).series()).count(QcFlag.SPIKE) == 0


class TestStepCheck:
    def test_persistent_level_shift_is_a_step(self) -> None:
        trace = flat_trace([10.0] * 8 + [16.0] * 8)
        outcome = StepCheck().check(trace.series())
        assert _flagged(outcome.flags, QcFlag.STEP) == [8]
        assert [event.kind for event in outcome.events] == [EventKind.STEP]
        assert outcome.events[0].t_utc == trace.timestamp(8)
        assert "+6.0 °C" in outcome.events[0].detail

    def test_spike_is_not_a_step(self) -> None:
        trace = flat_trace([10.0] * 8 + [16.0] + [10.0] * 7)
        assert StepCheck().check(trace.series()).count(QcFlag.STEP) == 0

    def test_fast_front_over_two_intervals_is_not_a_step(self) -> None:
        # -10 °C within about 1 h: two jumps of -5 °C; each neighbour is as large as the
        # jump (more than 0.4 x 5 °C), so the change is not confined to one interval.
        trace = flat_trace([18.0] * 8 + [13.0, 8.0] + [8.0] * 8)
        assert StepCheck().check(trace.series()).count(QcFlag.STEP) == 0
        lenient = StepCheck(StepSettings(max_adjacent_fraction=1.0))
        assert lenient.check(trace.series()).count(QcFlag.STEP) == 2

    def test_gradual_change_is_not_a_step(self) -> None:
        # A cold front: -8 °C over 4 intervals (2 °C each) is below the 5 °C jump threshold.
        trace = flat_trace([18.0] * 8 + [16.0, 14.0, 12.0, 10.0] + [10.0] * 8)
        assert StepCheck().check(trace.series()).count(QcFlag.STEP) == 0

    def test_jump_across_a_long_gap_is_not_examined(self) -> None:
        offsets = [i * INTERVAL_S for i in range(8)] + [
            7 * INTERVAL_S + 10_800 + i * INTERVAL_S for i in range(8)
        ]
        trace = custom_trace(offsets, [10.0] * 8 + [16.0] * 8)
        assert StepCheck().check(trace.series()).count(QcFlag.STEP) == 0

    def test_windows_need_enough_samples(self) -> None:
        trace = flat_trace([10.0, 10.0, 16.0, 16.0, 16.0])
        assert StepCheck().check(trace.series()).count(QcFlag.STEP) == 0
        relaxed = StepCheck(StepSettings(min_window_samples=2))
        assert relaxed.check(trace.series()).count(QcFlag.STEP) == 1

    def test_humidity_step(self) -> None:
        trace = custom_trace(
            [i * INTERVAL_S for i in range(12)], [10.0] * 12, [40.0] * 6 + [80.0] * 6
        )
        outcome = StepCheck().check(trace.series())
        assert _flagged(outcome.flags, QcFlag.STEP) == [6]
        assert "rh_pct level step +40.0 %" in outcome.events[0].detail


def _temps(values_c: list[float]) -> Trace:
    """Regular trace whose humidity alternates by 1 % (> tolerance), so only T can stick."""
    rh = [60.0 + (i % 2) for i in range(len(values_c))]
    return custom_trace([i * INTERVAL_S for i in range(len(values_c))], values_c, rh)


class TestPersistenceCheck:
    def test_long_unchanged_run_is_stuck(self) -> None:
        # 25 samples span 24 * 1825 s = 43 800 s >= 12 h = 43 200 s.
        trace = _temps([12.3] * 25 + [12.5])
        flags = PersistenceCheck().check(trace.series()).flags
        assert _flagged(flags, QcFlag.STUCK) == list(range(25))

    def test_short_run_is_not_stuck(self) -> None:
        # 24 samples span 23 * 1825 s = 41 975 s < 43 200 s.
        trace = _temps([12.3] * 24 + [12.5])
        assert PersistenceCheck().check(trace.series()).count(QcFlag.STUCK) == 0

    def test_changing_values_are_not_stuck(self) -> None:
        trace = _temps([12.3, 12.4] * 20)  # range 0.1 > tolerance 0.05 °C
        assert PersistenceCheck().check(trace.series()).count(QcFlag.STUCK) == 0

    def test_irregular_sampling_uses_real_durations(self) -> None:
        # Only 4 samples, but they span 13 h.
        trace = custom_trace(
            [0, 3600, 7200, 46_800, 48_600], [5.0, 5.0, 5.0, 5.0, 6.0], [60.0, 61.0] * 2 + [60.0]
        )
        flags = PersistenceCheck().check(trace.series()).flags
        assert _flagged(flags, QcFlag.STUCK) == [0, 1, 2, 3]

    def test_missing_values_are_skipped_and_not_flagged(self) -> None:
        values = [12.3] * 12 + [float("nan")] + [12.3] * 13
        trace = _temps(values)
        flags = PersistenceCheck().check(trace.series()).flags
        assert _flagged(flags, QcFlag.STUCK) == [i for i in range(26) if i != 12]

    def test_saturated_air_exempts_both_variables(self) -> None:
        offsets = [i * INTERVAL_S for i in range(30)]  # 29 * 1825 s = 14.7 h >= 12 h
        # Fog: temperature and humidity constant, humidity saturated.
        fog = custom_trace(offsets, [3.0] * 30, [99.0] * 30)
        assert PersistenceCheck().check(fog.series()).count(QcFlag.STUCK) == 0
        # Half of the samples saturated (share 0.5) still exempts the run.
        half = custom_trace(offsets, [3.0] * 30, [99.0, 96.0] * 15)
        assert PersistenceCheck().check(half.series()).count(QcFlag.STUCK) == 0
        # Not saturated: both variables stuck.
        stuck = custom_trace(offsets, [3.0] * 30, [55.0] * 30)
        assert PersistenceCheck().check(stuck.series()).count(QcFlag.STUCK) == 30
        no_exemption = PersistenceCheck(PersistenceSettings(rh_saturation_pct=None))
        assert no_exemption.check(fog.series()).count(QcFlag.STUCK) == 30

    def test_constant_humidity_alone_is_stuck(self) -> None:
        offsets = [i * INTERVAL_S for i in range(30)]
        temps = [10.0 + 0.5 * (i % 2) for i in range(30)]
        stuck = custom_trace(offsets, temps, [55.0] * 30)
        assert PersistenceCheck().check(stuck.series()).count(QcFlag.STUCK) == 30


class TestSamplingCheck:
    # Intervals: 1825 regular, 900 irregular, 1825 regular, 3650 = 2 * 1825 (one missed
    # sample, regular), 9000 > 3 * 1825 = 5475 (gap), 1900 regular (within ±456 s).
    OFFSETS = (0.0, 1825.0, 2725.0, 4550.0, 8200.0, 17_200.0, 19_100.0)

    def test_classify_intervals(self) -> None:
        classes = classify_intervals(np.array(self.OFFSETS), SamplingSettings())
        assert classes.irregular.tolist() == [False, False, True, False, False, False, False]
        assert classes.gap.tolist() == [False, False, False, False, False, True, False]
        assert not classes.non_positive.any()

    def test_classify_non_positive_intervals(self) -> None:
        classes = classify_intervals(np.array([0.0, 1825.0, 1825.0, 1000.0]), SamplingSettings())
        assert classes.non_positive.tolist() == [False, False, True, True]
        assert not classes.irregular.any()

    def test_check_flags_irregular_samples_and_reports_gaps(self) -> None:
        trace = custom_trace(self.OFFSETS, [10.0] * len(self.OFFSETS))
        outcome = SamplingCheck().check(trace.series())
        assert _flagged(outcome.flags, QcFlag.TIMESTAMP_SUSPECT) == [2]
        kinds = [event.kind for event in outcome.events]
        assert kinds == [EventKind.IRREGULAR_SAMPLING, EventKind.GAP]
        gap = outcome.events[1]
        assert (gap.t_utc, gap.end_utc) == (trace.timestamp(4), trace.timestamp(5))
        assert gap.detail.startswith("no sample for 2.5 h")
        assert outcome.events[0].severity is Severity.WARNING

    def test_regular_jittered_series_has_no_finding(self) -> None:
        trace = custom_trace([0.0, 1840.0, 3640.0, 5480.0], [1.0, 2.0, 3.0, 4.0])
        outcome = SamplingCheck().check(trace.series())
        assert outcome.count(QcFlag.TIMESTAMP_SUSPECT) == 0
        assert outcome.events == ()
