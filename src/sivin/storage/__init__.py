"""Measurement store on top of plain CSV files (WP-1.4, MIGRATION_PLAN §2.5).

``MeasurementStore`` keeps the canonical measurements of every sensor as
``<root>/raw/<sensor_id>/<YYYY>.csv``; ``RunLog`` appends run summaries to
``<root>/runs/<YYYY-MM-DD>.jsonl``. The file format is specified in ``docs/storage.md``.
"""

from sivin.storage.atomic import AtomicFileWriter
from sivin.storage.codec import CsvSeriesCodec, SeriesCodec
from sivin.storage.config import StorageConfig, build_store
from sivin.storage.conflicts import (
    ConflictPolicy,
    PreferExisting,
    PreferNewest,
    RaiseOnConflict,
    RowConflict,
    StoredRow,
    conflict_policy_registry,
)
from sivin.storage.errors import MeasurementConflictError, StoreError, StoreFormatError
from sivin.storage.merge import AppendCounts, MergeOutcome, SeriesMerger
from sivin.storage.partitioning import Partitioning, YearPartitioning, partitioning_registry
from sivin.storage.runlog import RunLog, RunRecord
from sivin.storage.store import AppendResult, MeasurementStore

__all__ = [
    "AppendCounts",
    "AppendResult",
    "AtomicFileWriter",
    "ConflictPolicy",
    "CsvSeriesCodec",
    "MeasurementConflictError",
    "MeasurementStore",
    "MergeOutcome",
    "Partitioning",
    "PreferExisting",
    "PreferNewest",
    "RaiseOnConflict",
    "RowConflict",
    "RunLog",
    "RunRecord",
    "SeriesCodec",
    "SeriesMerger",
    "StorageConfig",
    "StoreError",
    "StoreFormatError",
    "StoredRow",
    "YearPartitioning",
    "build_store",
    "conflict_policy_registry",
    "partitioning_registry",
]
