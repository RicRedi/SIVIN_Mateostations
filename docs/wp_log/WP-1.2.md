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

Verdict: _pending_
| Severity | File:line | Finding | Status |
|---|---|---|---|
