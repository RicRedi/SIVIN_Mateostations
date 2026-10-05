"""Tests of SeriesMerger and the conflict policies. All values are synthetic."""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
import pytest

from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries
from sivin.storage.conflicts import (
    ConflictDecision,
    PreferExisting,
    PreferNewest,
    RaiseOnConflict,
    ValueConflict,
    conflict_policy_registry,
)
from sivin.storage.errors import MeasurementConflictError
from sivin.storage.merge import DEFAULT_MAX_RECORDED_CONFLICTS, AppendCounts, SeriesMerger

from .conftest import UtcSeriesFactory

T0, T1, T2, T3 = (
    "2026-05-01T00:00:00Z",
    "2026-05-01T00:30:00Z",
    "2026-05-01T01:00:00Z",
    "2026-05-01T01:30:00Z",
)


@pytest.fixture
def stored(make_utc_series: UtcSeriesFactory) -> MeasurementSeries:
    return make_utc_series([T0, T1, T2], [10.0, 11.0, math.nan], [80.0, 81.0, 82.0], "old.csv")


def test_new_identical_and_conflicting_rows_with_prefer_newest(
    stored: MeasurementSeries, make_utc_series: UtcSeriesFactory
) -> None:
    # T1 identical, T2 identical (NaN == NaN), T0 temperature conflicts, T3 new.
    incoming = make_utc_series(
        [T0, T1, T2, T3], [10.5, 11.0, math.nan, 12.0], [80.0, 81.0, 82.0, 83.0], "new.csv"
    )
    outcome = SeriesMerger(PreferNewest()).merge(stored, incoming)
    assert outcome.counts == AppendCounts(
        new_rows=1, identical_skipped=2, conflicting_values=1, replaced_values=1
    )
    frame = outcome.series.frame
    np.testing.assert_array_equal(frame[Column.TEMP], [10.5, 11.0, math.nan, 12.0])
    # Identical rows keep the stored source; the replaced and the new row carry the new one.
    assert frame[Column.SOURCE].tolist() == ["new.csv", "old.csv", "old.csv", "new.csv"]
    assert outcome.conflicts == (
        ConflictDecision(
            ValueConflict(
                SensorId("77678271"), pd.Timestamp(T0), "temp_c", 10.0, 10.5, "old.csv", "new.csv"
            ),
            kept_incoming=True,
            policy="prefer_newest",
        ),
    )


@pytest.mark.parametrize("policy", [PreferNewest(), PreferExisting(), RaiseOnConflict()])
def test_missing_incoming_value_never_overwrites_a_stored_value(
    make_utc_series: UtcSeriesFactory, sensor_id: SensorId, policy: PreferNewest
) -> None:
    # Reviewer example 1: stored (12.3, 80.0), incoming (NaN, 80.0) -> stays (12.3, 80.0).
    stored = make_utc_series([T0], [12.3], [80.0], "old.csv")
    incoming = make_utc_series([T0], [math.nan], [80.0], "new.csv")
    outcome = SeriesMerger(policy).merge(stored, incoming)
    assert outcome.counts == AppendCounts(ignored_missing_values=1)
    assert not outcome.counts.changes_data
    frame = outcome.series.frame
    assert frame[Column.TEMP].tolist() == [12.3]
    assert frame[Column.RH].tolist() == [80.0]
    assert frame[Column.SOURCE].tolist() == ["old.csv"]
    assert outcome.conflicts == ()


@pytest.mark.parametrize("policy", [PreferNewest(), PreferExisting(), RaiseOnConflict()])
def test_mixed_missing_values_merge_column_by_column(
    make_utc_series: UtcSeriesFactory, policy: PreferNewest
) -> None:
    # Reviewer example 2: stored (NaN, 70.0), incoming (11.0, NaN) -> (11.0, 70.0).
    stored = make_utc_series([T0], [math.nan], [70.0], "old.csv")
    incoming = make_utc_series([T0], [11.0], [math.nan], "new.csv")
    outcome = SeriesMerger(policy).merge(stored, incoming)
    assert outcome.counts == AppendCounts(filled_values=1, ignored_missing_values=1)
    assert outcome.counts.changes_data
    frame = outcome.series.frame
    assert frame[Column.TEMP].tolist() == [11.0]
    assert frame[Column.RH].tolist() == [70.0]
    assert frame[Column.SOURCE].tolist() == ["new.csv"]


