"""The measurement store: canonical measurements as flat files, without a database.

Layout (MIGRATION_PLAN §2.5)::

    <root>/raw/<sensor_id>/<partition key><suffix>     e.g. data/raw/77678271/2026.csv
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries, TimestampLike
from sivin.storage.atomic import AtomicFileWriter
from sivin.storage.codec import CsvSeriesCodec, SeriesCodec
from sivin.storage.conflicts import ConflictDecision, ConflictPolicy, PreferNewest
from sivin.storage.errors import StoreFormatError
from sivin.storage.merge import DEFAULT_MAX_RECORDED_CONFLICTS, AppendCounts, SeriesMerger
from sivin.storage.partitioning import Partitioning, YearPartitioning
from sivin.storage.source import ExportSourceIds

logger = logging.getLogger(__name__)

RAW_DIR: Final = "raw"
"""Directory below the store root that holds the measurement files."""


@dataclass(frozen=True, slots=True)
class AppendResult:
    """Outcome of :meth:`MeasurementStore.append`.

    Attributes
    ----------
    sensor_id : SensorId
        The sensor appended to.
    counts : AppendCounts
        New and identical rows; filled, ignored, conflicting and replaced values.
    files_written : tuple of pathlib.Path
        Partition files that were created or replaced; empty when nothing changed.
    conflicts : tuple of ConflictDecision
        The first ``max_recorded_conflicts`` conflicts with both values and the decision, in
        time order; ``counts.conflicting_values`` tells how many there were in total.
    """

    sensor_id: SensorId
    counts: AppendCounts = field(default_factory=AppendCounts)
    files_written: tuple[Path, ...] = ()
    conflicts: tuple[ConflictDecision, ...] = ()


@dataclass(frozen=True, slots=True)
class _PendingWrite:
    path: Path
    series: MeasurementSeries


class MeasurementStore:
    """Flat-file store of the canonical measurements of all sensors.

    Appending is idempotent: rows are deduplicated on ``timestamp_utc``, identical rows are
    skipped, and a file is only rewritten when its data change. Every file is replaced
    atomically. QC flags are not stored; :meth:`read` returns ``qc = 0``. The ``source`` of a
    row is stored as the short identifier of its export (:class:`ExportSourceIds`, owner
    decision 2026-10-05); full file names in older files are shortened when read.

    Parameters
    ----------
    root : pathlib.Path
        Store directory (``data/`` in production); measurement files live in ``root/raw``.
    codec : SeriesCodec, optional
        File format; :class:`CsvSeriesCodec` by default.
    partitioning : Partitioning, optional
        Split of a sensor's rows into files; :class:`YearPartitioning` (UTC year) by default.
    conflict_policy : ConflictPolicy, optional
        Decides values that conflict with stored ones; :class:`PreferNewest` by default.
    writer : AtomicFileWriter, optional
        Writes files atomically.
    max_recorded_conflicts : int, optional
        Conflicts kept in :attr:`AppendResult.conflicts` per append (and logged one by one per
        partition file).
    source_ids : ExportSourceIds, optional
        Shortens the ``source`` of incoming and stored rows to export identifiers.
    """

    __slots__ = ("_codec", "_merger", "_partitioning", "_root", "_source_ids", "_writer")

    def __init__(
        self,
        root: Path,
        codec: SeriesCodec | None = None,
        partitioning: Partitioning | None = None,
        conflict_policy: ConflictPolicy | None = None,
        writer: AtomicFileWriter | None = None,
        max_recorded_conflicts: int = DEFAULT_MAX_RECORDED_CONFLICTS,
        source_ids: ExportSourceIds | None = None,
    ) -> None:
        self._root = root
        self._source_ids = source_ids if source_ids is not None else ExportSourceIds()
        self._codec = codec if codec is not None else CsvSeriesCodec()
        self._partitioning = partitioning if partitioning is not None else YearPartitioning()
        policy = conflict_policy if conflict_policy is not None else PreferNewest()
        self._merger = SeriesMerger(policy, max_recorded_conflicts)
        self._writer = writer if writer is not None else AtomicFileWriter()

    @property
    def root(self) -> Path:
        """The store directory."""
        return self._root

    def append(self, series: MeasurementSeries) -> AppendResult:
        """Merge ``series`` into the store.

        All partitions are merged in memory first, so a refused conflict
        (:class:`~sivin.storage.conflicts.RaiseOnConflict`) writes nothing. Each changed file is
        then replaced atomically. If writing one file fails, files written before it keep their
        new content; repeating the append completes the rest and gives the same bytes as one
        clean append, but its counts report the rows already written as identical. The caller
        must therefore record the failed attempt (e.g. in ``RunRecord.failures``).

        Parameters
        ----------
        series : MeasurementSeries
            Measurements of one sensor. Its ``qc`` column is not stored; set flags are logged
            as a warning with a count per flag. Its ``source`` values (export file names) are
            stored as short export identifiers.

        Returns
        -------
        AppendResult
            Counts, the files written and the recorded conflicts.

        Raises
        ------
        MeasurementConflictError
            If the conflict policy refuses a conflict.
        StoreFormatError
            If an existing file of an affected partition is malformed.
        """
        if series.is_empty:
            return AppendResult(series.sensor_id)
        _warn_dropped_flags(series)
        series = self._source_ids.shorten(series)
        counts = AppendCounts()
        conflicts: list[ConflictDecision] = []
        pending: list[_PendingWrite] = []
        for key, part in self._partitions_of(series):
            path = self._file(series.sensor_id, key)
            outcome = self._merger.merge(self._read_partition(series.sensor_id, key, path), part)
            counts += outcome.counts
            conflicts += outcome.conflicts
            if outcome.counts.changes_data:
                pending.append(_PendingWrite(path, outcome.series))
        for write in pending:
            with self._writer.open(write.path) as stream:
                self._codec.write(write.series, stream)
        logger.info(
            "Sensor %s: %s; %d file(s) written.",
            series.sensor_id,
            ", ".join(f"{name} {count}" for name, count in counts.to_dict().items()),
            len(pending),
        )
        recorded = tuple(conflicts[: self._merger.max_recorded_conflicts])
        return AppendResult(
            series.sensor_id, counts, tuple(write.path for write in pending), recorded
        )

    def read(
        self,
        sensor_id: SensorId,
        start_utc: TimestampLike | None = None,
        end_utc: TimestampLike | None = None,
    ) -> MeasurementSeries:
        """Read the stored rows of one sensor, across partition files.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.
        start_utc, end_utc : timestamp, optional
            Timezone-aware inclusive bounds; unbounded when omitted.

        Returns
        -------
        MeasurementSeries
            Rows in ascending time order with a ``source`` column (short export identifiers,
            ``""`` when unknown) and ``qc = 0``; empty for an unknown sensor or an empty
            range.

        Raises
        ------
        ValueError
            If a bound is naive (has no timezone).
        StoreFormatError
            If a file is malformed.
        """
        start = _bound(start_utc, "start_utc", pd.Timestamp.min)
        end = _bound(end_utc, "end_utc", pd.Timestamp.max)
        parts = [
            self._read_partition(sensor_id, key, path)
            for key, path in self._partition_files(sensor_id)
            if self._partitioning.overlaps(key, start, end)
        ]
        frames = [part.frame for part in parts if not part.is_empty]
        if not frames:
            return MeasurementSeries.empty(sensor_id)
        frame = pd.concat(frames, ignore_index=True)
        times = frame[Column.TIMESTAMP]
        return MeasurementSeries(sensor_id, frame.loc[(times >= start) & (times <= end)])

    def sensors(self) -> list[SensorId]:
        """List the sensors with at least one partition file.

        Returns
        -------
        list of SensorId
            Sorted by serial number. Directories whose name is not a serial are skipped with a
            warning.
        """
        raw = self._root / RAW_DIR
        if not raw.is_dir():
            return []
        found = []
        for directory in sorted(path for path in raw.iterdir() if path.is_dir()):
            try:
                sensor_id = SensorId(directory.name)
            except ValueError:
                logger.warning("Ignoring %s: not a sensor serial number.", directory)
                continue
            if self._partition_files(sensor_id):
                found.append(sensor_id)
        return found

    def time_range(self, sensor_id: SensorId) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Return the first and last stored timestamp of a sensor.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.

        Returns
        -------
        tuple of pandas.Timestamp or None
            First and last ``timestamp_utc`` (UTC), or ``None`` if nothing is stored.
        """
        timestamps = [
            self._read_partition(sensor_id, key, path).timestamps
            for key, path in self._partition_files(sensor_id)
        ]
        non_empty = [times for times in timestamps if not times.empty]
        if not non_empty:
            return None
        return non_empty[0].iloc[0], non_empty[-1].iloc[-1]

    def coverage(
        self,
        sensor_id: SensorId,
        expected_interval_s: float,
        start_utc: TimestampLike | None = None,
        end_utc: TimestampLike | None = None,
    ) -> float | None:
        """Share of expected samples that are stored with at least one value.

        The expected count is ``floor((end - start) / expected_interval_s) + 1``; a stored row
        counts when ``temp_c`` or ``rh_pct`` is present. The result is capped at 1.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.
        expected_interval_s : float
            Nominal sampling interval in seconds (``time.expected_interval_s``).
        start_utc, end_utc : timestamp, optional
            Inclusive bounds; the stored :meth:`time_range` when omitted.

        Returns
        -------
        float or None
            Coverage 0-1 (dimensionless), or ``None`` when a bound is omitted and nothing is
            stored.

        Raises
        ------
        ValueError
            If ``expected_interval_s`` is not positive, a bound is naive, or ``end < start``.
        """
        if expected_interval_s <= 0:
            raise ValueError(f"expected_interval_s must be positive, got {expected_interval_s}.")
        stored_range = self.time_range(sensor_id)
        if stored_range is None and (start_utc is None or end_utc is None):
            return None
        first, last = stored_range or (pd.Timestamp.min, pd.Timestamp.max)
        start = _bound(start_utc, "start_utc", first)
        end = _bound(end_utc, "end_utc", last)
        if end < start:
            raise ValueError(f"end_utc {end} is before start_utc {start}.")
        frame = self.read(sensor_id, start, end).frame
        present = int((frame[Column.TEMP].notna() | frame[Column.RH].notna()).sum())
        expected = int(np.floor((end - start).total_seconds() / expected_interval_s)) + 1
        return min(1.0, present / expected)

    def _partitions_of(self, series: MeasurementSeries) -> list[tuple[str, MeasurementSeries]]:
        frame = series.frame
        keys = self._partitioning.keys_of(frame[Column.TIMESTAMP])
        return [
            (str(key), MeasurementSeries(series.sensor_id, frame.loc[keys == key]))
            for key in sorted(keys.unique())
        ]

    def _partition_files(self, sensor_id: SensorId) -> list[tuple[str, Path]]:
        directory = self._root / RAW_DIR / str(sensor_id)
        if not directory.is_dir():
            return []
        suffix = self._codec.file_suffix
        files = [
            (path.name.removesuffix(suffix), path)
            for path in directory.iterdir()
            if path.is_file() and path.name.endswith(suffix)
        ]
        return sorted((key, path) for key, path in files if self._partitioning.is_key(key))

    def _file(self, sensor_id: SensorId, key: str) -> Path:
        return self._root / RAW_DIR / str(sensor_id) / f"{key}{self._codec.file_suffix}"

    def _read_partition(self, sensor_id: SensorId, key: str, path: Path) -> MeasurementSeries:
        if not path.exists():
            return MeasurementSeries.empty(sensor_id)
        with path.open("rb") as stream:
            series = self._codec.read(stream, sensor_id, str(path))
        if not series.is_empty:
            keys = self._partitioning.keys_of(series.timestamps)
            if bool((keys != key).any()):
                raise StoreFormatError(f"{path}: holds rows outside partition {key!r}.")
        return self._source_ids.shorten(series)


def _warn_dropped_flags(series: MeasurementSeries) -> None:
    """Log a warning with a count per flag when the series carries QC flags (not stored)."""
    flags = series.frame[Column.QC].to_numpy()
    if not flags.any():
        return
    per_flag = {str(flag.name): int(((flags & flag.value) != 0).sum()) for flag in QcFlag}
    logger.warning(
        "Sensor %s: QC flags are not stored in raw files and were dropped: %s.",
        series.sensor_id,
        ", ".join(f"{name} on {count} row(s)" for name, count in per_flag.items() if count),
    )


def _bound(value: TimestampLike | None, name: str, default: pd.Timestamp) -> pd.Timestamp:
    """Return an aware UTC bound, or ``default`` (made UTC) when ``value`` is ``None``."""
    if value is None:
        return default if default.tz is not None else default.tz_localize("UTC")
    timestamp = pd.Timestamp(value)
    if timestamp.tz is None:
        raise ValueError(f"'{name}' must be timezone-aware, got {value!r}.")
    return timestamp.tz_convert("UTC")
