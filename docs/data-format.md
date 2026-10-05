# Export formats and input validation

> **Not verified on a real export.** The formats below are reconstructed from the legacy
> scripts (`generate_animation.py`, `chrome_driver.py`, `sampl_freq_basic.py`,
> `vineyard_analyst.py` and the plot scripts). No real export file was available when the
> parsers were written. Until the owner provides a sample export (**Q1**) and confirms the
> time zone of its timestamps (**Q2**), every statement about column names, title rows, row
> order and time zone is an assumption. That is why all of them are configurable.

Code: `sivin.ingest.parsers` (parsers) and `sivin.ingest.validation` (validator).
Plan: MIGRATION_PLAN §2.7 and WP-1.2.

## Overview

```
file ──► ParserRegistry.for_file ──► ExportParser.parse
                                        │ load tables (CSV text / workbook sheets)
                                        │ TabularExportReader.inspect: header, columns,
                                        │   numbers, timestamps, row order, local → UTC
                                        ▼
                                  ExportInspection ──► InputValidator ──► ValidationReport
                                        │
             report has an ERROR ──► ParsedExport(series=(), report)       (quarantine)
             otherwise           ──► ParsedExport(series=(MeasurementSeries, ...), report)
```

A parser never raises because of file content. A rejected file yields an empty `series`
tuple and a report that says why. `ParserRegistry.for_file` raises `UnsupportedExportError`
when no parser accepts a file name, and `AmbiguousExportError` when several do. The second
case is a programming error.

## Supported formats

| Format id | Class | Accepted files | Sensor |
|---|---|---|---|
| `portal-csv` | `PortalCsvParser` | any `*.csv` | from the file name (`SensorId.parse`) |
| `portal-xlsx` | `PortalXlsxParser` | `*.xlsx`/`*.xlsm` whose name starts with `MeteoData` or names a sensor | from the file name |
| `legacy-workbook` | `LegacyWorkbookParser` | other `*.xlsx`/`*.xlsm`, only if a sheet mapping is configured | from the sheet → sensor mapping |

Routing looks at the file name only and never sniffs the content. A foreign file sent to the
wrong parser is judged by its content and fails loudly (wrong delimiter or unknown headers
give `required-columns`, a name without a serial gives `sensor-id`).

### Portal CSV (legacy `generate_animation.py`)

```
Meteo Data;
Datum a čas;Teplota (°C);Vlhkost (%)
2026-03-01 00:00:07;3,7;86,7
```

- Delimiter `;` (`csv_delimiter`). Encoding UTF-8 with or without BOM, then Windows-1250
  (`csv_encodings`). The Windows-1250 fallback is an assumption.
- One title row `Meteo Data;`. The header row is searched for, so any number of title rows
  works, up to `header_search_rows`.
- Further columns may exist; unknown columns are ignored.
- Decimal comma. Local wall-clock timestamps `%Y-%m-%d %H:%M:%S`.
- File name example: `MeteoData_8615620 77678271 (VUT)_20260301_223857.csv`.

### Portal XLSX (downloaded by legacy `chrome_driver.py`)

- File name `MeteoData_8615620 77678271.xlsx`, optionally with label, export time or a
  browser copy suffix such as ` (1)`.
- The layout is assumed to match the CSV: title row and header row, found by searching the
  first `header_search_rows` rows.
- Only the first worksheet is read. Any other worksheets are reported (WARNING) and ignored.
- Timestamps can be Excel date-time cells or text. The text can be ISO or day-first, e.g.
  `5.1.2026 17:33:01` (legacy `sampl_freq_basic.py`). Values can be number cells or text with
  a decimal comma.

### Legacy workbook `data.xlsx` (legacy `vineyard_analyst.py`, plot scripts)

- One worksheet per sensor, named by the legacy 4-digit suffix (`9986`, `8271`, `0065`,
  `0921`). Columns are `Datum a čas`, `Teplota` and `Vlhkost`, with a decimal comma.