def test_prefer_existing_keeps_stored_value(
    stored: MeasurementSeries, make_utc_series: UtcSeriesFactory
) -> None:
    incoming = make_utc_series([T0, T3], [99.0, 12.0], [80.0, 83.0], "new.csv")
    outcome = SeriesMerger(PreferExisting()).merge(stored, incoming)
    assert outcome.counts == AppendCounts(new_rows=1, conflicting_values=1)
    frame = outcome.series.frame
    np.testing.assert_array_equal(frame[Column.TEMP], [10.0, 11.0, math.nan, 12.0])
    assert frame[Column.SOURCE].iloc[0] == "old.csv"
    assert [d.kept_incoming for d in outcome.conflicts] == [False]


def test_conflict_in_one_column_and_fill_in_the_other(make_utc_series: UtcSeriesFactory) -> None:
    stored = make_utc_series([T0], [5.0], [math.nan], "old.csv")
    incoming = make_utc_series([T0], [6.0], [60.0], "new.csv")
    outcome = SeriesMerger(PreferExisting()).merge(stored, incoming)
    assert outcome.counts == AppendCounts(filled_values=1, conflicting_values=1)
    frame = outcome.series.frame
    assert frame[Column.TEMP].tolist() == [5.0]
    assert frame[Column.RH].tolist() == [60.0]
    # A value was taken from the import, so the row now names the import as its source.
    assert frame[Column.SOURCE].tolist() == ["new.csv"]


def test_raise_on_conflict(stored: MeasurementSeries, make_utc_series: UtcSeriesFactory) -> None:
    incoming = make_utc_series([T1], [11.1], [81.0], "new.csv")
    with pytest.raises(MeasurementConflictError, match=r"temp_c: stored 11.0.*incoming 11.1"):
        SeriesMerger(RaiseOnConflict()).merge(stored, incoming)


