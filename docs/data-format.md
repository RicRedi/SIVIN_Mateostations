# Export formats and input validation

> **Partly verified on a real export.** The formats below were reconstructed from the legacy
> scripts (`generate_animation.py`, `chrome_driver.py`, `sampl_freq_basic.py`,
> `vineyard_analyst.py` and the plot scripts) before any real export was available. The
> **portal CSV** has since been checked against one real export of sensor 77799986 (see
> [Verified against a real export](#verified-against-a-real-export)); the owner confirmed that
> the timestamps are local time (**Q2**). The **portal XLSX** layout and the exports of the other
> sensors are still unverified (**Q11**), so column names, title rows and row order stay
> configurable.

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
Datum a čas;Teplota (°C);Vlhkost (%);Srážky (mm);Celkové srážky (mm);Nabití baterie (V)
2026-03-01 22:27:05;23,79;31,1;0,0;326,4;3,60
...
2025-07-30 10:22:29;28,66;41,8;0,0;323,0;3,00
;
```

(First and last data rows of the real export of sensor 77799986; the legacy scripts showed only
the first three columns.)

- Delimiter `;` (`csv_delimiter`). Encoding UTF-8 with or without BOM, then Windows-1250
  (`csv_encodings`). The Windows-1250 fallback is an assumption.
- One title row `Meteo Data;`. The header row is searched for, so any number of title rows
  works, up to `header_search_rows`.
- Three further columns hold precipitation, cumulative precipitation and battery voltage.
  Since WP-1.9 they are read into `precip_mm`, `precip_total_mm` and `battery_v` (owner
  decision Q9); they are optional, so a file without them is still valid (see
  [Optional columns](#optional-columns-precipitation-counter-battery)). Other unknown columns
  are ignored.
- Decimal comma. Local wall-clock timestamps `%Y-%m-%d %H:%M:%S`, newest row first.
- A last line `;` (empty cells) follows the data; blank rows are skipped.
- File name examples: `MeteoData_8615620 77678271 (VUT)_20260301_223857.csv` (legacy
  scripts) and `MeteoData_8615620_77799986_VUT_20260301_223842.csv` (the real export, with
  underscores; owner question Q8). `SensorId.parse` accepts both.
- Rules of the underscore spelling (`UNDERSCORE_FILE_NAME_PATTERN`), which keep it unambiguous:
  - the `MeteoData_` prefix is required;
  - the portal device number is optional and has **1–7 digits** (the portal's is `8615620`).
    An 8-digit run after the prefix is always the serial, so a name with an 8-digit device
    number (or none) is never misread. If the portal ever issues 8-digit device numbers, such
    names are rejected with a `sensor-id` ERROR, never assigned to a wrong sensor;
  - the label is optional, one or more `_`-separated words, each starting with a Unicode
    letter and continuing with letters, digits or `-` (`VUT`, `VÚT`, `VUT_Brno`). A word never
    starts with a digit, so the label cannot absorb the export time;
  - the export time `_YYYYMMDD_HHMMSS` (8 and 6 digits) is optional and comes last, before a
    browser copy suffix such as ` (1)` and the extension. `MeteoData_77799986_20260301.csv`
    is rejected instead of being read as sensor `20260301`.

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

| `precip_mm` (optional) | Srážky, Srážka, Srážky za interval, Niederschlag, Niederschlagsmenge, Regen, Precipitation, Rain, Rainfall | mm, l/m², l/m2 |
| `precip_total_mm` (optional) | Celkové srážky, Srážky celkem, Kumulativní srážky, Niederschlag gesamt, Gesamtniederschlag, Kumulierter Niederschlag, Total precipitation, Cumulative precipitation, Precipitation total, Total rain, Rain total | mm, l/m², l/m2 |
| `battery_v` (optional) | Nabití baterie, Napětí baterie, Baterie, Batterie, Batteriespannung, Battery, Battery voltage | V |

- `Teplota (°F)` is rejected (ERROR); it is never read as °C.
- A qualified timestamp header such as `Datum a čas (UTC)` is rejected by default. Otherwise
  it would be read silently in `source_timezone`.
- If two columns denote the same **required** canonical column, the file is rejected (ERROR).
- The Czech names of the three optional columns are those of the real export (§0.6.1); the
  German and English aliases are guesses for other tools and are configurable.

### Optional columns (precipitation, counter, battery)

Timestamp, temperature and humidity are required (`REQUIRED_CANONICAL_COLUMNS`). The
precipitation of the interval since the previous sample (`precip_mm`), the device's cumulative
precipitation counter (`precip_total_mm`) and the battery voltage (`battery_v`) are optional
(`OPTIONAL_CANONICAL_COLUMNS`, WP-1.9, owner decision Q9):

- A file without them (older exports, other devices) is valid; the series gets `NaN` in those
  columns.
- A problem with an optional column never rejects the file, because whole-row validity
  concerns temperature and humidity only. An unaccepted unit (`Srážky (in)`) or two headers
  for the same optional column is a WARNING (`optional-columns`) and that column is not read.
  Non-numeric cells are a WARNING (`numbers-parseable`) and read as missing, whatever their
  share. Values outside the gross bounds are a WARNING and are also read as missing: they
  are unit or column mix-ups (e.g. a battery charge of 85 % under a unitless `Battery`
  header must not become 85 V), and no quality check would catch them later.
- A missing optional value never sets `QcFlag.MISSING`.

## Values

- Decimal comma or decimal point; no thousands separator. A number containing both `,` and
  `.` is unparseable. The typographic minus `−` is accepted.
- An empty cell is a missing value (`NaN`). Text such as `n/a`, `nan` or `inf`, booleans,
  dates and numbers too large for a float (e.g. a 400-digit integer cell) in a value column are
  unparseable.
- Formula cells are read with their cached result. A workbook saved by a script has no cached
  results; such cells read as empty, and `values-present` rejects the file.
- **Whole-row validity** (owner decision 2026-10-05, plan §0.5): a row whose temperature
  **or** humidity is missing gets `QcFlag.MISSING`; the measurement as a whole is invalid. The
  present value is kept in the series (it is not set to `NaN`), but the flag excludes the row
  from indices and from the web chart, and `DailyWeather` does not count it even without the
  flag. Until 2026-10-05 only rows with both values missing were flagged (WP-1.2).
- The optional columns follow the same number format. A missing precipitation, counter or
  battery value does **not** make the row invalid (owner decision Q9).

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
   (1830 s × 48 ≈ 24.4 h). A month-first file whose days are all ≤ 12 reads without parse
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
     fewer steps is read oldest first (rule `row-order`, WARNING). The real CSV export is
     newest first and is reversed by this rule.
   - **Out-of-sequence rows** (rule `out-of-sequence`). Each row is compared with the latest
     *accepted* row. The threshold is `max_backward_step_s` (2 h, at least 1 h = the
     repeated hour).
     - A row more than 2 h **earlier** is dropped (device clock reset). The exception is a
       row that repeats the wall-clock time of an accepted row exactly: it is a copy from an
       overlapping export and is kept, and later becomes a duplicate instant.
     - A row more than 2 h **later** is checked against the next 5 rows. If most of them
       are earlier than it (the clock returns), it is an isolated forward outlier, i.e. a
       glitched timestamp, and only that row is dropped. Otherwise it is accepted as a
       genuine outage after which the clock continues. An outlier never becomes the
       reference, so one glitched row cannot discard the rows after it.
     - The first row has no reference. It is an outlier only when most of the next 5 rows
       are more than 2 h earlier than it, so that a short newest-first table read oldest
       first is not mistaken for one.
     - Dropping more than `max_implausible_timestamp_share` (5 %) of the rows, and more
       than `min_error_rows`, is an ERROR, so a mass drop is never silent.
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
     the loss is reported. An export that ends just after the clock jump (e.g. 02:10 CEST,
     02:40 CEST, 02:11 CET) loses its last repeated-hour rows the same way. The rows are
     recovered when the next, overlapping export is imported, because the measurement store
     (WP-1.4) merges overlapping exports and fills the gap. This behaviour is accepted
     (review round 2).
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
| `short-rows` | rows that end before a mapped column, required or optional (cut-off line); the missing cells become missing values | WARNING |
| `optional-columns` | an optional column (precipitation, counter, battery) with an unaccepted unit or two headers; that column is not read | WARNING |
| `numbers-parseable` | share of non-numeric temperature or humidity cells > `max_unparseable_value_share` (5 %) → ERROR; otherwise the values become missing. Non-numeric cells of an optional column are always a WARNING | ERROR / WARNING |
| `timestamps-parseable` | share of unreadable timestamps > `max_unparseable_timestamp_share` (5 %) → ERROR; otherwise the rows are dropped | ERROR / WARNING |
| `values-present` | a temperature or humidity column without any value (empty column, formulas without cached results, e.g. a failed humidity channel) → ERROR: under whole-row validity every row would be `MISSING`, so the file holds no valid measurement (until 2026-10-05 one empty variable was a WARNING) | ERROR |
| `date-order` | day and month look swapped (see Timestamps, step 2) | ERROR |
| `timestamps-plausible` | share of timestamps outside the plausible range > `max_implausible_timestamp_share` (5 %) → ERROR; otherwise the rows are dropped | ERROR / WARNING |
| `row-order` | the table steps back but is too short to decide whether it is newest first; read oldest first | WARNING |
| `out-of-sequence` | rows more than `max_backward_step_s` earlier than the latest accepted row (clock reset; exact overlap copies excepted) or isolated more than that ahead of their neighbours (glitched timestamp); dropped. Share > `max_implausible_timestamp_share` (5 %) and more than `min_error_rows` → ERROR | ERROR / WARNING |
| `duplicate-timestamps` | repeated UTC instants (count, and how many conflict in any value column, optional ones included); the last one is kept | WARNING |
| `backward-steps` | counted backward steps (count and the first 10 source rows); converted in segments | WARNING |
| `daylight-saving` | ambiguous or nonexistent local times (flagged `TIMESTAMP_SUSPECT`) and the number of unresolved rows dropped (including incomplete transitions) | WARNING |
| `temperature-bounds` | share of temperatures outside [`temp_min_c`, `temp_max_c`] = [−60, 70] °C > `max_out_of_bounds_share` (5 %) → ERROR (°F or K export, swapped columns); otherwise WARNING | ERROR / WARNING |
| `humidity-bounds` | same for relative humidity outside [0, 100] % | ERROR / WARNING |
| `precipitation-bounds` | precipitation per interval outside [`precip_min_mm`, `precip_max_mm`] = [0, 500] mm; never rejects; the values are read as missing | WARNING |
| `precipitation-total-bounds` | cumulative counter outside [`precip_total_min_mm`, `precip_total_max_mm`] = [0, 100 000] mm; never rejects; read as missing | WARNING |
| `battery-bounds` | battery voltage outside [`battery_min_v`, `battery_max_v`] = [0, 10] V (catches millivolts and a charge in %); never rejects; read as missing | WARNING |
| `humidity-fraction` | share of humidity values ≤ `rh_fraction_max_pct` (1 %) > `max_out_of_bounds_share` → humidity given as a 0–1 fraction | ERROR |

**Short files.** A share threshold gives an ERROR only when more than `min_error_rows` (3)
rows are affected, or all of them. So one footer or comment row in a ten-row file is a
WARNING (the row is dropped), while a file whose every timestamp is unreadable is still an
ERROR. This applies to `numbers-parseable`, `timestamps-parseable`, `timestamps-plausible`,
`out-of-sequence`, the temperature and humidity bounds rules and `humidity-fraction`.

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
`expected_interval_s` (1830, the median step of the real export; the legacy estimate was 1825), `long_step_factor` (48), `csv_delimiter` (`;`), `csv_encodings`
(`utf-8-sig`, `cp1250`), `legacy_sheet_sensors` ({}).
`ValidationSettings` (proposed section `ingest.validation`): see the table above. Both are
frozen pydantic models with `extra="forbid"`.

## Verified against a real export

On 2026-10-05 the owner supplied the first real export (Q1, plan §0.6.1):
`MeteoData_8615620_77799986_VUT_20260301_223842.csv`, sensor 77799986, 3520 data rows from
2025-07-30 10:22:29 to 2026-03-01 22:27:05 local time (2025-07-30 08:22:29Z to
2026-03-01 21:27:05Z). The portal CSV parser reads it under its original name without any
validation finding.

What matched the reconstructed format:

- title line `Meteo Data;`, then the header row; `;` delimiter, decimal comma,
- the header names `Datum a čas`, `Teplota (°C)`, `Vlhkost (%)`,
- local wall-clock timestamps `YYYY-MM-DD HH:MM:SS` in `Europe/Prague` (owner decision Q2),
- encoding UTF-8 (without BOM), read by the first entry of `csv_encodings`.

What differed from it, and how it is handled:

| Finding | Handling |
|---|---|
| File name with underscores instead of spaces and parentheses (`MeteoData_8615620_77799986_VUT_…`); unknown whether the portal or the upload produced it (Q8) | `SensorId.parse` accepts both spellings (WP-0.2); routing (`can_parse`) already accepted any `.csv` and any `MeteoData…` workbook |
| Three extra columns `Srážky (mm)`, `Celkové srážky (mm)`, `Nabití baterie (V)` | read since WP-1.9 as the optional columns `precip_mm`, `precip_total_mm`, `battery_v` (owner decision Q9). In the full export: interval precipitation mostly 0.0 mm, at most 0.9 mm; counter 323.0–326.4 mm; battery 3.0–3.7 V. The interval value of a sample equals the counter increase since the previous sample up to 0.1 mm (rounding) |
| Rows **newest first** | reversed by the row-order analysis (no finding) |
| A last line `;` after the data | a blank row, skipped |
| CRLF line endings | read by the CSV reader (no finding) |
| Median step 1830 s, not the legacy 1825 s | default `expected_interval_s` = 1830 s (`time` and `ingest.parsers`) |
| Gaps of 3.5 h, 23.4 h and 139 days (3336.6 h) near the start, and two samples 49 s apart | kept as they are; gaps are not a validation finding |
| No daylight-saving transition inside the data (the 2025 fall-back lies in the 139-day gap) | DST handling is still verified only on synthetic data |

A trimmed excerpt (300 rows, original bytes) is the regression fixture
`tests/fixtures/exports/real/`, tested by `tests/ingest/test_real_export.py`.

## Test fixtures

`tests/fixtures/exports/` holds synthetic files generated by `make_fixtures.py`. The README
there lists every file and the expected result. The only exception is `real/`, a trimmed real
export (public by owner decision 2026-10-05) with its own README.
