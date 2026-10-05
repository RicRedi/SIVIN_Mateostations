# Measurement store

The measurement store keeps the canonical measurements of every sensor as plain files
(MIGRATION_PLAN §2.5). It is implemented in `sivin.storage` (WP-1.4). There is no database.

## Layout

```
<root>/
  raw/<sensor_id>/<YYYY>.csv     one file per sensor and UTC calendar year
  runs/<YYYY-MM-DD>.jsonl        run log, one file per UTC date of the run start
```

- `<root>` is `paths.data_dir` of the configuration (`data/`). In production it is the `data/`
  directory on the **`data` branch** of the repository, which only the pipeline workflow
  writes. On `main` the root `.gitignore` ignores `/data/`, so measurements never land on
  `main`; checking out and committing the `data` branch is the job of the pipeline (WP-4.1),
  which has to take that ignore rule into account.
- `<sensor_id>` is the canonical 8-digit serial (`SensorId`), e.g. `raw/77678271/2026.csv`.
- `<YYYY>` is the **UTC** year of the samples (`YearPartitioning`). A sample taken at 00:30
  local time on 1 January (23:30 UTC on 31 December in winter) is stored in the previous
  year's file. `MeasurementStore.read` hides this: it reads every file that overlaps the
  requested interval.
- `data/derived/events/` of §2.5 is written by later workpackages, not by the store.
- Hidden files `.<name>.*.tmp` are leftovers of an interrupted write (see *Atomic writes*);
  the store ignores them and they can be deleted.

## File format of `raw/<sensor_id>/<YYYY>.csv`

Implemented by `CsvSeriesCodec`. The format is exact, so that writing the same data always gives
the same bytes (git sees no change when nothing changed).

- Encoding UTF-8 without byte-order mark; line terminator LF (`\n`), also on Windows; the last
  line ends with LF.
- Separator `,`; quoting per RFC 4180: a field is enclosed in `"` only when it contains `,`,
  `"`, CR or LF, and a `"` inside is doubled.
- First line is the header, exactly `timestamp_utc,temp_c,rh_pct,source`.
- Then one line per sample, **strictly increasing** in `timestamp_utc` (no duplicates).
- Every timestamp lies in the year of the file name (UTC).

| Column | Content | Unit | Format | Missing |
|---|---|---|---|---|
| `timestamp_utc` | time of the sample | UTC | ISO 8601 `YYYY-MM-DDTHH:MM:SSZ`; a fraction of a second is written only when non-zero, as `.` and up to 9 digits without trailing zeros (`2026-01-01T00:00:00.5Z`) | never |
| `temp_c` | air temperature | °C | decimal number, see below | empty field |
| `rh_pct` | relative humidity | % | decimal number, see below | empty field |
| `source` | name of the export file the row came from | — | text | empty field = unknown |

**Numbers.** `.` is the decimal point, positional notation (never an exponent), at least one
digit after the point, and otherwise the **shortest** digit string that reads back as exactly
the same IEEE 754 `float64` (`numpy.format_float_positional(value, unique=True, trim="k",
min_digits=1)`). Examples: `12.3`, `-0.5`, `100.0`, `0.30000000000000004`. Choice and reasons:

- The provider's exports are assumed to have a resolution of 0.1 °C and 0.1 % (legacy
  scripts; not yet confirmed by a real export, owner question Q1). Such values come out as
  `12.3`, i.e. exactly as in the source.
- A fixed number of decimals (e.g. `%.1f`) would silently round away any finer value; the
  shortest round-trip form never loses information, whatever the source precision.
- The representation is a pure function of the value, so files are byte-stable, and
  reading a file and writing it again reproduces it byte for byte.
- `-0.0` is written as `-0.0` (it is a distinct `float64`; harmless).

**Reading** is strict: a wrong header, a wrong number of fields, a malformed timestamp or
number (`nan`, `1e3`, `12`, `12,5` are rejected), non-increasing timestamps or a row outside the
file's year raise `StoreFormatError` naming the file and line. A malformed file is never
overwritten by the store; repair it by hand (or restore it from git) and re-run.

**QC flags are not stored.** The `qc` column of `MeasurementSeries` is dropped on write and
`read` returns `qc = 0`: quality control is recomputed from the raw values at build time, so a
change of a QC threshold never requires rewriting the raw data, and the raw files hold only what
the sensors measured.

## Appending, deduplication and conflicts

`MeasurementStore.append(series)` merges a series into the store, partition by partition. Rows
are identified by `timestamp_utc` (the sensor is given by the directory):

