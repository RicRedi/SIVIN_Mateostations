"""Tests of TimeGrid, GridPolicy and the span rules. All data are synthetic."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from sivin.alignment.grid import (
    DEFAULT_GRID_STEP_S,
    GridPolicy,
    OverlapSpan,
    TimeGrid,
    UnionSpan,
    epoch_ns,
    span_registry,
    usable_span,
)
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

T0 = pd.Timestamp("2026-06-01T00:00:00Z")
STEP = pd.Timedelta(seconds=1800)
NONE = 0


def at(offset_s: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(seconds=offset_s)


def test_default_step_is_thirty_minutes() -> None:
    assert DEFAULT_GRID_STEP_S == 1800.0
    assert TimeGrid(T0, at(3600)).step == pd.Timedelta(minutes=30)


def test_grid_points_include_start_and_whole_steps_up_to_end() -> None:
    grid = TimeGrid(T0, at(4000), step_s=1800.0)

    assert list(grid.times) == [T0, at(1800), at(3600)]
    assert len(grid) == 3
    assert str(grid.times.dtype) == "datetime64[ns, UTC]"
    assert grid.times.name == "timestamp_utc"


def test_single_point_grid() -> None:
    grid = TimeGrid(T0, T0)

    assert list(grid.times) == [T0]


def test_grid_converts_bounds_to_utc() -> None:
    start = pd.Timestamp("2026-06-01T02:00:00+02:00")
    grid = TimeGrid(start, start + STEP)

    assert str(grid.start.tz) == "UTC"
    assert grid.start == T0


def test_times_ns_are_epoch_nanoseconds() -> None:
    grid = TimeGrid(pd.Timestamp("1970-01-01T00:00:00Z"), pd.Timestamp("1970-01-01T01:00:00Z"))

    np.testing.assert_array_equal(grid.times_ns, [0, 1_800_000_000_000, 3_600_000_000_000])


@pytest.mark.parametrize("step_s", [0.0, -1.0, float("nan"), float("inf")])
def test_grid_rejects_invalid_step(step_s: float) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        TimeGrid(T0, at(3600), step_s=step_s)


def test_grid_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="before its start"):
        TimeGrid(at(3600), T0)


def test_grid_rejects_naive_bounds() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TimeGrid(pd.Timestamp("2026-06-01T00:00:00"), at(3600))


def test_union_widens_outwards_to_epoch_anchored_points() -> None:
    spans = [(at(-300), at(5000)), (at(880), at(8650))]

    first, last = UnionSpan().bounds(spans, STEP)

    # min first -300 s -> floor to -1800 s; max last 8650 s -> ceil to 9000 s.
    assert (first, last) == (at(-1800), at(9000))


def test_overlap_narrows_inwards_to_epoch_anchored_points() -> None:
    spans = [(at(-300), at(7300)), (at(880), at(8650))]

    first, last = OverlapSpan().bounds(spans, STEP)

    # max first 880 s -> ceil to 1800 s; min last 7300 s -> floor to 7200 s.
    assert (first, last) == (at(1800), at(7200))


def test_overlap_without_common_grid_point_is_none(caplog: pytest.LogCaptureFixture) -> None:
    spans = [(at(0), at(1000)), (at(1900), at(5000))]

    with caplog.at_level(logging.WARNING):
        assert OverlapSpan().bounds(spans, STEP) is None
    assert "do not overlap" in caplog.text


def test_overlap_inside_one_step_is_none() -> None:
    assert OverlapSpan().bounds([(at(100), at(1700))], STEP) is None


@pytest.mark.parametrize("rule", [UnionSpan(), OverlapSpan()])
def test_no_spans_give_no_bounds(rule: UnionSpan | OverlapSpan) -> None:
    assert rule.bounds([], STEP) is None


def test_span_rules_are_registered() -> None:
    assert span_registry.ids() == ("overlap", "union")
    assert span_registry.get("union") is UnionSpan


def test_policy_builds_grid_with_its_step() -> None:
    policy = GridPolicy(step_s=900.0, span=UnionSpan())

    grid = policy.grid_for([(at(100), at(1000))])

    assert grid == TimeGrid(T0, at(1800), step_s=900.0)


def test_policy_without_spans_gives_none() -> None:
    assert GridPolicy().grid_for([]) is None


def test_policy_rejects_invalid_step() -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        GridPolicy(step_s=0.0)


def test_from_series_uses_only_usable_rows() -> None:
    nan = float("nan")
    series = MeasurementSeries.from_records(
        SensorId("11111111"),
        [at(0), at(1800), at(3600), at(5400), at(7200)],
        temp_c=[1.0, 2.0, 3.0, nan, 5.0],
        rh_pct=[1.0, 2.0, 3.0, nan, 5.0],
        qc=[int(QcFlag.PRE_DEPLOYMENT), 0, 0, 0, int(QcFlag.SPIKE)],
    )

    # Row 0 is excluded (PRE_DEPLOYMENT), row 3 has no value, row 4 is excluded (SPIKE).
    assert usable_span(series, int(QcFlag.DEFAULT_EXCLUDE)) == (at(1800), at(3600))
    assert usable_span(series, NONE) == (at(0), at(7200))
    grid = TimeGrid.from_series([series], GridPolicy(), int(QcFlag.DEFAULT_EXCLUDE))
    assert grid == TimeGrid(at(1800), at(3600))


def test_from_series_ignores_series_without_usable_rows() -> None:
    empty = MeasurementSeries.empty(SensorId("22222222"))
    full = MeasurementSeries.from_records(SensorId("11111111"), [at(0), at(3600)], [1, 2], [1, 2])

    grid = TimeGrid.from_series([empty, full], GridPolicy(span=OverlapSpan()), NONE)

    assert grid == TimeGrid(T0, at(3600))
    assert TimeGrid.from_series([empty], GridPolicy(), NONE) is None


def test_epoch_ns_of_series_and_index_agree() -> None:
    index = pd.DatetimeIndex([at(0), at(1)])

    np.testing.assert_array_equal(epoch_ns(index), epoch_ns(pd.Series(index)))
    assert epoch_ns(index)[1] - epoch_ns(index)[0] == 1_000_000_000


def test_span_rules_compare_by_type() -> None:
    assert UnionSpan() == UnionSpan()
    assert UnionSpan() != OverlapSpan()
    assert len({UnionSpan(), UnionSpan(), OverlapSpan()}) == 2
    assert repr(OverlapSpan()) == "OverlapSpan()"