- The 4-digit suffix is ambiguous, so the caller passes the mapping, either as
  `ParserSettings.legacy_sheet_sensors` (`{"8271": "77678271"}`) or as the `sheet_sensors`
  argument. It is normally resolved through the sensor registry (WP-1.1).
- A mapped sheet that is missing from the workbook is an ERROR. An unmapped sheet is a
  WARNING and is not read.

## Column names

Headers are matched exactly after normalisation: case-folded, without diacritics, and with
whitespace collapsed (`normalize_label`). A unit in parentheses or brackets is split off and
must be one of the units accepted for that column (`normalize_unit`). Substring matching is
not used, so `Teplota rosného bodu (°C)` (dew point) is not mistaken for the temperature.

| Canonical | Default aliases (`ParserSettings.aliases`) | Accepted units |
|---|---|---|
| timestamp | Datum a čas, Datum, Čas, Datum und Uhrzeit, Datum/Uhrzeit, Zeitstempel, Zeit, Date and time, Date, Time, Datetime, Timestamp | none |
| `temp_c` | Teplota, Teplota vzduchu, Temperatur, Lufttemperatur, Temperature, Air temperature, Temp | °C, C, degC, deg C, ℃ |
| `rh_pct` | Vlhkost, Relativní vlhkost, Vlhkost vzduchu, Luftfeuchtigkeit, Relative Luftfeuchtigkeit, Luftfeuchte, Feuchtigkeit, Humidity, Relative humidity, RH | %, % RH, %RH, % rel., pct |

- `Teplota (°F)` is rejected (ERROR); it is never read as °C.
- A qualified timestamp header such as `Datum a čas (UTC)` is rejected by default. Otherwise
  it would be read silently in `source_timezone`.
- If two columns denote the same canonical column, the file is rejected (ERROR).

## Values

- Decimal comma or decimal point; no thousands separator. A number containing both `,` and
  `.` is unparseable. The typographic minus `−` is accepted.
- An empty cell is a missing value (`NaN`). Text such as `n/a`, `nan` or `inf`, booleans,
  dates and numbers too large for a float (e.g. a 400-digit integer cell) in a value column are
  unparseable.
- Formula cells are read with their cached result. A workbook saved by a script has no cached
  results; such cells read as empty, and `values-present` rejects the file.
- A row whose temperature **and** humidity are both missing gets `QcFlag.MISSING`. A row with
  only one missing value keeps `qc = 0` and the missing value is `NaN`. `DailyWeather` already
  ignores `NaN` per variable, and a row flag would also exclude the valid other variable
  (see the hand-off note, open question 1).

## Timestamps

1. **Parsing.** Spreadsheet date-time cells, or text in ISO form
   (`2026-03-01 22:38:57`, with or without seconds, `T` allowed) or numeric form
   (`5.1.2026 17:33:01`, `05/01/2026 17:33`). Numeric dates are day first unless
   `day_first: false`. Date-only text, `date`/`time` values, timezone-aware values and dates
   outside 1678–2261 (the `datetime64[ns]` range) are unparseable. A spreadsheet cell
   formatted as a date only arrives from openpyxl as a `datetime` at midnight and is read as
   local midnight.
2. **Day/month swap guard** (`DateOrderCheck`, rule `date-order`, ERROR). The cells are read
   again with the other date order. The order is called ambiguous if the other order reads more
   cells (e.g. `1/13/2026`), or reads as many cells with fewer *long* steps between consecutive
   timestamps. A long step is longer than `expected_interval_s × long_step_factor`
   (1825 s × 48 ≈ 24.3 h). A month-first file whose days are all ≤ 12 reads without parse
   errors, but every change of day becomes a step of about a month. The median step cannot
   show this, because only one step per day changes. The guard therefore counts long steps
   instead of comparing the median with the expected interval.
3. **Plausible range** (rule `timestamps-plausible`). A local time before
   `earliest_timestamp` (2020-01-01, project default [to be tuned]; the project started in
   2025) or after the run time plus `max_future_s` (1 day) is dropped. Too many such rows
   reject the file. `latest_timestamp` can fix the upper bound, e.g. for tests or re-imports.