| Incoming row | Result | Counted as |
|---|---|---|
| timestamp not stored yet | added | `new_rows` |
| same timestamp, same `temp_c` and `rh_pct` (missing equals missing) | stored row kept unchanged, including its `source` | `identical_skipped` |
| same timestamp, different values | decided by the conflict policy, logged with both values | `conflicting_rows` (and `replaced_rows` when the incoming row wins) |

`source` is not compared: the same data downloaded again under another file name are identical
rows and change nothing. A missing value against a present value is a conflict.

Conflict policies (extension point `ConflictPolicy`, registry `conflict_policy_registry`,
configuration key proposed as `storage.conflict_policy`):

- `prefer_newest` (**default**, `PreferNewest`): the incoming row, i.e. the newer import, wins.
- `prefer_existing` (`PreferExisting`): the stored row is kept.
- `raise` (`RaiseOnConflict`): the append fails with `MeasurementConflictError`.

Each conflict is logged as a warning with the stored and the incoming values and sources; after
20 conflicts in one partition only a summary line is logged.

A file is rewritten only when it gains or replaces a row. Hence:

- importing the same export twice leaves every file byte-identical (tested with SHA-256);
- overlapping exports merge into one gap-free series;
- rows are always written in ascending time order, whatever the order of imports.

All partitions of one append are merged in memory before anything is written, so a refused
conflict (`raise`) or a malformed existing file writes nothing.

## Atomic writes

Each file is replaced atomically (`AtomicFileWriter`): the new content is written to a hidden
temporary file in the same directory, flushed and `fsync`-ed, then renamed over the target with
`os.replace`. A failure before the rename (exception, full disk) removes the temporary file and
leaves the old file intact; a reader sees either the complete old or the complete new file.
An append touching two years writes two files, each atomically but not as one transaction; if
the second write fails, repeating the append completes it (appends are idempotent). The store
assumes a single writer at a time (one pipeline run), which the scheduled workflow guarantees.

## Run log

`RunLog` appends one `RunRecord` per pipeline run as one JSON line to
`runs/<YYYY-MM-DD>.jsonl`, the UTC date of the run start. Fields: `started_at`,
`finished_at` (ISO 8601 UTC with `Z`), `files` (processed export files), `appends` (per sensor:
`new_rows`, `identical_skipped`, `conflicting_rows`, `replaced_rows`), `validation_issues`
(number of input-validation findings per category, filled from the WP-1.2 report) and
`failures` (one message per failure). Keys are sorted. Lines are only ever appended.

## Reading

- `read(sensor_id, start_utc=None, end_utc=None)` returns a `MeasurementSeries` with inclusive,
  timezone-aware bounds, across year files; an unknown sensor or an empty range gives an empty
  series.
- `sensors()` lists the sensors that have at least one year file.
- `time_range(sensor_id)` gives the first and last stored timestamp, or `None`.
- `coverage(sensor_id, expected_interval_s, start_utc=None, end_utc=None)` gives the share of
  expected samples (`floor(duration / interval) + 1`) stored with at least one value, capped at
  1; the stored time range when bounds are omitted.

## Why no database

The data are small (below), written once per hour by a single scheduled job and read in bulk.
Plain CSV files on a git branch need no server and no credentials, are versioned for free
(every change of the data is a commit that can be inspected and reverted), are readable by any
tool, and fit the static GitHub Pages deployment (MIGRATION_PLAN §0.5, §2.3). What a database
would add (concurrent writers, indexes, transactions over many rows) is not needed here.

## Growth estimate

At the nominal interval of 1825 s a sensor gives 365 × 86 400 / 1825 = 17 280 samples per year.
A line without a source name (`2026-01-01T00:00:00Z,12.3,81.5,`) has 32 bytes, so about
0.55 MB per sensor and year; this is the 0.5 MB of MIGRATION_PLAN §2.5. With a full export file
name in `source` (e.g. `MeteoData_8615620 77678271 (VUT)_20260301_223857.csv`, 84-byte line)
it is about 1.45 MB per sensor and year. Tens of sensors therefore mean tens of MB per year,
well within what git and the pipeline handle. Each changed year file is a new git blob; git
stores successive versions as compressed deltas when it packs the repository.

## Migration path to Parquet

The store depends on two small interfaces only: `SeriesCodec` (bytes of one file) and
`Partitioning` (which rows go to which file). With hundreds of sensors, a `ParquetSeriesCodec`
(e.g. via `pyarrow`, a new dependency) and possibly a monthly `Partitioning` can be added as new
classes and selected by configuration, without changing `MeasurementStore`, the merge rules or
the callers. A one-off command would read every CSV file with the current codec and write it
with the new one; the static site could then query the Parquet files directly in the browser
with DuckDB-WASM, still without a server (MIGRATION_PLAN §2.5).
