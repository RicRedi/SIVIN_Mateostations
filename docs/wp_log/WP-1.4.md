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

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent review agent, against the worker brief, MIGRATION_PLAN §2.5 and §4 WP-1.4.

### Gates observed

In `/home/user/wt/wp-1.4`: `make lint` → `All checks passed!`, `51 files already formatted`;
`make type` → `Success: no issues found in 30 source files`; `make test` → `276 passed`;
`make cov` → every `src/sivin/storage/*.py` at 100 % (statements and branches),
`TOTAL 1405 0 276 0 100%`. Scope: `git diff --stat bcde7d9...HEAD` touches only
`src/sivin/storage/**`, `tests/storage/**`, `docs/storage.md` and this note. No shared file
changed. No `type: ignore`; `Any` is used only for the JSON mapping in `runlog.py`.

### Verified with throwaway scripts (outside the repo, `/tmp/claude-0/review-1.4/`)

- Crash between two partitions of one append (writer raises on the 2nd of 3 files): `2025.csv`
  was written, `2026.csv` and `2027.csv` were not, and no temp file was left. Retrying the same
  append wrote the two missing files (`new_rows=2, identical_skipped=1`). The result was
  byte-identical (SHA-256) to a clean single append. Recoverable and idempotent on retry.
- Float round trip over 29 006 values (normal, ±1e-5, ±1e12, 0.1-rounded, `0.0`, `-0.0`,
  `5e-324`, `DBL_MAX`, `0.1+0.2`) through store → read: bit-exact (`np.array_equal`), and
  codec read → write reproduced the file byte for byte. The sign of `-0.0` is preserved.
- Sub-second timestamps (`.123456789`, `.5`, `.000001`) are written trimmed, read back
  ns-exact, and re-append leaves the bytes unchanged.
- Byte stability: the same series appended 3× more, mixed with an overlapping identical
  re-export under another source name, gave an unchanged SHA-256.
- Sources `"a\rb"`, `" x "`, `'č,"q"\n'` round-trip exactly.
- Malformed files: BOM, trailing blank line, `1`, `1e5`, `+1.0`, `.5`, `nan`, `2026-02-30`,
  `+01:00` offset, git conflict markers, duplicate timestamps and an empty file all raise
  `StoreFormatError`, and the file is never overwritten. CRLF files are accepted and
  normalised to LF on the next rewrite, without data loss.
- Size: 17 280 rows with 0.1-resolution values give 0.55 MB with an empty `source`, and
  1.44 MB with full export names that change every 2 rows (an hourly run brings about 2 new
  samples). An export timestamp `YYYYMMDDTHHMMSS` gives 0.81 MB, and an integer run id gives
  0.61 MB. Compressed with zlib (as git stores blobs), these are 0.14 / 0.24 / 0.20 / 0.17 MB.
  The estimate in `docs/storage.md` is correct.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| blocker | src/sivin/storage/merge.py:229, :175; src/sivin/storage/conflicts.py:114 | A missing value overwrites a real one. Stored `temp_c=12.3, rh_pct=80.0`, then an import with `temp_c=NaN, rh_pct=80.0` under the default `PreferNewest` leaves `temp_c=NaN` in the file (`conflicting_rows=1, replaced_rows=1`). Mixed case: stored `(NaN, 70.0)` and incoming `(11.0, NaN)` stores `(11.0, NaN)`, so the humidity 70.0 is lost. The store is the only copy of the history, so this is silent data loss: only a WARNING line in an ephemeral CI log remains, plus git history. It is also likely in practice, because a truncated or partial last row of a provider export is a NaN row. Fix: merge column by column. A NaN against a value is not a conflict: the present value is kept or filled in, and this is counted separately (e.g. `filled_values`). Only two *present*, different values are a `RowConflict` for the policy. Add tests for both cases at merger and store level, and correct `docs/storage.md:84` ("A missing value against a present value is a conflict"). | open |