4. **Row order** (`sivin.ingest.parsers.order`). Steps are counted between consecutive readable
   rows. A step between two ambiguous rows of the same fall-back day (inside the repeated
   hour) is **not** counted, because its direction is unknown before conversion. Every other
   step counts, including the steps into and out of the repeated hour.
   - A table is reversed only if it is **clearly newest first**: at least
     `newest_first_min_steps` (4) counted non-zero steps, and at least
     `newest_first_min_share` (0.75) of them go back in time. A table that steps back but has
     fewer steps is read oldest first (rule `row-order`, WARNING). The real row order of the
     exports is unknown (Q1).
   - A row more than `max_backward_step_s` (2 h; at least 1 h, the repeated hour) earlier
     than the latest time already read is **dropped** (rule `large-backward-steps`, WARNING).
     This covers a device clock reset and a long overlap of concatenated exports. The rows
     before it are kept, and the rows after it are kept again once the clock is back within
     2 h of the latest time. The rows of a long overlap are copies of rows already read, so in
     an overlap the first export's values win.
   - Every remaining counted backward step comes from a clock correction or a short overlap.
     It is handled by an `OrderRepair` strategy (rule `backward-steps`, WARNING). The default,
     `SplitAtBackwardSteps`, starts a new segment at each such step and converts each segment
     separately, so no row is dropped. After conversion the rows are sorted by UTC. Rows
     repeated by an overlap become duplicate instants, and the last one is kept. A single
     clock correction never rejects a file.
5. **Local → UTC** with `LocalTimeConverter(source_timezone)` (default `Europe/Prague`, Q2),
   applied to each segment in source order:
   - Times in the repeated hour of the autumn fall-back are resolved from the order of the
     samples and flagged `TIMESTAMP_SUSPECT`.
   - Times in the skipped hour of the spring transition are shifted by the gap and flagged
     `TIMESTAMP_SUSPECT`.
   - Rows the converter marks `unresolved` (a guess, or `NaT` after a collision) are
     **dropped**. Their number appears in the `daylight-saving` WARNING.
   - **Incomplete transitions.** The ambiguous rows of one fall-back day are also dropped
     (counted as unresolved) unless their segment has ordinary rows both before and after
     them. Rows of the repeated hour that an overlap repeats at the end of a file look
     exactly like a transition the file stops in, and the converter would place them one hour
     late. A genuine export that ends or starts inside the repeated hour loses those rows;
     the loss is reported.
   - The review's exhaustive check (two overlapping chunks of 24 samples across the
     fall-back, both directions, 5152 files) places **no** row at a wrong instant. A seeded
     subset of 400 cases runs in `tests/ingest/parsers/test_order.py`.
6. **Duplicates.** If one file repeats a UTC instant, the last occurrence is kept
   (`MeasurementSeries.from_records`) and the count is reported. Conflicts between different
   files are resolved by the measurement store (WP-1.4).

## Validation rules

Each rule is one `ValidationRule` class registered with `validation_rules`. A report with
any ERROR rejects the whole file. Thresholds are in `ValidationSettings`, the proposed
configuration section `ingest.validation`. The defaults are project defaults
**[to be verified]** on real data.

