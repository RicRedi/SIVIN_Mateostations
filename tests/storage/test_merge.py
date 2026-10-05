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
    PreferExisting,
    PreferNewest,
    RaiseOnConflict,
    RowConflict,
    StoredRow,
    conflict_policy_registry,
)
from sivin.storage.errors import MeasurementConflictError
from sivin.storage.merge import MAX_LOGGED_CONFLICTS, AppendCounts, SeriesMerger

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
    # T1 identical, T2 identical (NaN == NaN), T0 conflicting, T3 new.
    incoming = make_utc_series(
        [T0, T1, T2, T3], [10.5, 11.0, math.nan, 12.0], [80.0, 81.0, 82.0, 83.0], "new.csv"
    )
    outcome = SeriesMerger(PreferNewest()).merge(stored, incoming)
    assert outcome.counts == AppendCounts(
        new_rows=1, identical_skipped=2, conflicting_rows=1, replaced_rows=1
    )
    frame = outcome.series.frame
    np.testing.assert_array_equal(frame[Column.TEMP], [10.5, 11.0, math.nan, 12.0])
    # Identical rows keep the stored source; the replaced and the new row carry the new one.
    assert frame[Column.SOURCE].tolist() == ["new.csv", "old.csv", "old.csv", "new.csv"]


def test_prefer_existing_keeps_stored_value(
    stored: MeasurementSeries, make_utc_series: UtcSeriesFactory
) -> None:
    incoming = make_utc_series([T0, T3], [99.0, 12.0], [80.0, 83.0], "new.csv")
    outcome = SeriesMerger(PreferExisting()).merge(stored, incoming)
    assert outcome.counts == AppendCounts(new_rows=1, conflicting_rows=1)
    frame = outcome.series.frame
    np.testing.assert_array_equal(frame[Column.TEMP], [10.0, 11.0, math.nan, 12.0])
    assert frame[Column.SOURCE].iloc[0] == "old.csv"


def test_missing_versus_present_value_is_a_conflict(
    stored: MeasurementSeries, make_utc_series: UtcSeriesFactory
) -> None:
    incoming = make_utc_series([T2], [7.0], [82.0])
    outcome = SeriesMerger(PreferNewest()).merge(stored, incoming)
    assert outcome.counts == AppendCounts(conflicting_rows=1, replaced_rows=1)
    assert outcome.series.frame[Column.TEMP].iloc[2] == 7.0


def test_raise_on_conflict(stored: MeasurementSeries, make_utc_series: UtcSeriesFactory) -> None:
    incoming = make_utc_series([T1], [11.1], [81.0], "new.csv")
    with pytest.raises(MeasurementConflictError, match=r"stored temp_c=11.0.*incoming temp_c=11.1"):
        SeriesMerger(RaiseOnConflict()).merge(stored, incoming)


def test_conflicts_are_logged_with_both_values(
    stored: MeasurementSeries,
    make_utc_series: UtcSeriesFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    incoming = make_utc_series([T0], [10.5], [80.0], "new.csv")
    with caplog.at_level(logging.WARNING, logger="sivin.storage.merge"):
        SeriesMerger(PreferNewest()).merge(stored, incoming)
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "temp_c=10.0, rh_pct=80.0 (old.csv)" in message
    assert "temp_c=10.5, rh_pct=80.0 (new.csv)" in message
    assert "kept the incoming row (policy prefer_newest)" in message


def test_conflict_logging_is_capped(
    make_utc_series: UtcSeriesFactory, caplog: pytest.LogCaptureFixture
) -> None:
    n_rows = MAX_LOGGED_CONFLICTS + 5
    times = [t.isoformat() for t in pd.date_range(T0, periods=n_rows, freq="30min")]
    stored = make_utc_series(times, [1.0] * n_rows, [50.0] * n_rows)
    incoming = make_utc_series(times, [2.0] * n_rows, [50.0] * n_rows)
    with caplog.at_level(logging.WARNING, logger="sivin.storage.merge"):
        outcome = SeriesMerger(PreferExisting()).merge(stored, incoming)
    assert outcome.counts.conflicting_rows == n_rows
    assert len(caplog.records) == MAX_LOGGED_CONFLICTS + 1
    assert "5 further conflict(s)" in caplog.records[-1].getMessage()


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
    total = AppendCounts(1, 2, 3, 1) + AppendCounts(4, 0, 1, 0)
    assert total == AppendCounts(
        new_rows=5, identical_skipped=2, conflicting_rows=4, replaced_rows=1
    )
    assert AppendCounts.from_dict(total.to_dict()) == total
    assert total.changes_data
    assert not AppendCounts(identical_skipped=3, conflicting_rows=2).changes_data


def test_registry_names() -> None:
    assert conflict_policy_registry.names() == ("prefer_existing", "prefer_newest", "raise")
    assert isinstance(conflict_policy_registry.create("prefer_newest"), PreferNewest)


def test_row_conflict_describe_unknown_source(sensor_id: SensorId) -> None:
    conflict = RowConflict(
        sensor_id,
        pd.Timestamp(T0),
        StoredRow(1.0, math.nan, ""),
        StoredRow(2.0, 3.0, "b.csv"),
    )
    assert conflict.describe() == (
        "sensor 77678271 at 2026-05-01T00:00:00+00:00: stored temp_c=1.0, rh_pct=nan "
        "(unknown source) vs incoming temp_c=2.0, rh_pct=3.0 (b.csv)"
    )
