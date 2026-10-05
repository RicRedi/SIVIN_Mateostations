# WP-1.2 — Export parsing and input validation

## Summary

This WP turns every export format the project has used into validated `MeasurementSeries`,
and it rejects bad files with a full report instead of importing them.

- `ExportParser` is an ABC with a `ParserRegistry` that picks the parser by `can_parse`
  (ambiguity is an error). There are three registered parsers: `PortalCsvParser`,
  `PortalXlsxParser` and `LegacyWorkbookParser`. They share one template,
  `TabularExportParser`, and one reading class, `TabularExportReader`: header search, column
  aliases, decimal-comma numbers, local timestamps, row order, local → UTC and series
  assembly.
- `InputValidator` runs 16 registered `ValidationRule` classes, one class per rule, over an
  `ExportInspection` and returns a frozen `ValidationReport`. A file with an ERROR yields
  `series == ()`. Parsers never raise because of file content.
- Rows that step back in time (device clock correction, overlapping exports) are handled by a
  `RowOrderAnalyser` with the `OrderRepair` strategy `SplitAtBackwardSteps`, so one clock
  correction never rejects a file. A table is reversed only when it is clearly newest first.
- Fixtures are synthetic and generated deterministically. `docs/data-format.md` documents the
  formats and states prominently that they are not verified on a real export (Q1/Q2).

## Changed files

- `src/sivin/ingest/validation.py`: `Severity`, `ValidationIssue`, `ValidationReport`,
  `ValidationSettings`, the inspection value objects (`ExportInspection`, `TableInspection`,
  `TimeColumn`, `ValueColumn`), `ValidationRule`/`TableRule`, `ValidationRuleRegistry`
  (`validation_rules`), `InputValidator` and the 16 rules.
- `src/sivin/ingest/parsers/__init__.py`: importing it registers the parsers.
- `src/sivin/ingest/parsers/base.py`: `ExportParser`, `ParsedExport`, `ParserRegistry`
  (`parser_registry`), `UnsupportedExportError`, `AmbiguousExportError`.
- `src/sivin/ingest/parsers/columns.py`: `CanonicalColumn`, `ColumnAliases`, `ParserSettings`,
  `ColumnMapping`, `HeaderCell`, `HeaderMatch`, `normalize_label`, `normalize_unit`.
- `src/sivin/ingest/parsers/cells.py`: `NumberParser`, `TimestampParser`.
- `src/sivin/ingest/parsers/sources.py`: `CellGrid`, `CsvGridReader`, `WorkbookReader`,
  `GridReadError`.
- `src/sivin/ingest/parsers/order.py`: `RowOrder`, `OrderRepair`, `SplitAtBackwardSteps`,
  `RowOrderAnalyser`.
- `src/sivin/ingest/parsers/tabular.py`: `SensorTable`, `LoadedTables`,
  `TabularExportReader`, `TabularExportParser`.
- `src/sivin/ingest/parsers/portal.py`: `PortalCsvParser`, `PortalXlsxParser`,
  `is_portal_export_name`, `sensor_from_file_name`.
- `src/sivin/ingest/parsers/legacy.py`: `LegacyWorkbookParser`.
- `tests/ingest/**`: 11 test modules and `conftest.py`.
- `tests/fixtures/exports/**`: `make_fixtures.py`, `README.md` and 18 generated files.
- `docs/data-format.md`, `docs/wp_log/WP-1.2.md`.
- A merge of `wp/0.1-foundation` (8f354c0, the final converter), as the orchestrator asked.

## Public API

```python
# sivin.ingest.parsers.base
parser_registry.for_file(path, settings=None, validator=None) -> ExportParser
class ExportParser(ABC): format_id; __init__(settings=None, validator=None)
    can_parse(path) -> bool; parse(path) -> ParsedExport
@dataclass(frozen=True) class ParsedExport: series: tuple[MeasurementSeries, ...]; source: Path;
    report: ValidationReport; is_accepted
# sivin.ingest.parsers.columns
class ParserSettings(BaseModel): source_timezone, aliases: ColumnAliases, header_search_rows,
    day_first, newest_first_min_share, csv_delimiter, csv_encodings, legacy_sheet_sensors
# sivin.ingest.validation
class InputValidator: __init__(settings=None, rules=None); validate(inspection) -> ValidationReport
class ValidationReport: issues; is_acceptable; errors; warnings; rules(severity=None); summary()
class ValidationIssue: rule, severity, message, row=None, table=None
class ValidationSettings(BaseModel)   # thresholds, see docs/data-format.md
validation_rules: ValidationRuleRegistry   # @validation_rules.register
```