| minor | src/sivin/storage/conflicts.py:114-133; docs/storage.md:89 | `PreferNewest` means "the last *appended* row wins", not "the newer *source* wins" (MIGRATION_PLAN §4: "vyhrává novější zdroj"). A later back-fill of an older export, such as the legacy hand-merged `data.xlsx`, would overwrite values from newer exports. Fix: document that "newest" = import order and that back-fills must use `prefer_existing`. Better: give `RowConflict` an export time, so a policy can compare sources. | open |
| minor | src/sivin/storage/store.py:128-129; docs/storage.md:67-70 | QC is dropped with only a DEBUG log, and the docs say QC "is recomputed from the raw values". That is false for `MANUAL_EXCLUDE` (bit 256), an owner decision that cannot be derived from raw values. A caller that sets it before `append` loses it silently. Fix: log at WARNING (or raise) when non-recomputable bits such as `MANUAL_EXCLUDE` are present, and correct the docs to say where manual exclusions live (see the proposal below). | open |
| minor | tests/storage/test_store.py (missing) | The partial multi-partition append and its retry are only described in the docstring and docs, not tested. The reviewer verified the behaviour (see above). Add a test: the writer fails on the 2nd file, then a retry gives bytes identical to a clean append. Also note that the counts of a retry under-report (`identical_skipped` instead of `new_rows`), so the pipeline must record the failed first attempt in `RunRecord.failures`. | open |
| minor | src/sivin/storage/merge.py:187-206; src/sivin/storage/runlog.py | Conflicts, and so overwritten values, are only in log lines; the run log has counts only. Answer to owner Q2: yes, persist them. Add a bounded `conflicts` list (sensor, timestamp, stored, incoming, decision) to `AppendResult` and `RunRecord`, so the durable `data` branch says which value was replaced. | open |
| nit | src/sivin/storage/conflicts.py:114/118, src/sivin/storage/partitioning.py:189/197 | The registry name is given twice, in `register("…")` and in `name: ClassVar`, and nothing checks that the two are equal. Derive one from the other or assert equality in `register`. | open |
| nit | src/sivin/storage/registry.py | `NamedRegistry` is a generic registry living in `storage`, next to the domain `IndexRegistry` in analytics. Propose moving it to `sivin.core` for the other extension points (QC checks, aligners). This is out of this WP's scope; mention it as a proposal. | open |
| nit | src/sivin/storage/runlog.py:171-177 | A crash during a run-log line write leaves a partial line. The next append then continues that line, and `read(day)` raises for the whole day. Consider starting each append with a newline when the file does not end with `\n`, or skipping and reporting bad lines. | open |

### Owner question 1 (`source` column), reviewer recommendation

Keep a per-row `source`, which is useful when a conflict needs explaining, but make it short.
Store the export timestamp, or a short export id from the parser, rather than the full file
name, and keep the full file name in `RunRecord.files`, where the id can be resolved. The
measured cost: 0.81 MB raw (0.20 MB compressed) instead of 1.44 MB (0.24 MB) per
sensor-year. Git storage hardly differs. The difference is in the working tree and the
checkout in CI: for example 30 sensors × 10 years ≈ 240 MB instead of 430 MB. An export
timestamp also gives the export time that a true "newer source wins" policy needs (finding 2).
MIGRATION_PLAN §2.5 should then say ≈ 0.8 MB per sensor-year.

### Where manual exclusions should live (proposal)

Manual exclusions belong with the configuration, not with the bot-written raw data. Suggested
home: a human-edited, PR-reviewed file on `main`, e.g. `config/manual_exclusions.yaml`, or a
section of the sensor registry. Each entry has `sensor_id`, `start_utc`, `end_utc` (inclusive,
aware), `variables` (`temp_c`/`rh_pct`/both), `reason`, `decided_by` and `decided_on`. A
registered `ManualExclusionCheck` in the WP-1.5 QC pipeline applies these entries at build
time, so they survive any re-import or re-download. Exclusions given as intervals rather than
row ids also cover rows imported later. The `data` branch stays raw-only, so "qc dropped on
write" is then acceptable. The owner should assign this to WP-1.5 or WP-1.7.

### Deviations assessment

- `MeasurementStore` at about 260 lines: acceptable. Responsibilities are already split
  (codec, partitioning, merger, writer), and what is left is readable.
- `SeriesCodec` ABC and `NamedRegistry`: acceptable and in line with §1.2 (extension through
  registered classes). See the nit on where the registry belongs.
- `read` always returns a `source` column: acceptable and simpler for callers.
- Deduplication on `timestamp_utc` per sensor directory: equivalent to `sensor_id +
  timestamp_utc`. Acceptable.
- The atomic writer does not `fsync` the directory: acceptable for CI. It is documented, and
  the old file stays consistent.

Approve after the blocker is fixed. The minors can be fixed in the same round.
