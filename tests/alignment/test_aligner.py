"""Tests of SensorAligner and AlignedPanel. All series are synthetic.

The main example has three sensors whose clocks start at different offsets and drift
differently against a 30 min grid (0 .. 7200 s after 2026-06-01T00:00Z):

* ``11111111`` (A): samples at 0, 1825, 3650, 5475, 7300 s (1825 s period, +25 s/step drift),
  temperatures 10, 11, 12, 13, 14 °C;
* ``22222222`` (B): samples at -300, 1490, 3280, 5070, 6860, 8650 s (1790 s period,
  -10 s/step drift), temperatures 20 .. 25 °C;
* ``33333333`` (C): samples at 880, 2700, 4520, 6340, 8160 s (1820 s period, +20 s/step),
  temperatures 30 .. 34 °C.

Humidity is temperature + 50 in every sample.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from sivin.alignment import (
    AlignmentConfig,
    GridPolicy,
    LinearInterpolation,
    NearestWithinTolerance,
    OverlapSpan,
    SensorAligner,
    TimeGrid,
)
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

SeriesAt = Callable[..., MeasurementSeries]
T0 = pd.Timestamp("2026-06-01T00:00:00Z")
NAN = float("nan")
A, B, C = "11111111", "22222222", "33333333"


def at(offset_s: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(seconds=offset_s)


@pytest.fixture
def drifting(series_at: SeriesAt) -> list[MeasurementSeries]:
    """The three synthetic drifting sensors described in the module docstring."""
    return [
        series_at(C, [880, 2700, 4520, 6340, 8160], [30, 31, 32, 33, 34]),
        series_at(A, [0, 1825, 3650, 5475, 7300], [10, 11, 12, 13, 14]),
        series_at(B, [-300, 1490, 3280, 5070, 6860, 8650], [20, 21, 22, 23, 24, 25]),
    ]


@pytest.fixture
def grid() -> TimeGrid:
    return TimeGrid(T0, at(7200))


def test_three_drifting_sensors_nearest(drifting: list[MeasurementSeries], grid: TimeGrid) -> None:
    panel = SensorAligner(NearestWithinTolerance()).align(drifting, grid)

    # Nearest sample within 900 s of each grid point; C at 1800 s and 3600 s: 2700 s is exactly
    # 900 s from both (inclusive), its other neighbours are 920 s away.
    expected = pd.DataFrame(
        {A: [10.0, 11, 12, 13, 14], B: [20.0, 21, 22, 23, 24], C: [30.0, 31, 31, 32, 33]},
        index=grid.times,
    )
    temp = panel.variable("temp_c")
    pd.testing.assert_frame_equal(temp, expected, check_names=False, check_column_type=False)
    assert temp.index.name == "timestamp_utc"
    assert temp.columns.name == "sensor_id"
    np.testing.assert_array_equal(panel.variable("rh_pct").to_numpy(), expected.to_numpy() + 50)
    offsets = panel.offsets_s("temp_c")
    assert offsets is not None
    np.testing.assert_array_equal(
        offsets.to_numpy(),
        [[0, 300, 880], [25, 310, 900], [50, 320, 900], [75, 330, 880], [100, 340, 860]],
    )
    assert panel.validity("temp_c").to_numpy().all()


def test_three_drifting_sensors_linear(drifting: list[MeasurementSeries], grid: TimeGrid) -> None:
    panel = SensorAligner(LinearInterpolation()).align(drifting, grid)

    # v = v_l + (v_r - v_l) (g - t_l) / (t_r - t_l); A has an exact sample at 0 s; C has no
    # sample before 0 s, so it is not extrapolated there.
    expected = np.array(
        [
            [10, 20 + 300 / 1790, NAN],
            [10 + 1800 / 1825, 21 + 310 / 1790, 30 + 920 / 1820],
            [11 + 1775 / 1825, 22 + 320 / 1790, 31 + 900 / 1820],
            [12 + 1750 / 1825, 23 + 330 / 1790, 32 + 880 / 1820],
            [13 + 1725 / 1825, 24 + 340 / 1790, 33 + 860 / 1820],
        ]
    )
    np.testing.assert_allclose(panel.variable("temp_c").to_numpy(), expected)
    np.testing.assert_allclose(panel.variable("rh_pct").to_numpy(), expected + 50)
    assert panel.validity("temp_c")[C].tolist() == [False, True, True, True, True]
    assert panel.offsets_s("temp_c") is None


def test_pairwise_differences(drifting: list[MeasurementSeries], grid: TimeGrid) -> None:
    panel = SensorAligner(NearestWithinTolerance()).align(drifting, grid)

    diffs = panel.pairwise_differences("temp_c")

    assert list(diffs.columns) == ["timestamp_utc", "sensor_a", "sensor_b", "delta_temp_c"]
    pairs = list(zip(diffs["sensor_a"], diffs["sensor_b"], strict=True))
    assert pairs == [(A, B)] * 5 + [(A, C)] * 5 + [(B, C)] * 5
    # A - B = -10 everywhere; A - C = 10-30, 11-31, 12-31, 13-32, 14-33; B - C likewise.
    assert diffs["delta_temp_c"].tolist() == [-10.0] * 5 + [-20.0, -20, -19, -19, -19] + [
        -10.0,
        -10,
        -9,
        -9,
        -9,
    ]
    assert diffs["timestamp_utc"].tolist() == list(grid.times) * 3


def test_pairwise_differences_only_where_both_valid(
    drifting: list[MeasurementSeries], grid: TimeGrid
) -> None:
    panel = SensorAligner(LinearInterpolation()).align(drifting, grid)

    diffs = panel.pairwise_differences("temp_c")

    # C is invalid at 0 s, so pairs with C have 4 rows.
    counts = diffs.groupby(["sensor_a", "sensor_b"]).size().to_dict()
    assert counts == {(A, B): 5, (A, C): 4, (B, C): 4}
    first_ac = diffs[(diffs["sensor_a"] == A) & (diffs["sensor_b"] == C)].iloc[0]
    assert first_ac["timestamp_utc"] == at(1800)
    assert first_ac["delta_temp_c"] == pytest.approx((10 + 1800 / 1825) - (30 + 920 / 1820))


def test_pairwise_differences_for_requested_pairs(
    drifting: list[MeasurementSeries], grid: TimeGrid
) -> None:
    panel = SensorAligner(NearestWithinTolerance()).align(drifting, grid)

    diffs = panel.pairwise_differences("temp_c", pairs=[(C, A), (SensorId(B), SensorId(A))])

    pairs = list(zip(diffs["sensor_a"], diffs["sensor_b"], strict=True))
    assert pairs == [(C, A)] * 5 + [(B, A)] * 5
    # C - A = 20, 20, 19, 19, 19 (orientation as requested); B - A = 10 everywhere.
    assert diffs["delta_temp_c"].tolist() == [20.0, 20, 19, 19, 19] + [10.0] * 5
    assert panel.pairwise_differences("temp_c", pairs=[]).empty


def test_pairwise_differences_labels_are_categorical(
    drifting: list[MeasurementSeries], grid: TimeGrid
) -> None:
    panel = SensorAligner(NearestWithinTolerance()).align(drifting, grid)

    diffs = panel.pairwise_differences("temp_c")

    for column in ("sensor_a", "sensor_b"):
        assert isinstance(diffs[column].dtype, pd.CategoricalDtype)
        assert list(diffs[column].cat.categories) == [A, B, C]
        assert diffs[column].cat.codes.dtype == np.int8
    # 8 B time + 8 B difference + 2 x 1 B codes per row, plus constant overhead.
    assert diffs.memory_usage(index=False).sum() < 18 * len(diffs) + 1024


def test_pairwise_differences_rejects_bad_pairs(
    drifting: list[MeasurementSeries], grid: TimeGrid
) -> None:
    panel = SensorAligner(NearestWithinTolerance()).align(drifting, grid)

    with pytest.raises(KeyError, match="not in the panel"):
        panel.pairwise_differences("temp_c", pairs=[(A, "99999999")])
    with pytest.raises(ValueError, match="same sensor twice"):
        panel.pairwise_differences("temp_c", pairs=[(A, A)])


def test_complete_rows(drifting: list[MeasurementSeries], grid: TimeGrid) -> None:
    panel = SensorAligner(LinearInterpolation()).align(drifting, grid)

    complete = panel.complete_rows("temp_c")

    assert list(complete.index) == [at(1800), at(3600), at(5400), at(7200)]
    assert not complete.isna().any().any()


def test_columns_are_ordered_by_sensor_id(drifting: list[MeasurementSeries]) -> None:
    panel = SensorAligner(NearestWithinTolerance()).align(drifting)

    assert [str(s) for s in panel.sensors] == [A, B, C]
    assert list(panel.variable("temp_c").columns) == [A, B, C]
    assert panel.variables == ("temp_c", "rh_pct")
    assert panel.strategy_id == "nearest_within_tolerance"


def test_derived_union_and_overlap_grids(drifting: list[MeasurementSeries]) -> None:
    union = SensorAligner(NearestWithinTolerance()).align(drifting)
    overlap = SensorAligner(NearestWithinTolerance(), GridPolicy(span=OverlapSpan())).align(
        drifting
    )

    # Union: earliest sample -300 s -> -1800 s, latest 8650 s -> 9000 s.
    assert list(union.times) == [at(s) for s in range(-1800, 9001, 1800)]
    # Overlap: latest first sample 880 s -> 1800 s, earliest last sample 7300 s -> 7200 s.
    assert list(overlap.times) == [at(s) for s in range(1800, 7201, 1800)]


def test_excluded_samples_and_unflagged_half_rows_are_skipped(series_at: SeriesAt) -> None:
    series = series_at(
        A,
        [0, 100, 200],
        temp_c=[99.0, NAN, 5.0],
        rh_pct=[99.0, 50.0, 60.0],
        qc=[int(QcFlag.SPIKE), 0, 0],
    )
    grid = TimeGrid(T0, T0)

    panel = SensorAligner(NearestWithinTolerance()).align([series], grid)
    raw = SensorAligner(NearestWithinTolerance(), exclude_mask=0).align([series], grid)

    # The SPIKE sample at 0 s is excluded. The row at 100 s has no temperature and no MISSING
    # flag (qc = 0, as read from the store); under the whole-row rule it is invalid for both
    # variables, so both take the sample at 200 s.
    assert panel.variable("temp_c")[A].tolist() == [5.0]
    assert panel.variable("rh_pct")[A].tolist() == [60.0]
    for variable in ("temp_c", "rh_pct"):
        offsets = panel.offsets_s(variable)
        assert offsets is not None
        assert offsets[A].tolist() == [200.0]
    assert raw.variable("temp_c")[A].tolist() == [99.0]
    assert raw.variable("rh_pct")[A].tolist() == [99.0]


def test_dst_transitions_do_not_matter(series_at: SeriesAt) -> None:
    """Samples every 30 min across both 2026 Europe/Prague transitions stay a regular UTC grid."""
    aligner = SensorAligner(NearestWithinTolerance())
    for first_utc in ("2026-03-29T00:00:00Z", "2026-10-25T00:00:00Z"):
        utc = pd.date_range(first_utc, periods=7, freq="30min")
        local = utc.tz_convert("Europe/Prague")
        temps = [float(i) for i in range(7)]
        sensor_utc = MeasurementSeries.from_records(SensorId(A), utc, temps, temps)
        sensor_local = MeasurementSeries.from_records(SensorId(B), local, temps, temps)

        panel = aligner.align([sensor_utc, sensor_local])

        assert list(panel.times) == list(utc)
        assert panel.variable("temp_c")[A].tolist() == temps
        assert panel.variable("temp_c")[B].tolist() == temps
        assert set(panel.pairwise_differences("temp_c")["delta_temp_c"]) == {0.0}


def test_single_sensor(series_at: SeriesAt) -> None:
    series = series_at(A, [0, 1800, 3700], [1.0, 2.0, 3.0])

    panel = SensorAligner(NearestWithinTolerance()).align([series])

    assert panel.sensors == (SensorId(A),)
    # Union grid 0 .. 5400 s; 5400 s is 1700 s from the last sample (3700 s): invalid.
    assert panel.variable("temp_c")[A].tolist()[:3] == [1.0, 2.0, 3.0]
    assert panel.validity("temp_c")[A].tolist() == [True, True, True, False]
    assert panel.pairwise_differences("temp_c").empty
    assert list(panel.pairwise_differences("temp_c").columns) == [
        "timestamp_utc",
        "sensor_a",
        "sensor_b",
        "delta_temp_c",
    ]
    assert len(panel.complete_rows("temp_c")) == 3


def test_empty_series_next_to_data(series_at: SeriesAt) -> None:
    empty = MeasurementSeries.empty(SensorId(B))
    data = series_at(A, [0, 1800], [1.0, 2.0])

    panel = SensorAligner(LinearInterpolation()).align([empty, data])

    assert len(panel) == 2
    assert panel.validity("temp_c")[B].tolist() == [False, False]
    assert panel.variable("temp_c")[B].isna().all()
    assert panel.complete_rows("temp_c").empty
    assert panel.pairwise_differences("temp_c").empty


@pytest.mark.parametrize("strategy", [NearestWithinTolerance(), LinearInterpolation()])
def test_only_empty_series_give_an_empty_panel(
    strategy: NearestWithinTolerance | LinearInterpolation, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        panel = SensorAligner(strategy).align([MeasurementSeries.empty(SensorId(A))])

    assert panel.is_empty
    assert len(panel) == 0
    assert panel.variable("temp_c").shape == (0, 1)
    assert (panel.offsets_s("temp_c") is None) == (not strategy.provides_offsets)
    assert "empty panel" in caplog.text


def test_n_sensors_without_code_changes(series_at: SeriesAt) -> None:
    """Twelve sensors, sensor i sampling every 1800 s with a clock offset of 60 i s."""
    n_sensors, n_points = 12, 48
    series = [
        series_at(
            f"{10000000 + i:08d}",
            [60 * i + 1800 * k for k in range(n_points)],
            [float(i)] * n_points,
        )
        for i in range(n_sensors)
    ]

    panel = SensorAligner(NearestWithinTolerance()).align(series, TimeGrid(T0, at(47 * 1800)))

    assert panel.variable("temp_c").shape == (n_points, n_sensors)
    offsets = panel.offsets_s("temp_c")
    assert offsets is not None
    np.testing.assert_array_equal(offsets.to_numpy()[0], [60.0 * i for i in range(n_sensors)])
    diffs = panel.pairwise_differences("temp_c")
    assert len(diffs) == n_sensors * (n_sensors - 1) // 2 * n_points
    first = diffs.iloc[0]
    assert (first["sensor_a"], first["sensor_b"], first["delta_temp_c"]) == (
        "10000000",
        "10000001",
        -1.0,
    )


def synthetic_year(n_sensors: int, seed: int) -> list[MeasurementSeries]:
    """Synthetic year: period 1825 s +- 0.5 s, random phase, whole-second timestamps."""
    rng = np.random.default_rng(seed=seed)
    n_samples = 17_280  # 1825 s apart: ~1 year
    series = []
    for i in range(n_sensors):
        period_s = 1825.0 + float(rng.uniform(-0.5, 0.5))
        offsets_s = np.round(float(rng.uniform(0, 1800)) + np.arange(n_samples) * period_s)
        times = T0 + pd.to_timedelta(offsets_s, unit="s")
        temps = rng.normal(10.0, 5.0, n_samples)
        series.append(
            MeasurementSeries.from_records(SensorId(f"{20000000 + i}"), times, temps, temps)
        )
    return series


def test_a_year_of_many_sensors_is_vectorised() -> None:
    """Synthetic year of 30 min data for 30 sensors; checks shape, not timing."""
    panel = SensorAligner(LinearInterpolation()).align(synthetic_year(30, seed=16))

    assert panel.variable("temp_c").shape[1] == 30
    assert len(panel) > 17_500
    assert panel.validity("temp_c").to_numpy().mean() > 0.99


def test_default_nearest_covers_a_year_of_1825_s_sampling() -> None:
    """With default parameters, ~1825 s sampling fills the 1800 s grid (overlap span)."""
    aligner = SensorAligner(NearestWithinTolerance(), GridPolicy(span=OverlapSpan()))

    panel = aligner.align(synthetic_year(30, seed=17))

    coverage = panel.validity("temp_c").to_numpy().mean(axis=0)
    assert coverage.min() == pytest.approx(1.0, abs=1e-3)
    assert len(panel.complete_rows("temp_c")) / len(panel) > 0.99
    offsets = panel.offsets_s("temp_c")
    assert offsets is not None
    assert np.nanmax(offsets.to_numpy()) <= NearestWithinTolerance().tolerance_s  # 935 s


def test_rejects_no_series() -> None:
    with pytest.raises(ValueError, match="At least one series"):
        SensorAligner(NearestWithinTolerance()).align([])


def test_rejects_duplicate_sensors(series_at: SeriesAt) -> None:
    one = series_at(A, [0], [1.0])

    with pytest.raises(ValueError, match="duplicated"):
        SensorAligner(NearestWithinTolerance()).align([one, one])


@pytest.mark.parametrize("mask", [-1, 1 << 12])
def test_rejects_unknown_exclude_bits(mask: int) -> None:
    with pytest.raises(ValueError, match="not QcFlags"):
        SensorAligner(NearestWithinTolerance(), exclude_mask=mask)


def test_defaults_and_properties() -> None:
    strategy = NearestWithinTolerance()
    aligner = SensorAligner(strategy)

    assert aligner.strategy is strategy
    assert aligner.grid_policy == GridPolicy()
    assert aligner.grid_policy.step_s == 1800.0
    assert aligner.exclude_mask == int(QcFlag.DEFAULT_EXCLUDE)


def test_from_config(drifting: list[MeasurementSeries]) -> None:
    config = AlignmentConfig(
        strategy="linear_interpolation",
        params={"max_gap_s": 3600.0},
        grid_step_s=900.0,
        span="overlap",
    )

    aligner = SensorAligner.from_config(config, exclude_mask=0)

    assert isinstance(aligner.strategy, LinearInterpolation)
    assert aligner.strategy.max_gap_s == 3600.0
    assert isinstance(aligner.grid_policy.span, OverlapSpan)
    assert aligner.exclude_mask == 0
    panel = aligner.align(drifting)
    # Overlap 880 .. 7300 s on a 900 s grid: 900 .. 7200 s.
    assert list(panel.times) == [at(s) for s in range(900, 7201, 900)]