## How it was verified

All commands ran in `/home/user/wt/wp-1.2` after merging `wp/0.1-foundation` at 8f354c0, with
ruff 0.16.10, mypy 2.4.0, pandas 3.0.6 and openpyxl 3.1.5:

- `make lint` → `All checks passed!`, `56 files already formatted`.
- `make type` → `Success: no issues found in 30 source files`.
- `make test` → `321 passed`.
- `make cov` → `TOTAL 1785 0 346 0 100%`, `Required test coverage of 85% reached`.
- Coverage of the code this WP adds (`pytest --cov=sivin.ingest`) is `TOTAL 942 0 160 0 100%`.
  This is statement and branch coverage.
- Every validation rule has a test with a broken file or a constructed inspection:
  - fixtures in `broken/` cover `file-not-empty`, `data-rows`, `required-columns` (missing
    humidity, °F header), `humidity-fraction`, `numbers-parseable`, `timestamps-parseable`,
    `temperature-bounds` (Kelvin), `sensor-id` (`export.csv`), `file-readable` (truncated
    XLSX), `short-rows` (truncated CSV), `duplicate-timestamps` and `backward-steps`;
  - `tmp_path` files cover `file-exists`, `expected-tables` and `humidity-bounds`;
  - `daylight-saving` uses the DST fixture.
- DST: the fixture covers the 2026-10-25 fall-back with 12 samples every 1825 s. The UTC
  result equals the hand-computed `22:00:13Z + k·1825 s` and is strictly increasing. Exactly
  the 4 rows in the repeated hour carry `TIMESTAMP_SUSPECT`. The same file written newest
  first gives the identical result.
- Order repair, with hand-computed UTC:
  - a 30 s backward clock correction keeps all 5 rows, sorted;
  - two overlapping exports concatenated keep one copy of each instant (the last);
  - a clearly newest-first file is reversed;
  - a mixed-order file is not reversed and is converted in 3 segments.
- Robustness (`tests/ingest/test_robustness.py`, fixed seeds): 4 × 60 byte-damaged copies of
  the valid CSV, XLSX, legacy workbook and DST fixture, plus 40 random cell grids written as
  CSV and as portal and legacy workbooks. No exception was raised, accepted series are
  monotonic and rejected files carry no series.
- `test_fixtures.py` regenerates all fixtures and compares them with the committed files:
  CSV byte for byte, workbooks cell by cell. `git check-ignore --no-index` confirms that none
  of the fixture files is ignored.

## What did not work / what was not verified

- **No real export was available.** The column names, the title row, the XLSX layout, the
  row order (oldest or newest first) and the decimal format are all reconstructed from legacy
  code (Q1). The source time zone `Europe/Prague` is unconfirmed (Q2).
- The Windows-1250 CSV fallback, the default thresholds (5 % shares, −60/70 °C,
  RH ≤ 1 % as a fraction, newest-first share 0.9) and the alias lists are project
  assumptions marked `[to be verified]`.
- A °F temperature column with plausible-looking values (e.g. a winter export, 30–45 °F) and a
  header without a unit is not detected. It is caught only through its header or when more
  than 5 % of the values exceed 70.
- `mypy` has no stubs for openpyxl (`types-openpyxl` is not a dependency). The import in
  `sources.py` carries the targeted `# type: ignore[import-untyped]`, so the openpyxl calls
  are typed as `Any`.
- The parsers were not run against the legacy `data.xlsx` of the owner (not in the
  repository).

## Decisions and deviations from the brief