def test_conflicts_are_logged_with_both_values(
    stored: MeasurementSeries,
    make_utc_series: UtcSeriesFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    incoming = make_utc_series([T0], [10.5], [80.0], "new.csv")
    with caplog.at_level(logging.WARNING, logger="sivin.storage.merge"):
        SeriesMerger(PreferNewest()).merge(stored, incoming)
    assert [record.getMessage() for record in caplog.records] == [
        "Conflict, sensor 77678271 at 2026-05-01T00:00:00+00:00, temp_c: stored 10.0 (old.csv) "
        "vs incoming 10.5 (new.csv); kept the incoming value (policy prefer_newest)."
    ]


def test_recorded_and_logged_conflicts_are_capped(
    make_utc_series: UtcSeriesFactory, caplog: pytest.LogCaptureFixture
) -> None:
    n_rows, cap = 5, 3
    times = [t.isoformat() for t in pd.date_range(T0, periods=n_rows, freq="30min")]
    stored = make_utc_series(times, [1.0] * n_rows, [50.0] * n_rows)
    incoming = make_utc_series(times, [2.0] * n_rows, [51.0] * n_rows)
    with caplog.at_level(logging.WARNING, logger="sivin.storage.merge"):
        outcome = SeriesMerger(PreferExisting(), max_recorded_conflicts=cap).merge(stored, incoming)
    assert outcome.counts.conflicting_values == 2 * n_rows
    # Sorted by time, then column: (T0, rh), (T0, temp), (T1, rh).
    assert [(d.conflict.timestamp_utc.minute, d.conflict.column) for d in outcome.conflicts] == [
        (0, "rh_pct"),
        (0, "temp_c"),
        (30, "rh_pct"),
    ]
    assert len(caplog.records) == cap + 1
    assert "7 further conflict(s)" in caplog.records[-1].getMessage()


def test_default_and_invalid_cap() -> None:
    assert SeriesMerger(PreferNewest()).max_recorded_conflicts == DEFAULT_MAX_RECORDED_CONFLICTS
    with pytest.raises(ValueError, match="must not be negative"):
        SeriesMerger(PreferNewest(), max_recorded_conflicts=-1)


def test_qc_flags_are_dropped(make_utc_series: UtcSeriesFactory, sensor_id: SensorId) -> None:
    incoming = make_utc_series([T0], [1.0], [2.0], qc=[4])
    outcome = SeriesMerger(PreferNewest()).merge(MeasurementSeries.empty(sensor_id), incoming)
    assert outcome.series.frame[Column.QC].tolist() == [0]


def test_missing_source_becomes_empty_string(
    make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    incoming = make_utc_series([T0], [1.0], [2.0], source=None)
    outcome = SeriesMerger(PreferNewest()).merge(MeasurementSeries.empty(sensor_id), incoming)
    assert outcome.series.frame[Column.SOURCE].tolist() == [""]


def test_merge_rejects_other_sensor(
    stored: MeasurementSeries, make_utc_series: UtcSeriesFactory
) -> None:
    other = make_utc_series([T0], [1.0], [2.0], sensor=SensorId("11111111"))
    with pytest.raises(ValueError, match="Cannot merge sensor 11111111"):
        SeriesMerger(PreferNewest()).merge(stored, other)


def test_policy_property() -> None:
    policy = PreferExisting()
    assert SeriesMerger(policy).policy is policy


def test_append_counts_add_and_dict_round_trip() -> None:
    total = AppendCounts(1, 2, 3, 4, 5, 1) + AppendCounts(4, 0, 0, 1, 1, 0)
    assert total == AppendCounts(
        new_rows=5,
        identical_skipped=2,
        filled_values=3,
        ignored_missing_values=5,
        conflicting_values=6,
        replaced_values=1,
    )
    assert AppendCounts.from_dict(total.to_dict()) == total
    assert total.changes_data
    assert not AppendCounts(identical_skipped=3, conflicting_values=2).changes_data
    assert AppendCounts(filled_values=1).changes_data


def test_registry_names() -> None:
    assert conflict_policy_registry.names() == ("prefer_existing", "prefer_newest", "raise")
    for name in conflict_policy_registry.names():
        assert conflict_policy_registry.get(name).name == name
    assert isinstance(conflict_policy_registry.create("prefer_newest"), PreferNewest)


def test_value_conflict_describe_unknown_source(sensor_id: SensorId) -> None:
    conflict = ValueConflict(sensor_id, pd.Timestamp(T0), "rh_pct", 1.0, 2.0, "", "b.csv")
    assert conflict.describe() == (
        "sensor 77678271 at 2026-05-01T00:00:00+00:00, rh_pct: stored 1.0 (unknown source) "
        "vs incoming 2.0 (b.csv)"
    )


def test_conflict_decision_dict_round_trip(sensor_id: SensorId) -> None:
    decision = ConflictDecision(
        ValueConflict(sensor_id, pd.Timestamp(T0), "temp_c", 1.5, -2.25, "a.csv", "b.csv"),
        kept_incoming=False,
        policy="prefer_existing",
    )
    data = decision.to_dict()
    assert data == {
        "sensor_id": "77678271",
        "timestamp_utc": "2026-05-01T00:00:00Z",
        "column": "temp_c",
        "stored_value": 1.5,
        "incoming_value": -2.25,
        "stored_source": "a.csv",
        "incoming_source": "b.csv",
        "kept": "stored",
        "policy": "prefer_existing",
    }
    assert ConflictDecision.from_dict(data) == decision
    with pytest.raises(ValueError, match="'kept'"):
        ConflictDecision.from_dict({**data, "kept": "both"})
