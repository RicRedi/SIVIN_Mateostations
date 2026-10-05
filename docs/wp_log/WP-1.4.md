# WP-1.4 — Measurement store

## Summary

`sivin.storage` stores canonical measurements as flat files without a database:
`<root>/raw/<sensor_id>/<YYYY>.csv` (UTC-year partitions) and `<root>/runs/<YYYY-MM-DD>.jsonl`
run logs. `MeasurementStore.append` merges imports on `timestamp_utc`. Identical rows are
skipped and conflicting rows are decided by a registered `ConflictPolicy` (`PreferNewest`
default, `PreferExisting`, `RaiseOnConflict`) and logged with both values. A file is rewritten
only when its data change, and always atomically (temporary file + `os.replace`).
`CsvSeriesCodec` writes an exactly specified, byte-stable CSV with lossless shortest-round-trip
decimals. QC flags are not stored. `RunLog` appends frozen `RunRecord`s as JSON Lines.
`docs/storage.md` documents the layout, format, merge semantics, growth and the Parquet path.

## Changed files

- `src/sivin/storage/__init__.py` (re-exports), `store.py` (`MeasurementStore`,
  `AppendResult`), `codec.py` (`SeriesCodec` ABC, `CsvSeriesCodec`), `partitioning.py`
  (`Partitioning` ABC, `YearPartitioning`, `partitioning_registry`), `conflicts.py`
  (`ConflictPolicy` ABC, `PreferNewest`, `PreferExisting`, `RaiseOnConflict`, `RowConflict`,
  `StoredRow`, `conflict_policy_registry`), `merge.py` (`SeriesMerger`, `AppendCounts`,
  `MergeOutcome`), `atomic.py` (`AtomicFileWriter`), `runlog.py` (`RunLog`, `RunRecord`),
  `config.py` (`StorageConfig`, `build_store`), `registry.py` (`NamedRegistry`), `errors.py`
  (`StoreError`, `StoreFormatError`, `MeasurementConflictError`).
- `tests/storage/{conftest,test_store,test_codec,test_merge,test_atomic,test_partitioning,test_runlog,test_config,test_registry}.py`.
- `docs/storage.md`, `docs/wp_log/WP-1.4.md`.

## Public API

```python
# sivin.storage
MeasurementStore(root: Path, codec=None, partitioning=None, conflict_policy=None, writer=None)
    .append(series: MeasurementSeries) -> AppendResult
    .read(sensor_id, start_utc=None, end_utc=None) -> MeasurementSeries   # inclusive, aware
    .sensors() -> list[SensorId]
    .time_range(sensor_id) -> tuple[pd.Timestamp, pd.Timestamp] | None
    .coverage(sensor_id, expected_interval_s, start_utc=None, end_utc=None) -> float | None
    .root -> Path
AppendResult(sensor_id, counts: AppendCounts, files_written: tuple[Path, ...])  # frozen
AppendCounts(new_rows, identical_skipped, conflicting_rows, replaced_rows)       # frozen, +
ConflictPolicy (ABC: keeps_incoming(RowConflict) -> bool); PreferNewest | PreferExisting |
    RaiseOnConflict; conflict_policy_registry ("prefer_newest", "prefer_existing", "raise")
Partitioning (ABC: keys_of, is_key, bounds, overlaps); YearPartitioning; partitioning_registry
SeriesCodec (ABC: file_suffix, write(series, IO[bytes]), read(IO[bytes], sensor_id, origin))
CsvSeriesCodec; AtomicFileWriter.open(target) -> context manager yielding IO[bytes]
RunLog(root).append(RunRecord) -> Path; .read(day) -> list[RunRecord]; .path_for(day)
RunRecord(started_at, finished_at, files=(), appends={SensorId: AppendCounts},
          validation_issues={str: int}, failures=())                              # frozen
StorageConfig(conflict_policy="prefer_newest", partitioning="year"); build_store(root, config)
StoreError > StoreFormatError, MeasurementConflictError
```

Proposed wiring (for the integration WP): configuration section `storage:` with
`StorageConfig` (store directory stays `paths.data_dir`); CLI command
`sivin store status` (sensors, time range and coverage per sensor). The pipeline creates the
store with `build_store(paths.resolve(config.paths.data_dir), config.storage)`.

## How it was verified

All commands in `/home/user/wt/wp-1.4` (ruff 0.16.10, mypy 2.4.0, Python 3.12, pandas 3.0.6,
numpy 2.5.3):