1. **`MISSING` only when both values are missing.** The brief says "set `MISSING` for NaN
   values". Because `qc` is one flag per row and `MISSING` is in the default exclusion mask,
   flagging a row for a missing humidity would also exclude its valid temperature from the
   indices. That is the problem the WP-0.1 review raised as a major finding. `NaN` already
   marks a missing value per variable, and `DailyWeather` ignores it per variable. The policy
   is one line in `TabularExportReader.assemble`. See open question 1.
2. **Duplicates keep the last row** (orchestrator instruction; `from_records` behaviour). The
   count and the number of conflicting duplicates are reported as a WARNING.
3. **Order repair** (orchestrator follow-up): the brief's "non-monotonic order" rule is now
   `backward-steps`. It is detected **before** conversion on the rows outside daylight-saving
   hours, and it reports the count and the first 10 source rows. The chosen repair is
   **split into monotonic segments**: no row is dropped, and the converter is called once per
   segment. Reversal only happens when ≥ `newest_first_min_share` (0.9) of the steps go back in
   time.
4. **Unresolved daylight-saving rows are dropped** (orchestrator instruction). The count is in
   the `daylight-saving` WARNING.
5. **Additions to the briefed shapes:**
   - `ValidationIssue.table` (the worksheet the issue concerns);
   - `ValidationReport.errors`, `.warnings`, `.rules()` and `.summary()`;
   - `ParsedExport.is_accepted`;
   - `ParserRegistry.for_file(path, settings=None, validator=None)`, because the parsers need
     settings;
   - `ParserSettings` fields beyond the four in the brief: `newest_first_min_share`,
     `csv_delimiter`, `csv_encodings`, `legacy_sheet_sensors`;
   - extra rules `expected-tables`, `short-rows`, `daylight-saving` and `humidity-fraction`
     (the brief's "RH in 0–1" guard).
6. **`can_parse` uses the file name only**, so the decisions are cheap and do not overlap:
   - `portal-csv` takes any `*.csv`;
   - `portal-xlsx` takes a workbook whose name starts with `MeteoData` or names a sensor;
   - `legacy-workbook` takes any other workbook, but only when a sheet mapping is configured.

   A workbook with an unknown name and no mapping raises `UnsupportedExportError` from
   `for_file`. This is not a content problem, so the caller should quarantine the file.
7. **The sheet → sensor mapping** can be passed as the constructor argument `sheet_sensors`
   or as `ParserSettings.legacy_sheet_sensors`. The setting lets the registry build the parser
   from settings alone.
8. **A unit qualifier on the timestamp header** (e.g. `Datum a čas (UTC)`) is rejected by
   default (`ColumnAliases.timestamp_units = ()`), so a UTC export is never read as local
   time.

## Out of scope

- `pyproject.toml`: add `types-openpyxl` to the `dev` extra, so that the targeted
  `type: ignore` in `src/sivin/ingest/parsers/sources.py` can be removed.
- WP-1.7 (integration): wire `ParserSettings` as `ingest.parsers` and `ValidationSettings` as
  `ingest.validation` into `SivinConfig` and `config/sivin.yaml`. Proposed CLI:
  `sivin ingest validate <file>...`, which prints `ValidationReport.summary()` per file and
  exits non-zero on errors, and `sivin ingest import <file>...`. The legacy sheet mapping
  should be built from the sensor registry (WP-1.1, 4-digit suffix → serial) rather than
  typed into YAML.
- WP-1.4: store `ValidationReport.issues` of every file in `data/runs/<date>.jsonl`, and
  quarantine rejected files. `UnsupportedExportError` should be quarantined as well.
- `.gitignore`: `!/tests/fixtures/**` also re-includes `__pycache__/` below `tests/fixtures/`.
  The tests therefore load `make_fixtures.py` without writing bytecode. A rule
  `/tests/fixtures/**/__pycache__/` after the negation would make this robust.
- The `ParserRegistry` and `ValidationRuleRegistry` repeat the `IndexRegistry` pattern. The
  generic `Registry[T]` proposed in WP-0.1 would serve all three.

## Open questions for the owner

1. Should a row with only one missing variable carry `MISSING` (brief wording, but it excludes
   the other, valid variable from indices) or not (implemented)? The alternative is
   per-variable QC flags in the contract (WP-0.1 open question 5).
2. Q1: please provide a real portal export (XLSX straight from the download, plus a CSV if
   one exists). We need it to confirm the title rows, the column names, the row order, the
   number format and whether there are further columns.
3. Q2: are the export timestamps local time with daylight saving or UTC? Does the device clock
   get corrected (backward steps)?
4. Are the validation thresholds acceptable as starting values: 5 % unparseable values or
   timestamps, 5 % out of bounds, −60/70 °C gross temperature bounds?

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer agent. Reproduction scripts are outside the repository in
`/tmp/claude-0/review-1.2/` (`t1.py` to `t8.py`, helper `h.py`).

### Gates observed

- `make lint` → `All checks passed!`, `56 files already formatted`.
- `make type` → `Success: no issues found in 30 source files`.
- `make test` → `321 passed`.
- `make cov` → `TOTAL 1785 0 346 0 100%`, `Required test coverage of 85% reached`.
- Scope: `git diff --name-only wp/0.1-foundation...HEAD` touches only files in the WP-1.2 Files
  scope (plus the merge of `wp/0.1-foundation`). No shared file was changed.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| blocker | `src/sivin/ingest/parsers/order.py:83-89`, `:131-149` | Order repair cannot see backward steps between a daylight-saving row and an ordinary row. The DST hour can then be resolved wrongly and fabricated instants are imported. | open |
| major | `src/sivin/ingest/validation.py` (no rule) | A file without any measured value is accepted with **no findings**. Examples are an empty temperature column, an empty file body below a valid header, or an XLSX with formulas and no cached values. | open |
| major | `src/sivin/ingest/parsers/cells.py:103-105` | An XLSX integer cell too large for a float crashes `parse` with `OverflowError`. This breaks the acceptance criterion "no file content can crash the parser". | open |
| major | `src/sivin/ingest/validation.py`, `parsers/order.py` | There is no plausibility check on timestamps. After a clock reset, rows are imported at 1999. Rows in 2099 are accepted with no findings. | open |
| minor | `src/sivin/ingest/parsers/order.py:83-89` | An overlap that starts before the fall-back drops the whole repeated hour (6 rows), even though either export alone could be resolved. No `backward-steps` warning is given because the step goes from a DST row to an ordinary row. This has the same root cause as the blocker. | open |
| minor | `src/sivin/ingest/parsers/cells.py:39-45`, `columns.py:179` | A day/month swap is undetectable. A month-first file (`1/5/2026`) whose days are all ≤ 12 is read silently as day-first, with month-long steps between consecutive samples. | open |
| minor | `src/sivin/ingest/validation.py:160-212`, `columns.py:186` | The share thresholds behave badly on short files. One footer or comment row in a file with fewer than 20 rows rejects the file (more than 5 %). A newest-first file of about 10 rows with one irregular step falls below 0.9 and is not reversed, which leads into the blocker. | open |
| nit | `src/sivin/ingest/parsers/cells.py:122-124` | The docstring says date-only cells are unparseable. openpyxl returns `datetime(2026, 1, 5, 0, 0)` for a date cell, and it is accepted as local midnight. | open |
| nit | `src/sivin/ingest/validation.py:672` | Extra worksheets of a portal XLSX are reported as "without a sensor mapping". The message is meant for the legacy parser. | open |
| nit | history (`e03c8bb`, `895294e`) | `tests/fixtures/exports/__pycache__/make_fixtures.cpython-312.pyc` was committed in e03c8bb and removed in 895294e. The branch is unpushed, so squash or rewrite before the merge so the binary is not in the history. | open |

#### Details

**Blocker: DST rows mis-assigned after order repair.** `SplitAtBackwardSteps.segments` and
`RowOrderAnalyser.is_newest_first` compare only *ordinary* rows, which excludes rows in a
daylight-saving hour. A step from an ambiguous row (02:xx) back to an ordinary row (01:xx) is
therefore not a split point. The converter (WP-0.1) groups ambiguous rows per local date across
the ordinary rows between them. It then reads the one backward jump between the two exports as
the clock switch.

- Input (oldest first, 1825 s, export 1 ends inside the summer half of the repeated hour on
  2026-10-25, export 2 starts at 01:33): `… 01:33:08; 02:03:33; 02:33:58; 01:33:08; 02:03:33;
  02:33:58` with T = 0.7, 0.8, 0.9, 0.7, 0.8, 0.9.
- Result: the file is accepted. The only findings are `duplicate-timestamps` (1 row) and
  `daylight-saving` with "0 unresolved row(s) dropped". There is no `backward-steps` warning.
  The series holds **two fabricated rows**, 01:03:33Z (T = 0.8) and 01:33:58Z (T = 0.9). These
  are copies of 00:03:33Z and 00:33:58Z placed one hour late. They carry only
  `TIMESTAMP_SUSPECT`, which does not exclude them from indices.
- Same root cause for a newest-first table that is not reversed because its share is below
  0.9. Example: `02:33:58; 02:03:33; 01:33:08; …; 22:00:13; 22:30:38; 22:00:13` gives
  02:03:33 → 01:03:33Z, which is one hour late.
- An exhaustive check over two overlapping chunks of 24 samples across the fall-back, in both
  directions (5,152 files), found 25 files with a wrongly timed row. 2 were oldest first and 23
  newest first.
- Fix:
  - Treat as a split point every step whose wall clock goes back, except a step between two
    ambiguous rows of the same transition. Examples are ambiguous → ordinary
    (02:33 → 01:33) and ordinary → ambiguous (03:05 → 02:04). Count these steps in
    `is_newest_first` too.
  - Additionally, in a table that needed repair, mark as unresolved (and so drop and count)
    any ambiguous group whose segment does not contain ordinary rows on both sides of the
    transition.
  - Add the two inputs above as tests.

**Major: no "values present" rule.** Three cases from `t1.py` and `t2.py`:

- `Datum a čas;Teplota (°C);Vlhkost (%)` with every temperature cell empty → accepted, "no
  findings". A whole series with `temp_c = NaN` is imported.
- Both columns empty → accepted, "no findings". Every row carries `MISSING`.
- An XLSX whose value cells are formulas without cached values (a workbook saved by openpyxl
  or a script) → accepted, "no findings", every value is NaN.

§2.7 requires that a file is not empty. A file with timestamps and no measurements is empty
for this project. Fix: add a registered rule such as `values-present`. It gives an ERROR when a
required variable has no present value, and a WARNING (or a configurable ERROR) when the share
of missing values in a column exceeds a threshold. Add a fixture with a formula workbook.

**Major: crash on an oversized integer cell.** A sheet XML cell `<v>999…9</v>` with 400 digits
makes openpyxl return a Python `int`. `float(cell)` then raises `OverflowError` out of
`PortalXlsxParser.parse`. Excel does not write such a cell, but a damaged or hand-made file
can. Fix: wrap `float(cell)` in a `try`/`except OverflowError` that returns `None`, and add the
case to the robustness test (`t8.py` builds the file).

**Major: timestamp plausibility.**

- A clock reset in the middle of a file (`… 2026-03-01 02:00:07; 2000-01-01 00:00:00; 2000-01-01
  00:30:25; 2026-03-01 03:00:07 …`) → accepted. Two rows are imported at
  `1999-12-31 23:00Z` and `23:30:25Z`, with only a `backward-steps` WARNING.
- A row dated 2099-01-01 → accepted, "no findings".

Requirement (b) says a backward step must not reject the file. It does not say that implausible
instants should be imported. Fix: add `ValidationSettings` bounds such as `earliest_timestamp`
(e.g. the project start) and `max_future_s` relative to the file's mtime or the run time. Rows
outside the bounds are dropped and counted (WARNING), or the file gets an ERROR when their share
is large. Optionally, the repair strategy could drop a segment that starts with a backward step
larger than a configurable `max_backward_step_s`.

**Minor: lost repeated hour.** `… 01:33:08; 02:03:33S; 02:33:58S; 01:33:08; 02:03:33;
02:33:58; 02:04:23; 02:34:48; 03:05:13 …` → all 6 ambiguous rows are dropped as unresolved. The
loss is reported, so no data is wrong. The fix for the blocker (splitting at 02:33 → 01:33)
makes the second export resolvable.

**Minor: day/month swap.** This is a documented assumption (`day_first`). A cheap guard would
compare the median step between consecutive timestamps with the expected sampling interval
(~1825 s). Steps of about a month mean swapped day and month.

### Verified and correct

- **BOM and encodings.** A UTF-8 BOM with and without the title row, and cp1250, read
  correctly. UTF-16 is rejected loudly (NUL characters).
- **Rejected loudly with a clear ERROR:**
  - thousands separators `1.234,5`, and `1 234,5` caught by the bounds rule;
  - extra columns (dew point, pressure, battery) are ignored correctly;
  - a header below row 10;
  - a comma-delimited CSV;
  - an `.xlsx` that is really a CSV (`BadZipFile` → `file-readable`);
  - an Excel serial number as a timestamp;
  - a `(UTC)` timestamp header;
  - ISO strings with `Z` or an offset;
  - AM/PM.
- **Excel cells.** Excel datetime cells and day-first strings (`5.1.2026 17:33:01`) give the
  same UTC result: 2026-01-05 16:33:01Z, hand-computed for CET = UTC+1. Merged title cells work.
- **One year at 1825 s (17,280 rows)** rendered in Europe/Prague local time:
  - CSV parses in 0.23 s and XLSX in 0.38 s;
  - all 17,280 UTC instants equal the generating UTC grid exactly, with no loss and no
    duplicates;
  - exactly the 4 rows of the repeated hour on 2026-10-25 are `TIMESTAMP_SUSPECT`;
  - the same file written newest first gives an identical series.
- **DST fixture, hand-computed.** 00:00:13 CEST is 22:00:13Z on the 24th. 02:01:53 CEST is
  00:01:53Z. 02:02:43 CET is 01:02:43Z (= 00:32:18Z + 1825 s). The test expectations match.
- **Requirement (a).**
  - Rows are processed oldest first, and a table is reversed only above the share.
  - NaT rows are dropped before `from_records` and counted in `timestamps-parseable`.
  - Unresolved and collided rows are dropped and counted in `daylight-saving`.
- **ERROR files yield `series == ()`.** This is enforced in `ParsedExport.__post_init__`.
- **Severities are sensible:** structural problems are ERRORs; duplicates, backward steps, DST,
  short rows and small shares are WARNINGs.
- **Standards.** The design follows the OOP and registry rules. There are no prints and no
  `Any`/`cast` escapes. The only `type: ignore` is the targeted openpyxl one. NumPy docstrings
  carry units. Fixtures are labelled SYNTHETIC. The docs carry the "not verified" note.

### Deviations assessment

1. **MISSING only when both values are missing: agree.** WP-0.1 aggregates T and RH
   independently over non-NaN values (`daily.py:141-148`). Setting `MISSING` on a row for a
   missing RH would exclude a valid temperature through the default exclusion mask. NaN
   already marks a missing value per variable. The open question to the owner is the right
   follow-up.
2. **Duplicates keep the last row: agree.** This matches the orchestrator's instruction and
   `from_records`. Conflicting duplicates are counted.
3. **Split into monotonic segments: acceptable as a strategy.** It is deterministic, drops no
   row, and never rejects a file. However, the detection is incomplete (blocker) and the size
   of a step is not bounded (major on plausibility).
4. **Dropping unresolved DST rows: agree.** This is per the orchestrator, and the rows are
   counted.
5. **Additions to the briefed shapes: fine.** They are small and documented.
6. **`can_parse` by file name only: acceptable.** Any `.csv` goes to `portal-csv`. A foreign
   CSV is then judged by content: a wrong delimiter or unknown headers give an ERROR, and a name
   without a serial gives a `sensor-id` ERROR. So misrouting is loud, not silent. The cases are
   these:
   - A non-portal CSV with `;`, matching aliases and a serial in its name would be imported.
     This is acceptable, because it is valid data for that sensor.
   - A workbook named after a sensor is read as a portal XLSX, first sheet only. The other
     sheets are reported.
   - Document in `docs/data-format.md` that routing never sniffs content.
7. **The sheet mapping in the constructor or the settings: agree.**
8. **Timestamp unit qualifiers rejected by default: agree.** This is a good guard against
   reading UTC exports as local time.