| Rule id | Checks | Severity |
|---|---|---|
| `file-exists` | the path is an existing regular file | ERROR |
| `file-not-empty` | the file has more than 0 bytes | ERROR |
| `file-readable` | the CSV decodes and parses; the workbook opens (a truncated or corrupt archive fails here) | ERROR |
| `expected-tables` | mapped worksheets are present and there is at least one table (ERROR); unread worksheets are listed (WARNING) | ERROR / WARNING |
| `sensor-id` | the sensor resolves from the file name or the sheet mapping | ERROR |
| `required-columns` | a header row with timestamp, temperature and humidity exists in the first `header_search_rows` rows; units are accepted; no duplicate columns | ERROR |
| `data-rows` | at least `min_data_rows` (1) non-blank rows below the header | ERROR |
| `short-rows` | rows that end before a required column (cut-off line); the missing cells become missing values | WARNING |
| `numbers-parseable` | share of non-numeric value cells > `max_unparseable_value_share` (5 %) → ERROR; otherwise the values become missing | ERROR / WARNING |
| `timestamps-parseable` | share of unreadable timestamps > `max_unparseable_timestamp_share` (5 %) → ERROR; otherwise the rows are dropped | ERROR / WARNING |
| `values-present` | no temperature and no humidity value at all (empty columns, formulas without cached results) → ERROR; one variable without any value (e.g. a failed humidity channel) → WARNING, the other is imported | ERROR / WARNING |
| `date-order` | day and month look swapped (see Timestamps, step 2) | ERROR |
| `timestamps-plausible` | share of timestamps outside the plausible range > `max_implausible_timestamp_share` (5 %) → ERROR; otherwise the rows are dropped | ERROR / WARNING |
| `row-order` | the table steps back but is too short to decide whether it is newest first; read oldest first | WARNING |
| `large-backward-steps` | rows more than `max_backward_step_s` earlier than rows before them (clock reset, long overlap); dropped | WARNING |
| `duplicate-timestamps` | repeated UTC instants (count, and how many conflict); the last one is kept | WARNING |
| `backward-steps` | counted backward steps (count and the first 10 source rows); converted in segments | WARNING |
| `daylight-saving` | ambiguous or nonexistent local times (flagged `TIMESTAMP_SUSPECT`) and the number of unresolved rows dropped (including incomplete transitions) | WARNING |
| `temperature-bounds` | share of temperatures outside [`temp_min_c`, `temp_max_c`] = [−60, 70] °C > `max_out_of_bounds_share` (5 %) → ERROR (°F or K export, swapped columns); otherwise WARNING | ERROR / WARNING |
| `humidity-bounds` | same for relative humidity outside [0, 100] % | ERROR / WARNING |
| `humidity-fraction` | share of humidity values ≤ `rh_fraction_max_pct` (1 %) > `max_out_of_bounds_share` → humidity given as a 0–1 fraction | ERROR |

**Short files.** A share threshold gives an ERROR only when more than `min_error_rows` (3)
rows are affected, or all of them. So one footer or comment row in a ten-row file is a
WARNING (the row is dropped), while a file whose every timestamp is unreadable is still an
ERROR. This applies to `numbers-parseable`, `timestamps-parseable`, `timestamps-plausible`,
the gross bounds rules and `humidity-fraction`.

These gross bounds only guard against unit and column mix-ups. Values outside the bounds
that stay below the share threshold are reported but kept: the climatological range check
and the `OUT_OF_RANGE` flag are quality control (WP-1.5). A temperature column in °F is only
rejected through its header or when enough values exceed 70 (a winter export in °F could pass
the value check). This limitation is known.

Row numbers in findings are 1-based source rows (the CSV line or the spreadsheet row) of the
first affected row.

## Settings

`ParserSettings` (proposed section `ingest.parsers`): `source_timezone`, `aliases`,
`header_search_rows` (10), `day_first` (true), `newest_first_min_share` (0.75),
`newest_first_min_steps` (4), `max_backward_step_s` (7200), `earliest_timestamp`
(2020-01-01), `latest_timestamp` (none: run time + `max_future_s`), `max_future_s` (86400),
`expected_interval_s` (1825), `long_step_factor` (48), `csv_delimiter` (`;`), `csv_encodings`
(`utf-8-sig`, `cp1250`), `legacy_sheet_sensors` ({}).
`ValidationSettings` (proposed section `ingest.validation`): see the table above. Both are
frozen pydantic models with `extra="forbid"`.

## Test fixtures

`tests/fixtures/exports/` holds synthetic files generated by `make_fixtures.py`. The README
there lists every file and the expected result.