- `make lint` → `All checks passed!`, `51 files already formatted`.
- `make type` → `Success: no issues found in 30 source files`.
- `make test` → `276 passed` (95 of them in `tests/storage`).
- `make cov` → every `src/sivin/storage/*.py` at 100 % (statements and branches; 580 statements,
  98 branches in the package); `TOTAL 1405 0 276 0 100%`.

Acceptance criteria → tests:

- Double import = no file change: `test_double_import_leaves_files_byte_identical` (SHA-256 of
  every file before and after, 200 rows across two years),
  `test_reimport_under_another_file_name_changes_nothing`.
- Overlap of two exports: `test_two_overlapping_exports_merge` (rows 0–47 and 24–71 → 72 rows,
  24 new, 24 identical), `test_stored_values_do_not_depend_on_import_order`.
- Read across the year boundary: `test_read_across_year_boundary_local_new_years_eve` (local
  Prague 23:00–01:30 on New Year's Eve → exact lines of `2025.csv` and `2026.csv`, reads with
  UTC and local bounds).
- Write survives interruption: `test_failed_write_leaves_old_file_intact` (codec writes half a
  row, then raises), `test_failed_first_write_creates_no_file`, `test_atomic.py` (exception in
  the body, failing `os.replace`).
- Conflict policies, logging of both values and the log cap: `test_merge.py`, store-level
  `test_conflict_*`, `test_raise_on_conflict_writes_no_partition` (nothing written in any
  partition).
- Empty store, unknown sensor, ascending order, QC not stored, codec round trip with NaN and
  sources containing commas, quotes, newlines and non-ASCII, lossless floats (200 values from
  a seeded RNG), exact file bytes, malformed-file rejection: `test_store.py`, `test_codec.py`.

## What did not work / what was not verified

- **No real export was available** (Q1): the 0.1 °C / 0.1 % source resolution is an assumption
  from the legacy scripts. The number format is lossless for any precision, so this only
  affects how the files look.
- Durability after a power loss: the temporary file is `fsync`-ed, but the directory is not,
  so on Linux a rename right before a power cut may be lost (the old file stays, which is
  still consistent). Not tested; there is no way to test it here.
- Only tested on Linux. On Windows, `os.replace` fails if another process has the target open;
  production runs on Linux (GitHub Actions).
- One writer at a time is assumed, not enforced (no lock file). The scheduled workflow runs one
  pipeline at a time.
- Performance was not measured on large data; `time_range` and `coverage` read every year file
  of the sensor (a few files per sensor today).

## Deviations

- `MeasurementStore` is about 260 lines including docstrings (about 110 lines of code), above
  the ~200-line signal of §1.2. Merging, encoding, partitioning and atomic writing are already
  separate classes; what is left is the public API plus three small private helpers.
- Added `SeriesCodec` (ABC) next to `CsvSeriesCodec` and a small generic `NamedRegistry`, used
  by the two configurable extension points (conflict policy, partitioning).
- `read` always returns a `source` column (empty string where unknown) instead of omitting it.
- The plan says "deduplicate on `sensor_id + timestamp_utc`"; the sensor is given by the
  directory, so deduplication is on `timestamp_utc` within the sensor's files, which is the
  same thing.

## Out of scope

- `src/sivin/core/flags.py`, `QcFlag` docstring: "persisted in the measurement store". Raw
  store files hold no flags (this WP's brief). Proposal: "persisted in derived data and the
  static site data".
- `sivin.core.schema.MeasurementSeries` has no `concat`; the store concatenates frames and
  validates them with the constructor. Proposal: `MeasurementSeries.concat(parts)` in core.
- MIGRATION_PLAN §2.5 estimates 0.5 MB per sensor and year. That holds without the `source`
  column. With full export file names in `source` it is about 1.45 MB (see
  `docs/storage.md`). Proposal: update the estimate, or decide the question below.
- MIGRATION_PLAN §4 says CLI and configuration wiring is done by WP-3.2; this WP's brief names
  WP-1.7. One of the two should be corrected.
- `.gitignore` ignores `/data/` on `main`. The pipeline (WP-4.1) must commit `data/` on the
  `data` branch despite that rule (for example with `git add -f`, or with a branch-specific
  ignore). Mentioned in `docs/storage.md`; `.gitignore` is unchanged.

## Open questions for the owner

1. Should `source` hold the full export file name (about 1.45 MB per sensor-year, simple
   provenance) or something shorter, such as the export timestamp (about 0.8 MB)? The code
   stores whatever the parser puts in `MeasurementSeries.source`.
2. Default conflict policy `prefer_newest` (the newer import wins), as in the plan. Should a
   conflict also be listed in the run log, not only counted (`conflicting_rows`) and logged?
   Today only the counts go into `RunRecord.appends`.

## Review

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
