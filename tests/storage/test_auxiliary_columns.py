"""Precipitation and battery columns in the store (WP-1.9). All values are synthetic."""

from __future__ import annotations

import hashlib
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from sivin.core.ids import SensorId
from sivin.core.schema import Column
from sivin.storage.conflicts import PreferExisting, RaiseOnConflict
from sivin.storage.errors import MeasurementConflictError
from sivin.storage.merge import AppendCounts
from sivin.storage.store import MeasurementStore

from .conftest import UtcSeriesFactory

LEGACY_STORE = Path(__file__).parents[1] / "fixtures" / "storage" / "legacy_layout"
"""A committed synthetic store whose file has the layout written before WP-1.9."""

LEGACY_HEADER = "timestamp_utc,temp_c,rh_pct,source"
CURRENT_HEADER = "timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source"
TIMES = ["2026-05-01T00:00:00Z", "2026-05-01T00:30:30Z", "2026-05-01T01:01:00Z"]
"""The timestamps of the committed legacy file."""


@pytest.fixture
def legacy_store(tmp_path: Path) -> MeasurementStore:
    """A copy of the committed legacy-layout store."""
    root = tmp_path / "data"
    shutil.copytree(LEGACY_STORE, root, ignore=shutil.ignore_patterns("*.md"))
    return MeasurementStore(root)


def _partition(store: MeasurementStore) -> Path:
    return store.root / "raw" / "77678271" / "2026.csv"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_committed_legacy_file_has_the_old_header() -> None:
    lines = (LEGACY_STORE / "raw" / "77678271" / "2026.csv").read_text().splitlines()
    assert lines[0] == LEGACY_HEADER


def test_legacy_file_is_read_unchanged_with_nan_auxiliary_columns(
    legacy_store: MeasurementStore, sensor_id: SensorId
) -> None:
    frame = legacy_store.read(sensor_id).frame
    np.testing.assert_array_equal(frame[Column.TEMP].to_numpy(), [12.5, 12.25, math.nan])
    assert frame[Column.RH].tolist() == [80.0, 81.5, 82.0]
    # The full source of the old file reads back as the short export identifier.
    assert frame[Column.SOURCE].tolist() == ["20260501T060000"] * 3
    assert frame[[Column.PRECIP, Column.PRECIP_TOTAL, Column.BATTERY]].isna().all().all()


def test_append_without_new_values_leaves_the_legacy_file_untouched(
    legacy_store: MeasurementStore, make_utc_series: UtcSeriesFactory
) -> None:
    before = _digest(_partition(legacy_store))
    result = legacy_store.append(
        make_utc_series(TIMES[:2], [12.5, 12.25], [80.0, 81.5], "20260502_060000")
    )
    assert result.counts == AppendCounts(identical_skipped=2)
    assert result.files_written == ()
    assert _digest(_partition(legacy_store)) == before


def test_filling_the_new_columns_rewrites_the_file_in_the_current_layout(
    legacy_store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    export = make_utc_series(
        TIMES,
        [12.5, 12.25, math.nan],
        [80.0, 81.5, 82.0],
        "20260502_060000",
        precip_mm=[0.0, 0.3, 0.0],
        precip_total_mm=[323.0, 323.3, 323.3],
        battery_v=[3.6, 3.6, math.nan],
    )
    result = legacy_store.append(export)
    # 3 + 3 + 2 auxiliary values filled; the missing temperature (row 3) and battery (row 3)
    # are missing in both.
    assert result.counts == AppendCounts(filled_values=8)
    assert _partition(legacy_store).read_text().splitlines() == [
        CURRENT_HEADER,
        "2026-05-01T00:00:00Z,12.5,80.0,0.0,323.0,3.6,20260502T060000",
        "2026-05-01T00:30:30Z,12.25,81.5,0.3,323.3,3.6,20260502T060000",
        "2026-05-01T01:01:00Z,,82.0,0.0,323.3,,20260502T060000",
    ]
    rewritten = _digest(_partition(legacy_store))
    again = legacy_store.append(export)
    assert again.counts == AppendCounts(identical_skipped=3)
    assert again.files_written == ()
    assert _digest(_partition(legacy_store)) == rewritten
    frame = legacy_store.read(sensor_id).frame
    np.testing.assert_array_equal(frame[Column.BATTERY].to_numpy(), [3.6, 3.6, math.nan])


def test_an_import_without_auxiliary_columns_never_erases_stored_ones(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    store.append(
        make_utc_series(TIMES[:1], [1.0], [50.0], "new.csv", precip_mm=[0.2], battery_v=[3.5])
    )
    before = _digest(_partition(store))
    result = store.append(make_utc_series(TIMES[:1], [1.0], [50.0], "old.csv"))
    assert result.counts == AppendCounts(identical_skipped=0, ignored_missing_values=2)
    assert result.files_written == ()
    assert _digest(_partition(store)) == before
    frame = store.read(sensor_id).frame
    assert (frame[Column.PRECIP].tolist(), frame[Column.BATTERY].tolist()) == ([0.2], [3.5])


def test_different_auxiliary_values_are_conflicts_for_the_policy(
    tmp_path: Path, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    first = make_utc_series(TIMES[:1], [1.0], [50.0], "a.csv", precip_mm=[0.3], battery_v=[3.5])
    second = make_utc_series(TIMES[:1], [1.0], [50.0], "b.csv", precip_mm=[0.6], battery_v=[3.5])

    newest = MeasurementStore(tmp_path / "newest")
    newest.append(first)
    result = newest.append(second)
    assert result.counts == AppendCounts(conflicting_values=1, replaced_values=1)
    (decision,) = result.conflicts
    assert decision.conflict.column == "precip_mm"
    assert (decision.conflict.stored_value, decision.conflict.incoming_value) == (0.3, 0.6)
    assert newest.read(sensor_id).frame[Column.PRECIP].tolist() == [0.6]

    existing = MeasurementStore(tmp_path / "existing", conflict_policy=PreferExisting())
    existing.append(first)
    kept = existing.append(second)
    assert kept.counts == AppendCounts(conflicting_values=1)
    assert existing.read(sensor_id).frame[Column.PRECIP].tolist() == [0.3]

    strict = MeasurementStore(tmp_path / "strict", conflict_policy=RaiseOnConflict())
    strict.append(first)
    with pytest.raises(MeasurementConflictError, match="precip_mm"):
        strict.append(second)
