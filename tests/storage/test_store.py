"""Tests of MeasurementStore. All measurement values are synthetic."""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import numpy as np
import pandas as pd
import pytest

from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries
from sivin.storage.atomic import AtomicFileWriter
from sivin.storage.codec import CsvSeriesCodec
from sivin.storage.conflicts import PreferExisting, PreferNewest, RaiseOnConflict
from sivin.storage.errors import MeasurementConflictError, StoreFormatError
from sivin.storage.merge import AppendCounts
from sivin.storage.store import MeasurementStore

from .conftest import UtcSeriesFactory

INTERVAL_S = 1800
"""Sampling step of the synthetic series in seconds."""

OTHER = SensorId("11111111")
EXPORT_A = "MeteoData_8615620 77678271 (VUT)_20260501_060000.csv"
EXPORT_B = "MeteoData_8615620 77678271 (VUT)_20260502_060000.csv"
NEW_CSV_SHA256 = "4d4732a2cb66fff9c0c6d137ffa6452fd04bb9ff620556d7615ee7f746331aa2"
"""SHA-256 of the file name ``new.csv`` (``printf 'new.csv' | sha256sum``)."""


def _digests(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _regular_series(
    sensor_id: SensorId, start_utc: str, n_rows: int, source: str
) -> MeasurementSeries:
    """Synthetic series: temp_c = 0.1 * i, rh_pct = 50 + 0.5 * (i % 10)."""
    times = pd.date_range(start_utc, periods=n_rows, freq=f"{INTERVAL_S}s", tz="UTC")
    index = np.arange(n_rows)
    return MeasurementSeries.from_records(
        sensor_id, times, 0.1 * index, 50.0 + 0.5 * (index % 10), source=source
    )


def test_double_import_leaves_files_byte_identical(
    store: MeasurementStore, sensor_id: SensorId
) -> None:
    series = _regular_series(sensor_id, "2025-12-30T00:00:00Z", 200, "export.csv")
    first = store.append(series)
    before = _digests(store.root)
    second = store.append(series)
    assert first.counts == AppendCounts(new_rows=200)
    assert len(first.files_written) == 2
    assert second.counts == AppendCounts(identical_skipped=200)
    assert second.files_written == ()
    assert _digests(store.root) == before


def test_reimport_under_another_file_name_changes_nothing(
    store: MeasurementStore, sensor_id: SensorId
) -> None:
    store.append(_regular_series(sensor_id, "2026-01-01T00:00:00Z", 10, "export (1).csv"))
    before = _digests(store.root)
    result = store.append(_regular_series(sensor_id, "2026-01-01T00:00:00Z", 10, "export.xlsx"))
    assert result.counts == AppendCounts(identical_skipped=10)
    assert _digests(store.root) == before


def test_stored_values_do_not_depend_on_import_order(tmp_path: Path, sensor_id: SensorId) -> None:
    signal = _regular_series(sensor_id, "2026-01-01T00:00:00Z", 96, "signal")
    a, b = _rows(signal, 0, 60, EXPORT_A), _rows(signal, 40, 96, EXPORT_B)
    one, two = MeasurementStore(tmp_path / "one"), MeasurementStore(tmp_path / "two")
    one.append(a)
    one.append(b)
    two.append(b)
    two.append(a)
    values = [str(Column.TIMESTAMP), str(Column.TEMP), str(Column.RH)]
    first, second = one.read(sensor_id).frame, two.read(sensor_id).frame
    assert first[values].equals(second[values])
    # Overlapping identical rows keep the source of whichever export came first.
    assert first[Column.SOURCE].iloc[50] == "20260501T060000"
    assert second[Column.SOURCE].iloc[50] == "20260502T060000"


def _rows(series: MeasurementSeries, start: int, stop: int, source: str) -> MeasurementSeries:
    """Rows ``start:stop`` of ``series`` as a new export named ``source``."""
    frame = series.frame.iloc[start:stop]
    return MeasurementSeries.from_records(
        series.sensor_id,
        frame[Column.TIMESTAMP],
        frame[Column.TEMP],
        frame[Column.RH],
        source=source,
    )


def test_two_overlapping_exports_merge(store: MeasurementStore, sensor_id: SensorId) -> None:
    # Export A holds rows 0..47, export B rows 24..71 of the same synthetic signal.
    signal = _regular_series(sensor_id, "2026-01-01T00:00:00Z", 72, "signal")
    store.append(_rows(signal, 0, 48, EXPORT_A))
    result = store.append(_rows(signal, 24, 72, EXPORT_B))
    assert result.counts == AppendCounts(new_rows=24, identical_skipped=24)
    merged = store.read(sensor_id).frame
    assert merged[Column.TIMESTAMP].equals(signal.frame[Column.TIMESTAMP])
    np.testing.assert_array_equal(merged[Column.TEMP], signal.frame[Column.TEMP])
    np.testing.assert_array_equal(merged[Column.RH], signal.frame[Column.RH])
    # The store keeps the short export identifiers, not the file names.
    assert merged[Column.SOURCE].tolist() == ["20260501T060000"] * 48 + ["20260502T060000"] * 24


def test_conflict_prefer_newest_replaces_and_rewrites(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    store.append(make_utc_series(["2026-02-01T00:00:00Z"], [3.0], [70.0], "old.csv"))
    result = store.append(make_utc_series(["2026-02-01T00:00:00Z"], [3.1], [70.0], "new.csv"))
    assert result.counts == AppendCounts(conflicting_values=1, replaced_values=1)
    assert store.read(sensor_id).frame[Column.TEMP].tolist() == [3.1]
    assert [d.to_dict()["kept"] for d in result.conflicts] == ["incoming"]


def test_conflict_prefer_existing_writes_nothing(
    tmp_path: Path, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    store = MeasurementStore(tmp_path, conflict_policy=PreferExisting())
    store.append(make_utc_series(["2026-02-01T00:00:00Z"], [3.0], [70.0], "old.csv"))
    before = _digests(tmp_path)
    result = store.append(make_utc_series(["2026-02-01T00:00:00Z"], [3.1], [70.0], "new.csv"))
    assert result.counts == AppendCounts(conflicting_values=1)
    assert result.files_written == ()
    assert [d.to_dict()["kept"] for d in result.conflicts] == ["stored"]
    assert _digests(tmp_path) == before


def test_raise_on_conflict_writes_no_partition(
    tmp_path: Path, make_utc_series: UtcSeriesFactory
) -> None:
    store = MeasurementStore(tmp_path, conflict_policy=RaiseOnConflict())
    store.append(make_utc_series(["2026-02-01T00:00:00Z"], [3.0], [70.0]))
    before = _digests(tmp_path)
    # The 2025 row is new and sorts first, but the 2026 conflict must stop the whole append.
    incoming = make_utc_series(["2025-06-01T00:00:00Z", "2026-02-01T00:00:00Z"], [1.0, 3.5], [1, 1])
    with pytest.raises(MeasurementConflictError):
        store.append(incoming)
    assert _digests(tmp_path) == before


def test_read_across_year_boundary_local_new_years_eve(
    store: MeasurementStore, sensor_id: SensorId
) -> None:
    # Local Europe/Prague (CET = UTC+1) half-hourly from 31 Dec 2025 23:00 to 1 Jan 2026 01:30.
    local = pd.date_range("2025-12-31 23:00", periods=6, freq="30min", tz="Europe/Prague")
    series = MeasurementSeries.from_records(
        sensor_id,
        local,
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        [90.0] * 6,
        source="MeteoData_8615620_77678271_VUT_20260101_090000.csv",
    )
    store.append(series)
    directory = store.root / "raw" / "77678271"
    # Local 23:00, 23:30, 00:00, 00:30 on New Year = 22:00..23:30 UTC on 31 Dec -> 2025.csv.
    assert (directory / "2025.csv").read_text().splitlines()[1:] == [
        "2025-12-31T22:00:00Z,0.1,90.0,,,,20260101T090000",
        "2025-12-31T22:30:00Z,0.2,90.0,,,,20260101T090000",
        "2025-12-31T23:00:00Z,0.3,90.0,,,,20260101T090000",
        "2025-12-31T23:30:00Z,0.4,90.0,,,,20260101T090000",
    ]
    assert (directory / "2026.csv").read_text().splitlines()[1:] == [
        "2026-01-01T00:00:00Z,0.5,90.0,,,,20260101T090000",
        "2026-01-01T00:30:00Z,0.6,90.0,,,,20260101T090000",
    ]
    assert store.read(sensor_id).frame[Column.TEMP].tolist() == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    window = store.read(sensor_id, "2025-12-31T23:30:00Z", "2026-01-01T00:00:00+00:00")
    assert window.frame[Column.TEMP].tolist() == [0.4, 0.5]
    local_window = store.read(sensor_id, pd.Timestamp("2026-01-01 01:00", tz="Europe/Prague"))
    assert local_window.frame[Column.TEMP].tolist() == [0.5, 0.6]
    assert store.time_range(sensor_id) == (
        pd.Timestamp("2025-12-31T22:00:00Z"),
        pd.Timestamp("2026-01-01T00:30:00Z"),
    )


def test_read_skips_partitions_outside_range(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    store.append(make_utc_series(["2025-06-01T00:00:00Z", "2026-06-01T00:00:00Z"], [1, 2], [3, 4]))
    (store.root / "raw" / "77678271" / "2025.csv").write_bytes(b"corrupt")
    later = store.read(sensor_id, start_utc="2026-01-01T00:00:00Z")
    assert later.frame[Column.TEMP].tolist() == [2.0]
    with pytest.raises(StoreFormatError, match=r"2025\.csv"):
        store.read(sensor_id)


def test_rows_are_always_ascending(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    later = ["2026-03-01T02:00:00Z", "2026-03-01T03:00:00Z"]
    earlier_and_between = ["2026-03-01T00:00:00Z", "2026-03-01T02:30:00Z"]
    store.append(make_utc_series(later, [3, 4], [1, 1]))
    store.append(make_utc_series(earlier_and_between, [1, 3.5], [1, 1]))
    lines = (store.root / "raw" / "77678271" / "2026.csv").read_text().splitlines()[1:]
    assert [line.split(",")[0] for line in lines] == [
        "2026-03-01T00:00:00Z",
        "2026-03-01T02:00:00Z",
        "2026-03-01T02:30:00Z",
        "2026-03-01T03:00:00Z",
    ]
    assert store.read(sensor_id).timestamps.is_monotonic_increasing


def test_empty_store(store: MeasurementStore, sensor_id: SensorId) -> None:
    assert store.sensors() == []
    assert store.read(sensor_id).is_empty
    assert store.time_range(sensor_id) is None
    assert store.coverage(sensor_id, INTERVAL_S) is None


def test_unknown_sensor(store: MeasurementStore, make_utc_series: UtcSeriesFactory) -> None:
    store.append(make_utc_series(["2026-01-01T00:00:00Z"], [1.0], [2.0]))
    assert store.read(OTHER).is_empty
    assert store.read(OTHER).sensor_id == OTHER
    assert store.time_range(OTHER) is None
    assert store.coverage(OTHER, INTERVAL_S) is None
    assert store.coverage(OTHER, INTERVAL_S, "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z") == 0


def test_append_empty_series_does_nothing(store: MeasurementStore, sensor_id: SensorId) -> None:
    result = store.append(MeasurementSeries.empty(sensor_id))
    assert result.counts == AppendCounts()
    assert result.files_written == ()
    assert not store.root.exists()


def test_qc_is_not_stored(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    store.append(make_utc_series(["2026-01-01T00:00:00Z"], [1.0], [2.0], qc=[32]))
    assert store.read(sensor_id).frame[Column.QC].tolist() == [0]
    header = (store.root / "raw" / "77678271" / "2026.csv").read_text().splitlines()[0]
    assert header == "timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source"


def test_sensors_lists_only_serial_directories_with_partition_files(
    store: MeasurementStore,
    make_utc_series: UtcSeriesFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store.append(make_utc_series(["2026-01-01T00:00:00Z"], [1.0], [2.0], sensor=OTHER))
    store.append(make_utc_series(["2026-01-01T00:00:00Z"], [1.0], [2.0]))
    raw = store.root / "raw"
    (raw / "notes").mkdir()
    (raw / "22222222").mkdir()
    (raw / "22222222" / ".2026.csv.abc.tmp").write_text("partial")
    (raw / "22222222" / "readme.txt").write_text("x")
    (raw / "stray.csv").write_text("x")
    with caplog.at_level(logging.WARNING, logger="sivin.storage.store"):
        assert store.sensors() == [OTHER, SensorId("77678271")]
    assert "notes" in caplog.text


def test_partition_with_foreign_rows_is_rejected(
    store: MeasurementStore, sensor_id: SensorId
) -> None:
    path = store.root / "raw" / "77678271" / "2026.csv"
    path.parent.mkdir(parents=True)
    path.write_text("timestamp_utc,temp_c,rh_pct,source\n2025-12-31T23:30:00Z,1.0,2.0,\n")
    with pytest.raises(StoreFormatError, match=r"outside partition '2026'"):
        store.read(sensor_id)


def test_coverage_hand_computed(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    # 00:00, 00:30, 01:30 (01:00 missing), 02:00 with both values missing.
    store.append(
        make_utc_series(
            [
                "2026-04-01T00:00:00Z",
                "2026-04-01T00:30:00Z",
                "2026-04-01T01:30:00Z",
                "2026-04-01T02:00:00Z",
            ],
            [1.0, math.nan, 2.0, math.nan],
            [50.0, 51.0, math.nan, math.nan],
        )
    )
    # Stored range 00:00-02:00: 5 expected samples, 3 present.
    assert store.coverage(sensor_id, INTERVAL_S) == pytest.approx(3 / 5)
    # 00:00-03:00: 7 expected, 3 present.
    end = "2026-04-01T03:00:00Z"
    assert store.coverage(sensor_id, INTERVAL_S, end_utc=end) == pytest.approx(3 / 7)
    # 00:00-00:30 at a 3600 s step: 1 expected, 2 present -> capped at 1.
    assert store.coverage(sensor_id, 3600, end_utc="2026-04-01T00:30:00Z") == 1.0


def test_coverage_rejects_bad_arguments(store: MeasurementStore, sensor_id: SensorId) -> None:
    start, end = "2026-01-02T00:00:00Z", "2026-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="positive"):
        store.coverage(sensor_id, 0)
    with pytest.raises(ValueError, match="before"):
        store.coverage(sensor_id, INTERVAL_S, start, end)


def test_naive_bounds_are_rejected(store: MeasurementStore, sensor_id: SensorId) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        store.read(sensor_id, start_utc="2026-01-01 00:00")


class _FailingCodec(CsvSeriesCodec):
    """Writes the header and a part of a row, then fails (simulated crash mid-write)."""

    def write(self, series: MeasurementSeries, stream: IO[bytes]) -> None:
        stream.write(b"timestamp_utc,temp_c,rh_pct,source\n2026-01-01T00:")
        raise OSError("disk full (injected)")


def test_failed_write_leaves_old_file_intact(
    tmp_path: Path, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    MeasurementStore(tmp_path).append(make_utc_series(["2026-01-01T00:00:00Z"], [1.0], [2.0]))
    before = _digests(tmp_path)
    failing = MeasurementStore(tmp_path, codec=_FailingCodec())
    with pytest.raises(OSError, match="injected"):
        failing.append(make_utc_series(["2026-01-01T00:30:00Z"], [1.5], [2.5]))
    assert _digests(tmp_path) == before
    assert MeasurementStore(tmp_path).read(sensor_id).frame[Column.TEMP].tolist() == [1.0]


def test_failed_first_write_creates_no_file(
    tmp_path: Path, make_utc_series: UtcSeriesFactory
) -> None:
    failing = MeasurementStore(tmp_path, codec=_FailingCodec())
    with pytest.raises(OSError, match="injected"):
        failing.append(make_utc_series(["2026-01-01T00:30:00Z"], [1.5], [2.5]))
    assert _digests(tmp_path) == {}


def test_header_only_partition_file_reads_as_empty(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    store.append(make_utc_series(["2026-01-01T00:00:00Z"], [1.0], [2.0]))
    header_only = "timestamp_utc,temp_c,rh_pct,source\n"
    (store.root / "raw" / "77678271" / "2025.csv").write_text(header_only)
    assert len(store.read(sensor_id)) == 1
    assert store.time_range(sensor_id) == (
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:00:00Z"),
    )


def test_missing_value_in_a_reimport_keeps_the_stored_value(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    # A truncated last row of an export: temperature missing. Default policy PreferNewest.
    store.append(make_utc_series(["2026-05-01T00:00:00Z"], [12.3], [80.0], "old.csv"))
    before = _digests(store.root)
    result = store.append(make_utc_series(["2026-05-01T00:00:00Z"], [math.nan], [80.0], "new"))
    assert result.counts == AppendCounts(ignored_missing_values=1)
    assert result.files_written == ()
    assert _digests(store.root) == before
    assert store.read(sensor_id).frame[Column.TEMP].tolist() == [12.3]


def test_missing_values_are_filled_column_by_column(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    store.append(make_utc_series(["2026-05-01T01:00:00Z"], [math.nan], [70.0], "old.csv"))
    result = store.append(make_utc_series(["2026-05-01T01:00:00Z"], [11.0], [math.nan], "new.csv"))
    assert result.counts == AppendCounts(filled_values=1, ignored_missing_values=1)
    lines = (store.root / "raw" / "77678271" / "2026.csv").read_text().splitlines()
    # "new.csv" carries no export time: stored as h + 12 digits of SHA-256("new.csv").
    assert lines[1:] == ["2026-05-01T01:00:00Z,11.0,70.0,,,,h" + NEW_CSV_SHA256[:12]]
    assert store.read(sensor_id).frame[Column.RH].tolist() == [70.0]


def test_backfill_of_an_older_export_needs_prefer_existing(
    tmp_path: Path, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    # "Newest" is import order: the older export appended last wins under PreferNewest.
    newer = make_utc_series(["2026-01-01T00:00:00Z"], [4.2], [60.0], "export_2026-02.csv")
    older = make_utc_series(["2026-01-01T00:00:00Z"], [4.0], [60.0], "data.xlsx")
    by_import_order = MeasurementStore(tmp_path / "newest", conflict_policy=PreferNewest())
    by_import_order.append(newer)
    by_import_order.append(older)
    assert by_import_order.read(sensor_id).frame[Column.TEMP].tolist() == [4.0]
    backfill = MeasurementStore(tmp_path / "existing", conflict_policy=PreferExisting())
    backfill.append(newer)
    backfill.append(older)
    assert backfill.read(sensor_id).frame[Column.TEMP].tolist() == [4.2]


def test_dropped_qc_flags_are_logged_with_counts_per_flag(
    store: MeasurementStore,
    make_utc_series: UtcSeriesFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    times = ["2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z", "2026-01-01T01:00:00Z"]
    with caplog.at_level(logging.INFO, logger="sivin.storage.store"):
        store.append(make_utc_series(times, [1, 2, 3], [4, 5, 6], qc=[256, 256 | 4, 0]))
    (record,) = [r for r in caplog.records if "dropped" in r.getMessage()]
    assert record.levelno == logging.INFO
    assert record.getMessage() == (
        "Sensor 77678271: QC flags are not stored in raw files and were dropped: "
        "SPIKE on 1 row(s), MANUAL_EXCLUDE on 2 row(s)."
    )


def test_dropped_parser_flags_are_debug_only(
    store: MeasurementStore,
    make_utc_series: UtcSeriesFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    times = ["2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z"]
    with caplog.at_level(logging.DEBUG, logger="sivin.storage.store"):
        store.append(make_utc_series(times, [1, float("nan")], [4, 5], qc=[128, 1]))
    (record,) = [r for r in caplog.records if "dropped" in r.getMessage()]
    assert record.levelno == logging.DEBUG


def test_no_qc_warning_without_flags(
    store: MeasurementStore,
    make_utc_series: UtcSeriesFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="sivin.storage.store"):
        store.append(make_utc_series(["2026-01-01T00:00:00Z"], [1.0], [2.0]))
    assert caplog.messages == []


class _WriterFailingOnSecondFile(AtomicFileWriter):
    """Simulates a crash after the first partition file of an append was written."""

    def __init__(self) -> None:
        self.calls = 0

    @contextmanager
    def open(self, target: Path) -> Iterator[IO[bytes]]:
        self.calls += 1
        if self.calls == 2:
            raise OSError("crash between partitions (injected)")
        with super().open(target) as stream:
            yield stream


def test_retry_after_crash_between_partitions_completes_the_append(
    tmp_path: Path, make_utc_series: UtcSeriesFactory
) -> None:
    times = ["2025-06-01T00:00:00Z", "2026-06-01T00:00:00Z", "2027-06-01T00:00:00Z"]
    series = make_utc_series(times, [1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
    clean = MeasurementStore(tmp_path / "clean")
    clean.append(series)
    crashing = MeasurementStore(tmp_path / "crash", writer=_WriterFailingOnSecondFile())
    with pytest.raises(OSError, match="injected"):
        crashing.append(series)
    written = sorted(path.name for path in (tmp_path / "crash").rglob("*") if path.is_file())
    assert written == ["2025.csv"]
    retry = MeasurementStore(tmp_path / "crash").append(series)
    # The retry under-reports: the 2025 row counts as identical, not new.
    assert retry.counts == AppendCounts(new_rows=2, identical_skipped=1)
    assert _digests(tmp_path / "crash") == _digests(tmp_path / "clean")


def test_recorded_conflicts_are_capped_per_append_across_partitions(
    tmp_path: Path, make_utc_series: UtcSeriesFactory
) -> None:
    store = MeasurementStore(tmp_path, max_recorded_conflicts=2)
    times = ["2025-12-31T23:30:00Z", "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z"]
    store.append(make_utc_series(times, [1.0, 1.0, 1.0], [5.0, 5.0, 5.0]))
    result = store.append(make_utc_series(times, [2.0, 2.0, 2.0], [5.0, 5.0, 5.0]))
    assert result.counts.conflicting_values == 3
    assert [d.conflict.timestamp_utc for d in result.conflicts] == [
        pd.Timestamp(times[0]),
        pd.Timestamp(times[1]),
    ]
