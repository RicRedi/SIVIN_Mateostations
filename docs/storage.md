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
- First line is the header, exactly
  `timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source` (since WP-1.9; see
  [Format change in WP-1.9](#format-change-in-wp-19-precipitation-and-battery) for files with
  the older header `timestamp_utc,temp_c,rh_pct,source`).
- Then one line per sample, **strictly increasing** in `timestamp_utc` (no duplicates).
- Every timestamp lies in the year of the file name (UTC).

| Column | Content | Unit | Format | Missing |
|---|---|---|---|---|
| `timestamp_utc` | time of the sample | UTC | ISO 8601 `YYYY-MM-DDTHH:MM:SSZ`; a fraction of a second is written only when non-zero, as `.` and up to 9 digits without trailing zeros (`2026-01-01T00:00:00.5Z`) | never |
| `temp_c` | air temperature | °C | decimal number, see below | empty field |
| `rh_pct` | relative humidity | % | decimal number, see below | empty field |
| `precip_mm` | precipitation in the interval since the previous sample (export column `Srážky (mm)`) | mm | decimal number, see below | empty field |
| `precip_total_mm` | the device's cumulative precipitation counter (`Celkové srážky (mm)`) | mm | decimal number, see below | empty field |
| `battery_v` | battery voltage (`Nabití baterie (V)`) | V | decimal number, see below | empty field |
| `source` | name of the last export that contributed a value to the row | — | text | empty field = unknown |

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

**Reading** is strict: a header that is neither the current nor the pre-WP-1.9 one, a wrong
number of fields, a malformed timestamp or
number (`nan`, `1e3`, `12`, `12,5` are rejected), non-increasing timestamps or a row outside the
file's year raise `StoreFormatError` naming the file and line. A malformed file is never
overwritten by the store; repair it by hand (or restore it from git) and re-run.

**QC flags are not stored.** The `qc` column of `MeasurementSeries` is dropped on write and
`read` returns `qc = 0`. The automatic checks (range, spike, step, persistence, deployment,
neighbours, timestamps) are recomputed from the raw values at build time, so a change of a QC
threshold never requires rewriting the raw data, and the raw files hold only what the sensors
measured. `MANUAL_EXCLUDE` cannot be recomputed from raw values: it is an owner decision. It
will come from a human-edited exclusions file that the QC pipeline applies at build time (a
later workpackage); it is never stored in the raw files. If a series passed to `append`
carries any QC bits, the store logs a **warning** with the number of rows per flag, so a
caller that set flags (in particular `MANUAL_EXCLUDE`) by mistake notices that they are not
kept.

### Format change in WP-1.9 (precipitation and battery)

Owner decision Q9 (2026-10-05) takes precipitation, the cumulative precipitation counter and
the battery voltage into the data. The file layout therefore gained three columns between
`rh_pct` and `source`:

| | Header |
|---|---|
| before WP-1.9 (`LEGACY_STORED_COLUMNS`) | `timestamp_utc,temp_c,rh_pct,source` |
| since WP-1.9 (`STORED_COLUMNS`) | `timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source` |

- **Reading is backward compatible.** `CsvSeriesCodec.read` recognises both headers
  (`READABLE_LAYOUTS`). A file with the old header is read with `NaN` in the three new
  columns; every other rule (field count of that layout, number format, ordering) is the same.
- **Writing always uses the new header.** The store rewrites a file only when its data change
  (see below). An old file therefore stays byte-for-byte untouched until an append adds a row
  or fills a value, e.g. the precipitation of rows it already has; then the whole file is
  written in the new layout. No migration step is needed, and a repository can hold files of
  both layouts at the same time.
- **Byte stability** holds for the new layout: reading a file and writing it again reproduces
  it byte for byte. A file in the old layout is reproduced only as long as it is not rewritten.
- The new values follow the number format above; an export without these columns (older
  exports, other devices) gives empty fields.
- The growth estimate below rises by the three fields: with values such as `0.0,326.4,3.6`
  about 15 bytes per line, i.e. about 0.26 MB per sensor and year.

The committed synthetic sample `tests/fixtures/storage/legacy_layout/` is a store file in the
old layout; `tests/storage/test_auxiliary_columns.py` checks reading, leaving it untouched and
rewriting it.

## Appending, deduplication and conflicts

`MeasurementStore.append(series)` merges a series into the store, partition by partition. Rows
are identified by `timestamp_utc` (the sensor is given by the directory). A timestamp that is
not stored yet adds a row (`new_rows`). For a stored timestamp, the value columns `temp_c`,
`rh_pct`, `precip_mm`, `precip_total_mm` and `battery_v` are merged **column by column**, all
by the same rules (`VALUE_COLUMNS`):

| Stored value | Incoming value | Result | Counted as |
|---|---|---|---|
| equal to the incoming one, or both missing | | unchanged | — |
| missing | present | the incoming value is filled in | `filled_values` |
| present | missing | the stored value is kept | `ignored_missing_values` |
| present | present, different | decided by the conflict policy, logged and recorded | `conflicting_values` (and `replaced_values` when the incoming value wins) |

A missing value therefore **never overwrites a measurement**, whatever the policy. This matters
because a truncated last row of an export typically has missing values. An incoming row whose
values all equal the stored row counts as `identical_skipped`. Example: stored
`(temp_c, rh_pct) = (NaN, 70.0)` and incoming `(11.0, NaN)` give `(11.0, 70.0)`. Likewise, a
stored row without precipitation (an old-layout file) gets the precipitation of an export that
has it (`filled_values`), an export without the column never erases stored precipitation
(`ignored_missing_values`), and two exports with different precipitation for the same instant
are a conflict for the policy, exactly as for temperature.

`source` is not compared. A row keeps its stored `source` unless at least one of its values is
taken from the import (filled or replaced); then it gets the incoming `source`. The same data
downloaded again under another file name are identical rows and change nothing.

Conflict policies (extension point `ConflictPolicy`, registry `conflict_policy_registry`,
configuration key proposed as `storage.conflict_policy`):

- `prefer_newest` (**default**, `PreferNewest`): the value **appended last** wins. "Newest"
  means import order, not the age of the export: the pipeline appends exports in download
  order, so the latest download wins. **A back-fill of older exports** (e.g. the legacy
  hand-merged `data.xlsx`) **must use `prefer_existing`**; under `prefer_newest` its older
  values would replace those of newer exports.
- `prefer_existing` (`PreferExisting`): the stored value is kept.
- `raise` (`RaiseOnConflict`): the append fails with `MeasurementConflictError` and writes
  nothing.

Every conflict is logged as a warning with both values and sources, and recorded as a
`ConflictDecision` (sensor, timestamp, column, stored and incoming value and source, kept
`incoming`/`stored`, policy). `AppendResult.conflicts` holds the first
`max_recorded_conflicts` decisions of an append (configuration key proposed as
`storage.max_recorded_conflicts`, default 100), in time order. The pipeline copies them into
`RunRecord.conflicts`, so the `data` branch records which stored values were replaced. Beyond
the cap, conflicts are only counted (`conflicting_values`) and summarised in one log line per
partition file.

A file is rewritten only when it gains a row or a value changes (fill or replacement). Hence:

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
An append touching two years writes two files, each atomically but not as one transaction. If
the second write fails, the first file keeps its new content. Repeating the append completes the
rest and gives the same bytes as one clean append (tested). However, its counts report the rows
already written as `identical_skipped` instead of `new_rows`, so **the pipeline must record the
failed attempt** (e.g. in `RunRecord.failures`); otherwise the run log under-reports new data.
The store assumes a single writer at a time (one pipeline run), which the scheduled workflow
guarantees.

## Run log

`RunLog` appends one `RunRecord` per pipeline run as one JSON line to
`runs/<YYYY-MM-DD>.jsonl`, the UTC date of the run start. Fields: `started_at`,
`finished_at` (ISO 8601 UTC with `Z`), `files` (processed export files), `appends` (per sensor:
`new_rows`, `identical_skipped`, `filled_values`, `ignored_missing_values`,
`conflicting_values`, `replaced_values`), `validation_issues`
(number of input-validation findings per category, filled from the WP-1.2 report),
`failures` (one message per failure) and `conflicts` (the recorded conflict decisions, see
above). Keys are sorted. Lines are only ever appended.

A write interrupted mid-line leaves an incomplete last line. The next append notices that the
file does not end with a line break and starts a new line first (with a warning), so only the
broken line is lost. `RunLog.read` skips lines that are not valid records, with a warning naming
the file and line.

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
