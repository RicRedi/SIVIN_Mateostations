"""Tests of the alignment strategies on hand-made sample sets. All data are synthetic."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.alignment.grid import TimeGrid
from sivin.alignment.strategies import (
    DEFAULT_MAX_GAP_S,
    DEFAULT_TOLERANCE_MARGIN_S,
    AlignedValues,
    AlignmentStrategy,
    LinearInterpolation,
    LinearParams,
    NearestParams,
    NearestWithinTolerance,
    SampleSet,
    StrategyParams,
    strategy_registry,
)
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

T0 = pd.Timestamp("2026-06-01T00:00:00Z")
T0_NS = T0.value
NS = 1_000_000_000
NAN = float("nan")


def at(offset_s: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(seconds=offset_s)


def samples(offsets_s: list[float], values: list[float]) -> SampleSet:
    times_ns = np.array([T0_NS + round(s * NS) for s in offsets_s], dtype=np.int64)
    return SampleSet(times_ns, np.array(values, dtype=np.float64))


def grid(last_s: float, step_s: float = 1800.0) -> TimeGrid:
    return TimeGrid(T0, at(last_s), step_s)


def test_nearest_default_tolerance_is_half_the_interval_plus_margin() -> None:
    # 1825 / 2 + 20 = 932.5 s
    assert DEFAULT_TOLERANCE_MARGIN_S == 20.0
    assert NearestWithinTolerance().tolerance_s == 932.5
    derived = NearestParams(expected_interval_s=1000.0, margin_s=0.0)
    assert NearestWithinTolerance(derived).tolerance_s == 500.0
    override = NearestParams(tolerance_s=60.0, margin_s=500.0)
    assert NearestWithinTolerance(override).tolerance_s == 60.0


def test_nearest_tolerance_boundary_is_inclusive() -> None:
    strategy = NearestWithinTolerance()

    at_limit = strategy.align(samples([932.5], [1.0]), grid(0))
    beyond = strategy.align(samples([932.500000001], [1.0]), grid(0))

    assert at_limit.valid.tolist() == [True]
    assert at_limit.grid_values.tolist() == [1.0]
    assert at_limit.offset_s is not None
    assert at_limit.offset_s.tolist() == [932.5]
    assert beyond.valid.tolist() == [False]
    assert np.isnan(beyond.grid_values).all()
    assert beyond.offset_s is not None
    assert np.isnan(beyond.offset_s).all()


def test_nearest_respects_configured_tolerance() -> None:
    strategy = NearestWithinTolerance(NearestParams(tolerance_s=60.0))

    result = strategy.align(samples([60.0, 1861.0], [1.0, 2.0]), grid(1800))

    # 60 s from the first grid point (valid), 61 s from the second (invalid).
    assert result.valid.tolist() == [True, False]
    assert result.grid_values[0] == 1.0


def test_nearest_tie_takes_the_earlier_sample() -> None:
    result = NearestWithinTolerance().align(samples([-450.0, 450.0], [1.0, 2.0]), grid(0))

    assert result.grid_values.tolist() == [1.0]
    assert result.offset_s is not None
    assert result.offset_s.tolist() == [450.0]


def test_nearest_prefers_exact_match() -> None:
    result = NearestWithinTolerance().align(samples([-10.0, 0.0, 10.0], [1.0, 2.0, 3.0]), grid(0))

    assert result.grid_values.tolist() == [2.0]


def test_nearest_half_way_sample_serves_both_neighbours() -> None:
    result = NearestWithinTolerance().align(samples([900.0], [7.0]), grid(1800))

    assert result.grid_values.tolist() == [7.0, 7.0]
    assert result.offset_s is not None
    assert result.offset_s.tolist() == [900.0, 900.0]


def test_nearest_grid_outside_samples() -> None:
    result = NearestWithinTolerance().align(samples([3600.0], [5.0]), grid(7200))

    # Grid points 0, 1800, 3600, 5400, 7200 s: only 3600 s is within 932.5 s of the sample.
    assert result.valid.tolist() == [False, False, True, False, False]


def test_nearest_without_samples_is_all_invalid() -> None:
    result = NearestWithinTolerance().align(samples([], []), grid(3600))

    assert result.valid.tolist() == [False, False, False]
    assert result.offset_s is not None
    assert np.isnan(result.offset_s).all()


def test_nearest_slip_of_1825_s_sampling_on_1800_s_grid() -> None:
    """A clock drifting 25 s per sample against the grid, with tolerance = half the grid step.

    Samples at 10 + 1825 k s (k = 0..72). For grid point m (1800 m s), sample k = m is
    10 + 25 m s away: within 900 s for m <= 35. At m = 36 (64800 s) the neighbours are
    k = 35 (63885 s, 915 s away) and k = 36 (65710 s, 910 s away): no sample within 900 s.
    From m = 37 on, sample k = m - 1 is 1815 - 25 m s away (890 s at m = 37 down to 15 s at
    m = 72), and m = 73 (131400 s) takes k = 72 (131410 s, 10 s away).
    """
    k = np.arange(73)
    data = samples((10 + 1825 * k).tolist(), k.astype(float).tolist())

    half_step = NearestWithinTolerance(NearestParams(tolerance_s=900.0))
    result = half_step.align(data, grid(73 * 1800))

    assert np.flatnonzero(~result.valid).tolist() == [36]
    expected = np.concatenate([np.arange(36), [NAN], np.arange(36, 73)])
    np.testing.assert_array_equal(result.grid_values, expected)
    assert result.offset_s is not None
    assert result.offset_s[35] == 885.0
    assert result.offset_s[37] == 890.0
    assert result.offset_s[73] == 10.0

    filled = LinearInterpolation().align(data, grid(73 * 1800))
    # Only m = 0 (0 s) is not enclosed: it lies before the first sample (10 s).
    assert np.flatnonzero(~filled.valid).tolist() == [0]
    # m = 36 lies between k = 35 (63885 s) and k = 36 (65710 s): 35 + 915 / 1825.
    assert filled.grid_values[36] == pytest.approx(35 + 915 / 1825)


def test_nearest_default_tolerance_covers_the_slip() -> None:
    """Same samples with the default tolerance 932.5 s: m = 36 takes k = 36 (910 s away).

    Sample k = 36 then serves both m = 36 and m = 37 (890 s away), and no grid point is empty.
    """
    k = np.arange(73)
    data = samples((10 + 1825 * k).tolist(), k.astype(float).tolist())

    result = NearestWithinTolerance().align(data, grid(73 * 1800))

    assert result.valid.all()
    expected = np.concatenate([np.arange(37), np.arange(36, 73)])
    np.testing.assert_array_equal(result.grid_values, expected)
    assert result.offset_s is not None
    assert result.offset_s[36] == 910.0
    assert result.offset_s[37] == 890.0


def test_linear_default_max_gap() -> None:
    assert DEFAULT_MAX_GAP_S == 2737.5
    assert LinearInterpolation().max_gap_s == 2737.5


def test_linear_interpolates_by_time_weight() -> None:
    result = LinearInterpolation().align(samples([-300.0, 1490.0], [20.0, 21.0]), grid(0))

    # 20 + (21 - 20) * (0 - (-300)) / (1490 - (-300)) = 20 + 300 / 1790
    assert result.grid_values[0] == pytest.approx(20 + 300 / 1790)
    assert result.offset_s is None


def test_linear_takes_exact_sample_as_is() -> None:
    result = LinearInterpolation().align(samples([0.0, 5000.0], [3.0, 9.0]), grid(0))

    assert result.grid_values.tolist() == [3.0]


def test_linear_exact_sample_is_valid_even_next_to_a_long_gap() -> None:
    result = LinearInterpolation().align(samples([-9000.0, 0.0, 9000.0], [1.0, 2.0, 3.0]), grid(0))

    assert result.valid.tolist() == [True]
    assert result.grid_values.tolist() == [2.0]


def test_linear_gap_longer_than_max_gap_stays_empty() -> None:
    data = samples([0.0, 3600.0], [10.0, 20.0])

    default = LinearInterpolation().align(data, grid(3600))
    wide = LinearInterpolation(LinearParams(max_gap_s=3600.0)).align(data, grid(3600))

    # 3600 s > 2737.5 s: the middle point stays empty, the end points are exact samples.
    assert default.valid.tolist() == [True, False, True]
    assert np.isnan(default.grid_values[1])
    # A gap equal to max_gap_s is still bridged: midpoint value 15.
    assert wide.grid_values.tolist() == [10.0, 15.0, 20.0]


def test_linear_never_extrapolates() -> None:
    result = LinearInterpolation().align(samples([1000.0, 2000.0], [1.0, 2.0]), grid(3600))

    # Grid 0 s is before the first sample, 3600 s after the last; 1800 s is enclosed.
    assert result.valid.tolist() == [False, True, False]
    assert result.grid_values[1] == pytest.approx(1.8)


def test_linear_without_samples_is_all_invalid() -> None:
    result = LinearInterpolation().align(samples([], []), grid(1800))

    assert result.valid.tolist() == [False, False]
    assert result.offset_s is None


def test_linear_single_sample_only_fills_its_own_grid_point() -> None:
    result = LinearInterpolation().align(samples([1800.0], [4.0]), grid(3600))

    assert result.valid.tolist() == [False, True, False]


def test_sample_set_skips_excluded_and_nan_samples() -> None:
    series = MeasurementSeries.from_records(
        SensorId("11111111"),
        [at(0), at(100), at(200), at(300)],
        temp_c=[99.0, NAN, 5.0, 6.0],
        rh_pct=[80.0, 50.0, 60.0, NAN],
        qc=[int(QcFlag.SPIKE), 0, int(QcFlag.STEP), 0],
    )
    mask = int(QcFlag.DEFAULT_EXCLUDE)

    temp = SampleSet.from_series(series, "temp_c", mask)
    rh = SampleSet.from_series(series, "rh_pct", mask)
    unmasked = SampleSet.from_series(series, "temp_c", 0)

    # SPIKE is excluded by default, STEP is informative only.
    assert temp.sample_values.tolist() == [5.0, 6.0]
    assert (temp.times_ns - T0_NS).tolist() == [200 * NS, 300 * NS]
    assert rh.sample_values.tolist() == [50.0, 60.0]
    assert unmasked.sample_values.tolist() == [99.0, 5.0, 6.0]
    assert len(temp) == 2


def test_sample_set_validation() -> None:
    with pytest.raises(ValueError, match="same length"):
        SampleSet(np.array([1, 2], dtype=np.int64), np.array([1.0]))
    with pytest.raises(ValueError, match="strictly increasing"):
        SampleSet(np.array([2, 2], dtype=np.int64), np.array([1.0, 2.0]))
    with pytest.raises(ValueError, match="NaN"):
        SampleSet(np.array([1, 2], dtype=np.int64), np.array([1.0, NAN]))


def test_aligned_values_validation() -> None:
    with pytest.raises(ValueError, match="equal length"):
        AlignedValues(np.zeros(2), np.zeros(3, dtype=bool))
    with pytest.raises(ValueError, match="equal length"):
        AlignedValues(np.zeros(2), np.zeros(2, dtype=bool), np.zeros(1))


def test_strategy_rejects_parameters_of_another_strategy() -> None:
    with pytest.raises(TypeError, match="expects NearestParams"):
        NearestWithinTolerance(LinearParams())  # type: ignore[arg-type]


def test_strategy_from_raw_parameters() -> None:
    strategy = LinearInterpolation.from_params({"max_gap_s": 4000})

    assert strategy.max_gap_s == 4000.0
    assert "max_gap_s=4000.0" in repr(strategy)
    assert NearestWithinTolerance.from_params().params == NearestParams()


@pytest.mark.parametrize(
    "raw", [{"max_gap_s": 0}, {"max_gap_s": float("inf")}, {"tolerance_s": 10}]
)
def test_invalid_raw_parameters_fail(raw: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        LinearInterpolation.from_params(raw)


def test_params_model_must_match_the_generic_argument() -> None:
    with pytest.raises(TypeError, match=r"declared as AlignmentStrategy\[NearestParams\]"):

        class Mismatched(AlignmentStrategy[NearestParams]):
            strategy_id: ClassVar[str] = "mismatched"
            params_model: ClassVar[type[StrategyParams]] = LinearParams

            def align(self, samples: SampleSet, grid: TimeGrid) -> AlignedValues:
                raise NotImplementedError


def test_strategies_are_registered() -> None:
    assert strategy_registry.ids() == ("linear_interpolation", "nearest_within_tolerance")
    assert strategy_registry.get("nearest_within_tolerance") is NearestWithinTolerance
    assert NearestWithinTolerance.provides_offsets
    assert not LinearInterpolation.provides_offsets
