# WP-1.9 — Precipitation and battery in the data

## Summary

Implements owner decision Q9 (2026-10-05): precipitation per interval, the cumulative
precipitation counter and the battery voltage are now part of the data, end to end.
`MeasurementSeries` has three optional `float64` columns (`precip_mm`, `precip_total_mm`,
`battery_v`, `NaN` when absent), and `DailyWeather` adds `precip_sum_mm` and `battery_min_v`.
The whole-row validity rule still concerns temperature and humidity only. The parsers read the
three columns of the real export through configurable aliases. A file without them stays
valid, and a problem in one of them is only a warning. The store writes the new layout
`timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source` and still reads old
files (tested on a committed old-layout sample). The column-wise merge treats the new columns
like temperature and humidity. Three new registered QC checks (`precip_range`,
`precip_counter`, `battery`) report events and **never set row flags**, so precipitation or
battery problems cannot invalidate temperature and humidity. Implausible precipitation values
can be set aside as `NaN` (`PrecipRangeCheck.set_aside`). The web contract accepts the optional
fields. The real-export regression test checks all six columns on hand-read rows.

## Changed files

Core:
- `src/sivin/core/schema.py`: `Column.PRECIP`, `PRECIP_TOTAL`, `BATTERY`; new constants
  `AUXILIARY_COLUMNS`, `VALUE_COLUMNS`, `CANONICAL_ORDER` (`REQUIRED_COLUMNS` and
  `OPTIONAL_COLUMNS` unchanged in meaning). Missing auxiliary columns are filled with `NaN` in
  the constructor. Given ones must be `float64` and finite or `NaN`. `from_records` gets the
  keyword-only arguments `precip_mm`, `precip_total_mm`, `battery_v`. The new
  `with_values(column, values)` replaces an auxiliary column only; temperature and humidity
  raise `SchemaError`. `complete_mask` is unchanged, and its docstring states that the
  auxiliary columns play no part.
- `src/sivin/core/daily.py`: `AUXILIARY_DAILY_COLUMNS = ("precip_sum_mm", "battery_min_v")`
  and `ALL_DAILY_COLUMNS`. `DAILY_COLUMNS` keeps its old meaning (temperature/humidity columns,
  required), so callers that build frames with `frame[list(DAILY_COLUMNS)]` (thermal test
  fixtures, `ripening/common.py`, `winter_freeze.py`) keep working. The constructor accepts
  frames without the new columns and fills them with `NaN`. The sum and minimum are taken over
  the same valid samples as temperature and humidity (`complete_mask`); `sum(min_count=1)`
  makes a day without any precipitation value `NaN`.

Ingest:
- `src/sivin/ingest/parsers/columns.py`: `CanonicalColumn.PRECIP`, `PRECIP_TOTAL`,
  `BATTERY`, plus `REQUIRED_CANONICAL_COLUMNS` and `OPTIONAL_CANONICAL_COLUMNS`. New
  `ColumnAliases` fields `precip_mm`, `precip_total_mm`, `battery_v`, `precip_units` (`mm`)
  and `battery_units` (`V`). `HeaderMatch.missing` lists required columns only. Problems with
  optional columns go to the new `optional_problems`, and such a column is dropped.
- `src/sivin/ingest/parsers/tabular.py`: reads the optional columns when mapped and passes them
  to `from_records`.
- `src/sivin/ingest/validation.py`: new `TableInspection.precip`, `precip_total`, `battery`,
  `optional_column_problems` and `auxiliary_columns`. New rules: `optional-columns` (WARNING),
  `precipitation-bounds`, `precipitation-total-bounds` and `battery-bounds` (gross bounds,
  always WARNING). `numbers-parseable` covers the optional columns, always as WARNING.
  `duplicate-timestamps` compares all value columns. The `short-rows` message now says "mapped
  column". New `ValidationSettings` fields: `precip_min_mm` 0, `precip_max_mm` 500,
  `precip_total_min_mm` 0, `precip_total_max_mm` 100 000, `battery_min_v` 0, `battery_max_v`
  10. `_ordered_bounds` checks all five pairs.

Storage:
- `src/sivin/storage/codec.py`: `STORED_COLUMNS` (new layout), `LEGACY_STORED_COLUMNS` and
  `READABLE_LAYOUTS`. `read` accepts both headers; `write` always uses the new one.
- `src/sivin/storage/merge.py`: `VALUE_COLUMNS = sivin.core.schema.VALUE_COLUMNS` (all five
  value columns merge by the same rules); `_series` carries the auxiliary columns.
- `src/sivin/storage/conflicts.py`: docstring of `ValueConflict.column` only.

Quality:
- `src/sivin/quality/checks/precip.py` (new): `PrecipRangeSettings`/`PrecipRangeCheck`
  (`precip_range`, with `out_of_range` and `set_aside`) and
  `PrecipCounterSettings`/`CounterSteps`/`PrecipCounterCheck` (`precip_counter`).
- `src/sivin/quality/checks/battery.py` (new): `BatterySettings`/`BatteryCheck` (`battery`).
- `src/sivin/quality/checks/range_check.py`: module docstring, and the helper `runs_of(mask,
  considered)`, which groups consecutive samples into event runs. `RangeCheck` is unchanged.
- `src/sivin/quality/checks/__init__.py`: imports and registration. The module docstring is
  deliberately unchanged to avoid a merge conflict with WP-1.8.
- `src/sivin/quality/events.py`: four new `EventKind` members (`precip_out_of_range`,
  `precip_counter_reset`, `precip_counter_mismatch`, `low_battery`). **Outside the listed
  Files scope**; see *Deviations*.

Web:
- `web/src/contract/types.ts`: optional `precip_mm?` and `battery_v?` on `RawMonthFile`, and
  `precip_sum_mm?` and `battery_min_v?` on `DailyFile`.
- `web/src/contract/validateSeries.ts`: `readOptionalColumns` validates a present field like
  the other nullable columns (length of `t`/`date`). An absent field is left out.
- `web/src/domain/**`: unchanged. `RawSeries.merge` already ignores unknown fields (tested).

Tests and fixtures:
- `tests/core/test_auxiliary_columns.py` (new); `tests/core/test_schema.py` and
  `tests/core/test_daily.py` (expected column lists).
- `tests/ingest/test_auxiliary_columns.py` (new, synthetic CSVs);
  `tests/ingest/test_real_export.py` (all six columns on five hand-read lines; ranges of the
  excerpt); `tests/ingest/test_validation.py` (rule list).
- `tests/storage/test_auxiliary_columns.py` (new); `tests/storage/test_codec.py`,
  `tests/storage/test_store.py` and `tests/storage/conftest.py` (new layout, legacy cases).
- `tests/fixtures/storage/legacy_layout/` (new): a **synthetic** old-layout store file with a
  README.
- `tests/quality/test_precip_battery.py` (new; synthetic and real excerpt);
  `tests/quality/test_base_and_events.py` (registered ids).
- `web/tests/contract.optional.test.ts` (new; a separate file so that it does not collide with
  WP-1.8's edits of `contract.test.ts`).

Docs: `docs/data-format.md`, `docs/storage.md` (section *Format change in WP-1.9*),
`docs/quality-control.md` (section *Precipitation and battery (WP-1.9)*, placed after `range`
so that it stays away from WP-1.8's edits), `docs/architecture.md` (schema table) and this
note.

## How it was verified

In `/home/user/wt/wp-1.9`:
- `make lint` → `All checks passed!`, `200 files already formatted`.
- `make type` → `Success: no issues found in 118 source files`.
- `make test` → `1388 passed` (baseline before the WP: 1314).
- `make cov` → total 99.93 %. Every changed or new module is at 100 % (statements and
  branches): `core/schema.py`, `core/daily.py`, `ingest/parsers/columns.py`,
  `ingest/parsers/tabular.py`, `ingest/validation.py`, `storage/codec.py`, `storage/merge.py`,
  `storage/conflicts.py`, `quality/checks/precip.py`, `quality/checks/battery.py`,
  `quality/checks/range_check.py`, `quality/checks/__init__.py` and `quality/events.py`.
- Web (`web/`): `npm run lint` clean, `npm run typecheck` clean, `npm test` → 15 files, 138
  tests passed (`validateSeries.ts` fully covered), `npm run build` OK.
- Real data: the **full** real export (3520 rows, outside the repository) parses without any
  finding; `precip_mm` 0.0–0.9 mm, `precip_total_mm` 323.0–326.4 mm, `battery_v` 3.0–3.7 V,
  matching the brief. On the committed excerpt: `precip_range` and `precip_counter` report
  nothing with the defaults. With a 0.05 mm tolerance, `precip_counter` reports exactly the
  0.1 mm rounding difference at 2025-12-19 14:07:16 local. `battery` reports one event for the
  two 3.0 V lines of 2025-07-30. Lines at exactly 3.30 V are not low, because the threshold is
  exclusive.
- Merge compatibility: `git merge-tree` of this branch with `wp/1.8-offsite-log` and with
  `wp/L.1-literature-verification` has no conflicts. The merged tree with WP-1.8, extracted to a
  scratch directory, passes the Python suite (1479 passed, 19 skipped) and the web typecheck
  and tests (152 passed).

## What did not work / what was not verified

- **No real rain.** The only real export was recorded indoors (Q10). Its precipitation values
  (0.3/0.9 mm) are probably handling of the gauge, so the range and counter checks have never
  seen outdoor rain. Their defaults (`precip_max_mm` 50 mm per interval, `tolerance_mm`
  0.15 mm, `max_interval_s` 2745 s) are project defaults **[to be tuned]**.
- **Counter semantics.** That `Srážky (mm)` is the counter increase since the previous sample
  is inferred from the 7 non-zero rows of the real export; it is not documented by the
  provider. A counter reset or overflow was never observed. Whether the device resets it (and
  to what) is unknown.
- **Battery threshold.** 3.3 V is a guess, and the device's cut-off voltage is unknown
  **[to be verified against the device data sheet]**.
- The **XLSX** export and the exports of the other sensors (Q11) were not available. The
  German and English aliases are guesses for other tools.
- The new checks are **not enabled by default** in `QualityPipelineSettings`, and `set_aside`
  is not applied in any pipeline, because `pipeline.py` is outside the scope (WP-1.8 is editing
  it). Until WP-1.7 wires them, implausible precipitation reaches `DailyWeather.precip_sum_mm`
  unfiltered.

## Deviations

1. **`src/sivin/quality/events.py` changed although it is not in the listed Files scope.**
   The checks need event kinds, and `QualityEvent.kind` is typed `EventKind`. There was no
   clean way inside the scope (a parallel enum would break the typing). The change is purely
   additive (four enum members), inserted away from WP-1.8's additions; `git merge-tree`
   confirms no conflict.
2. **Optional columns never reject a file.** The brief asks for "numbers parseable (warning
   share like other columns)". I report the same share in the same message, but cap the
   severity at WARNING for the auxiliary columns. The same applies to their gross bounds. The
   reason is Q9: validity concerns temperature and humidity only, and rejecting a file because
   of a broken rain gauge would throw away valid temperature and humidity. A column-level
   problem (unaccepted unit, two headers) drops only that column (`optional-columns`).
3. **Values outside the auxiliary gross bounds are read as missing** (round 2; temperature and
   humidity keep theirs for QC). The `*-bounds` WARNING says so ("read as missing"). A unitless
   `Battery` column in % therefore never becomes e.g. `battery_v = 85`.
4. **Mechanism for bad precipitation: set aside as `NaN` plus an event, no flag** (documented
   in `docs/quality-control.md`). A new flag bit would change the frozen `QcFlag` contract, and
   every consumer would have to remember to mask it.
5. **`DailyWeather` column constants**: `DAILY_COLUMNS` was not extended (it would break callers
   that select `frame[list(DAILY_COLUMNS)]`). The full list is the new `ALL_DAILY_COLUMNS`, and
   the new columns are optional on input.

## Out of scope

- **WP-1.7 (integration)**: (a) enable the checks: `quality.screening_checks: [missing,
  sampling, range, precip_range, precip_counter, battery]` with `check_settings` as in
  `docs/quality-control.md`; (b) apply `PrecipRangeCheck(...).set_aside(result.series)` after
  `QualityPipeline.run`, before daily aggregation and the site export; (c) configuration
  sections: `ingest.parsers.aliases` gains `precip_mm`, `precip_total_mm`, `battery_v`,
  `precip_units` and `battery_units`; `ingest.validation` gains the six bounds above; no new
  CLI command is needed.
- **WP-3.2 (SiteBuilder)** should write `precip_mm` and `battery_v` into `raw/<YYYY-MM>.json`,
  and `precip_sum_mm` and `battery_min_v` into `daily.json` (`null` for `NaN`), and decide
  whether the QC events of this WP go into `events/<id>.json`. Their `type` values are not in
  the web contract's `SENSOR_EVENT_TYPES`, so the web validator would reject them today.
- **`docs/web.md`** (not in scope) should mention the optional contract fields and their
  tolerant reading; proposed for **WP-3.2**.
- **MIGRATION_PLAN §2.6**: the `daily.json` example does not show `precip_sum_mm` and
  `battery_min_v`. Proposed plan addition: "optional, since WP-1.9".
- **Gap filling from the counter** (plan §2.5: the counter "serves to check and fill gaps") is
  not implemented. After a gap, the counter increase is the precipitation of the gap. Proposal:
  a later WP (e.g. with WP-2.5) adds an event or a daily correction from it.
- **`docs/storage.md` growth estimate** still uses the 1825 s interval of WP-1.4. I only added
  the size of the new fields.
- `sivin.quality.samples.Variable` and `SampleArrays` cover temperature and humidity only. The
  new checks read the frame directly, which is fine as long as only they use the auxiliary
  columns.

## Open questions for the owner

1. ~~Daily precipitation sum over which samples?~~ Decided by the orchestrator in round 2
   (reviewer's proposal): separate `auxiliary_exclude_mask`, default
   `PRE_DEPLOYMENT | MANUAL_EXCLUDE`; see *Round 2*. The owner may still change the default.
2. **Defaults to confirm or replace:** `precip_max_mm` = 50 mm per ~30 min interval,
   `low_battery_v` = 3.3 V, `tolerance_mm` = 0.15 mm. Is the device data sheet (rain gauge
   resolution, battery cut-off) available?
3. **Should a broken auxiliary column ever reject a file?** (Deviation 2.) Now never.
4. **`precip_total_mm` on the web**: the plan's contract carries only `precip_mm` and
   `battery_v` in the raw months, so the counter is not part of the web contract. Is that
   intended?

## Round 2 (changes after review round 1)

Merged `origin/wp/1.8-offsite-log` first (merge commit, no conflicts). Then:

- **major, daily auxiliary aggregates** (`core/daily.py`): `DailyWeather.from_series` takes
  `auxiliary_exclude_mask` (default `DEFAULT_AUXILIARY_EXCLUDE` = `PRE_DEPLOYMENT |
  MANUAL_EXCLUDE` = 288). `precip_sum_mm` sums every present `precip_mm` of the day not excluded
  by that mask, `battery_min_v` is the minimum over the same rows, and the new int64 column
  `precip_n_samples` counts the summed values so partial days are visible
  (`AUXILIARY_DAILY_COLUMNS` = `precip_sum_mm, precip_n_samples, battery_min_v`, still optional
  on input; `precip_n_samples` is filled with 0). The difference to the T/RH rule is documented
  in the `DailyWeather` docstring and `docs/architecture.md` (table "Samples used"). Tests: the
  reviewer's 6-sample example (6.0 mm, 3.1 V, while `n_samples` = 5), mask defaults,
  `auxiliary_exclude_mask=0` and `=DEFAULT_EXCLUDE`.
- **minor, out-of-bounds auxiliary values** (`ingest/validation.py`, `parsers/tabular.py`):
  read as missing; the WARNING message ends with "; read as missing". `assemble` takes the
  validator's `ValidationSettings` (new properties `precip_bounds_mm`, `precip_total_bounds_mm`,
  `battery_bounds_v`; helper `outside_bounds`). Test: unitless `Battery` with 85/3,6/84 →
  `[NaN, 3.6, NaN]` and one WARNING.
- **minor, event text** (`checks/precip.py`): the detail now ends "temperature and humidity are
  unaffected" and no longer claims a set-aside.
- **minor, battery flapping** (`checks/battery.py`): hysteresis. New setting
  `recovery_margin_v` = 0.1 V (*[to be tuned]*, 0 disables); `low_battery_episodes()` ends an
  episode only at a reading ≥ `low_battery_v + recovery_margin_v`. Tested by hand
  (3.6, 3.2, 3.3, 3.2, 3.35, 3.1, 3.4, 3.2 → two events instead of four).
- **minor, web** (`contract/validateSeries.ts`): a present but malformed optional field is
  dropped with a warning (`warn` parameter, default `console.warn`, same pattern as
  `parseEventsFile`); required columns stay strict. Tests with a collecting callback and with a
  `console.warn` spy.
- **minor, plan/docs**: MIGRATION_PLAN §2.6 is updated by the orchestrator; `docs/web.md` is
  listed for WP-3.2 under *Out of scope*.
- **nit, units**: `precip_units` = `mm`, `l/m²`, `l/m2` (tested).

Gates after round 2 (in `/home/user/wt/wp-1.9`, including WP-1.8): `make lint` → `All checks
passed!`, `211 files already formatted`; `make type` → `Success: no issues found in 127 source
files`; `make test`/`make cov` → `1506 passed`, total 99.91 %, every module changed by this WP
at 100 %. Web: lint and typecheck clean, `npm test` 15 files / 153 tests passed
(`validateSeries.ts` 100 %), `npm run build` OK.

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer agent, base `2f08446`, head `81ff791`.

### Gates observed

In `/home/user/wt/wp-1.9`:
- `make lint`: ruff check clean, `200 files already formatted`. `make type`: `Success: no issues
  found in 118 source files`. `make test`: `1388 passed`.
- `make cov`: TOTAL 99 % (7541 statements, 3 missed). Every module this WP changed is at 100 %
  (statements and branches).
- Web: `npm ci`, `npm run lint` clean, `npm run typecheck` clean, `npm test` 15 files / 138 tests
  passed, `npm run build` OK.
- Merge with `wp/1.8-offsite-log` (`c458c3e`): `git merge-tree --write-tree` is clean (tree
  `b602ac7`). The tree was extracted to `/tmp/claude-0/review-1.9/merged`, and there ruff check
  and `ruff format --check src tests` are clean, mypy reports `Success: no issues found in 127
  source files`, and pytest gives `1479 passed, 19 skipped`. The 19 skipped tests are
  `test_gitignore`, which needs a git checkout. The web gates on the merged tree are also green:
  lint, typecheck, 152 tests, build. WP-1.8 code builds no series from selected columns, so it
  does not drop the new columns.

### What I verified with my own scripts (`/tmp/claude-0/review-1.9/`, outside the repo)

- **Full real export** (3520 rows): accepted with no findings. All six columns are read with no
  NaN. `precip_mm` is 0.0–0.9, `precip_total_mm` 323.0–326.4 and `battery_v` 3.0–3.7. In all 7
  rain rows, the interval value equals the counter increase within 0.1 mm. The only difference
  is 0.3 vs 0.4 mm at 2025-12-19 13:07:16 UTC. With the defaults, `precip_counter` and
  `precip_range` report nothing, and `battery` reports one event (2 readings at 3.0 V,
  2025-07-30).
- **Storage, mixed scenario.** I wrote an old-layout file `2025.csv` (60 real rows, T/RH only,
  source `old`), read it (aux columns NaN), then appended the full real series. The result:
  `new_rows=3460, filled_values=180` (60 rows × 3 columns), no conflicts. Every value of all
  five columns equals the parsed series (`np.array_equal(..., equal_nan=True)`), so the merge is
  **lossless**. A repeated append writes no file and leaves the SHA-256 unchanged. Read →
  write is byte-identical for both rewritten partitions. The old file was rewritten in the new
  layout only because data changed, as `docs/storage.md` says.
- **Schema.** A frame without the aux columns gets NaN float64 columns, and the caller's frame
  is not mutated. `from_records` without the aux keyword arguments gives NaN. `with_values`
  keeps the flags and T/RH, refuses `temp_c`, and refuses `inf`.
- **Parsers (synthetic CSVs).** These variants are mapped: `srazky [MM]`, `CELKOVÉ SRÁŽKY` and
  `Nabiti baterie(V)`. `Baterie (%)`, `Precipitation (in)` and `Srážky (l/m2)` each drop only
  that column, with an `optional-columns` WARNING. Two precipitation headers drop that column.
  Unparseable aux cells give WARNINGs and NaN, and the file is accepted. A file without aux
  columns is accepted. Short rows without the battery cell give a `short-rows` WARNING and NaN.
  Reordered columns are read correctly.
- **QC.** A reset (10.4 → 0.3) is one info event with no mismatch. A decrease of 0.1 is neither
  a reset nor a mismatch. A difference of 0.1 from rounding is accepted, a difference of 0.2
  is a mismatch, and a step after a gap is not compared. `set_aside` changes only `precip_mm`,
  and `qc` and `complete_mask` are unchanged. All three checks return all-zero flags.
  Rounding argument: both columns are multiples of 0.1 mm and the true combined rounding error
  is below 0.15 mm, so a rounded difference can only be 0 or 0.1. The tolerance of 0.15 mm
  therefore separates rounding from a real mismatch.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `src/sivin/core/daily.py:185-189` | `precip_sum_mm` and `battery_min_v` are taken over `complete_mask(exclude_mask)`, i.e. only rows with valid T **and** RH. Rain in a row with missing T/RH or with a T/RH-only flag (`SPIKE`, `OUT_OF_RANGE`, `STUCK`, `MISSING`) is lost. A low battery reading in a row whose T/RH dropped out (the typical symptom of a failing battery) is hidden. This contradicts the spirit of Q9 ("the validity rule concerns T and RH only"). | fixed in round 2 (separate auxiliary mask, `precip_n_samples`) |
| minor | `src/sivin/ingest/validation.py:1225`, `:1302` | Aux values outside the gross bounds are kept (deviation 3). A battery column without a unit that holds percent (`Battery` = 85) is stored as `battery_v = 85.0` with only a `battery-bounds` WARNING, and `BatteryCheck` never reports it (85 > 3.3). | fixed in round 2 (read as missing) |
| minor | `src/sivin/quality/checks/precip.py:140` | The `precip_out_of_range` event detail says "set aside, temperature and humidity stay valid". Nothing applies `set_aside` in the pipeline yet (until WP-1.7), so the events file would claim a removal that did not happen, and the value reaches `precip_sum_mm`. | fixed in round 2 (neutral text) |
| minor | `src/sivin/quality/checks/battery.py:68` | No hysteresis and no minimum gap between events. With 0.1 V resolution and diurnal voltage swings, a battery near 3.3 V (3.3 ↔ 3.2) gives one `low_battery` event per dip, possibly daily, which is noise in `events/<id>.json`. | fixed in round 2 (hysteresis, `recovery_margin_v`) |
| minor | `web/src/contract/validateSeries.ts:62` (and the daily counterpart) | An optional field that is present but malformed (wrong length, a non-number, `null` instead of an array) makes the whole raw month or daily file fail, so its T/RH are not shown either. The owner approved "tolerant reading of optional contract fields". | fixed in round 2 (ignored with a warning) |
| minor | `MIGRATION_PLAN.md` §2.6 (line ~453), §4 WP-1.9 | The plan's `daily.json` example and the WP-1.9 task text do not mention `precip_sum_mm`/`battery_min_v`, which this WP adds to the web contract. `docs/web.md` (outside scope) does not mention the optional fields either. The plan text is consistent otherwise (§2.5 table and store header match the code). | plan: orchestrator; `docs/web.md`: listed for WP-3.2 under *Out of scope* |
| nit | `src/sivin/storage/merge.py:218` | When only precipitation is filled into an old-layout row, the row's `source` moves to the new export, so the T/RH of that row are attributed to an export that did not change them. This is the existing WP-1.4 rule, but after WP-1.9 it fires for every old row on the first import. | accepted (orchestrator) |
| nit | `src/sivin/ingest/parsers/columns.py:235` | `precip_units` accepts only `mm`. `l/m²` (equal to mm) would drop the column. Consider adding it if other devices use it (not observed). | fixed in round 2 (`l/m²`, `l/m2`) |
| nit | `web/tests/contract.optional.test.ts` | The test pins the message `$.battery_min_v must have 2 items like "t"` for a daily file, which is keyed by `date`. The message comes from the existing `FieldReader.list`. | accepted (orchestrator) |

### Details and suggested fixes

**Major: daily auxiliary aggregates over T/RH-valid rows.** Synthetic check: 6 samples on one
local day, `temp_c = [1, NaN, 3, 4, 5, 6]`, `precip_mm = [1, 2, 3, 0, 0, 0]`,
`battery_v = [3.6, 3.1, 3.6, …]`. `DailyWeather.from_series` gives `precip_sum_mm = 4.0`
(expected 6.0) and `battery_min_v = 3.6`, which hides the 3.1 V reading. The worker followed
the brief and raised it as open question 1, so the decision belongs to the orchestrator and the
owner. My assessment: rain does not stop being rain because the humidity sensor glitched. The
only rows that must be excluded are those **not at the site** or excluded by hand. Proposal:

- `from_series` takes a second mask `auxiliary_exclude_mask`. Its project default is
  `PRE_DEPLOYMENT | MANUAL_EXCLUDE`, i.e. location and manual flags only, not
  `MISSING`/`SPIKE`/`OUT_OF_RANGE`/`STUCK`, which describe T/RH.
- `precip_sum_mm` = sum of present `precip_mm` over `valid_mask(auxiliary_exclude_mask)`,
  with NaN if there is none.
- `battery_min_v` = minimum over all present `battery_v` of the day. Battery is a property of
  the device, so it should not depend on the location either. At most, use the same auxiliary
  mask.
- The rain sum also needs its own completeness measure. A day with 10 % T/RH coverage now
  shows a small "sum" with nothing to mark it partial. Add `precip_n_samples` (or a
  `precip_coverage`), or document that the counter difference over the day is the robust
  alternative (follow-up, see *Out of scope*, gap filling).
- Document it in the `DailyWeather` docstring, `docs/architecture.md` and
  `docs/quality-control.md`.

If the owner explicitly confirms the current semantics, this finding drops to resolved.

**Minor: battery percent column.** Input: header `Battery` with values `85`. Result: stored
`battery_v = 85.0`, a WARNING only. Fix: since the aux bounds rules can never reject, let them
**read out-of-bounds aux values as missing** (with the WARNING saying so), or narrow the
battery alias without a unit. The same idea would apply to negative precipitation outside the
gross bounds.

**Minor: event text.** Make the detail neutral (e.g. "…outside […] mm per interval;
temperature and humidity unaffected"), or let `set_aside` say what it removed. Alternatively,
state in the hand-off that WP-1.7 must apply `set_aside` before any events are published.

**Minor: battery flapping.** Merge low runs separated by less than a configurable
`merge_gap_s` (e.g. 24 h, project default [to be tuned]), or use hysteresis (`recover_v`).

**Minor: web tolerance.** In `readOptionalColumns`, catch a `ContractError` for an optional
field, drop that field and warn on the console. Required columns stay strict.

### Deviations assessment

1. **`quality/events.py` outside the Files scope.** Accepted. The change is four purely
   additive enum members, and a parallel enum would break the typing of `QualityEvent.kind`.
   `git merge-tree` with WP-1.8 is clean, and the merged gates are green. The owner should note
   that these `type` values are not yet in the web's `SENSOR_EVENT_TYPES` (WP-3.2 must filter
   or extend them).
2. **Aux problems never reject a file.** Accepted. This is consistent with Q9. Verified: the
   column is dropped (unit or ambiguity) or its cells become NaN (unparseable), with a WARNING
   in the validation report. Note that WARNING-severity issues are logged at INFO by the
   existing `InputValidator` convention. They reach the report and the run record, not the
   WARNING log level.
3. **Out-of-bounds aux values kept.** Partly accepted. Precipitation is covered by
   `precip_range` once wired. For battery, see the minor finding above.
4. **Set aside as NaN, not a flag.** Accepted as a design: it keeps the frozen `QcFlag`
   contract, and `with_values` is restricted to aux columns (verified). Risk: until WP-1.7
   wires it, nothing applies it. This is stated in the hand-off.
5. **`DAILY_COLUMNS` unchanged, new `ALL_DAILY_COLUMNS`.** Accepted. Existing callers
   (`frame[list(DAILY_COLUMNS)]` in the thermal fixtures, ripening, winter freeze) keep working
   (full suite green). Frames without the aux columns construct a `DailyWeather` with NaN.

### Round 2

Verdict: APPROVE (round 2)

Reviewed head `00d092e`. It includes the merge `43a028a` of `origin/wp/1.8-offsite-log`
(`c458c3e`). The merge commit has both parents. Against WP-1.8 it changes only the 35 files of
this WP, so no WP-1.8 file was altered.

**Gates observed** in `/home/user/wt/wp-1.9`:
- **Python:** `make lint` (ruff clean, 211 files formatted). `make type`: `Success: no issues
  found in 127 source files`. `make test`: `1506 passed`. `make cov`: TOTAL 99 %. `daily.py`,
  `tabular.py`, `validation.py`, `battery.py` and `precip.py` are each at 100 %.
- **Web:** `npm ci`, `npm run lint` (exit 0), `npm run typecheck` (exit 0), `npm test` with 15
  files / 153 tests passed, `npm run build` OK.

**Probes re-run** (`/tmp/claude-0/review-1.9/`):
- **Full real export (3520 rows):** accepted with no findings, all six columns read. Counter and
  range checks report nothing with the defaults. The battery check gives one event (2 readings
  at 3.0 V).
- **Mixed storage scenario** (old-layout file of 60 rows, then the full import): `new_rows=3460,
  filled_values=180`, no conflicts. All five value columns equal the parsed series, so nothing
  is lost. A repeated append writes nothing and the SHA-256 is unchanged. Read → write is
  byte-identical for both partitions.
- **Off-site exclusion after the WP-1.8 merge:** I ran the real export through
  `QualityPipeline` with the committed `sensors/offsite_log.yaml`.
  - All 3520 rows get `PRE_DEPLOYMENT`, and `DailyWeather.from_series` (default auxiliary mask)
    gives **no** `precip_sum_mm`, `battery_min_v` or precipitation count on any day.
  - With the period shortened to end at 2025-12-19 00:00, no day before 2025-12-19 has
    precipitation. The days after it show hand-checked sums: 2025-12-19 = 1.5 mm
    (0.3 + 0.9 + 0.3), 2025-12-21 = 0.3 mm, 2026-02-09 = 0.9 mm.
  - A `SPIKE` flag on a rainy row lowers `n_samples` (47 → 46) but keeps `precip_sum_mm = 1.5`
    and `precip_n_samples = 47`.
- **Round-1 example:** a row with T missing now counts. `precip_sum_mm` is 6.0 (was 4.0) and
  `battery_min_v` is 3.1 V (was 3.6).
- **Parsers:**
  - A unitless `Battery` column with values of 85 now becomes NaN with a `battery-bounds`
    WARNING.
  - Negative precipitation becomes NaN.
  - `Srážky (l/m2)` is accepted.
  - The other variants behave as in round 1.
- **Battery hysteresis:** for the readings 3.3, 3.2, 3.3, 3.2, 3.3, 3.2, 3.4, 3.2 with
  threshold 3.3 V and recovery 3.4 V, the result is 2 episodes, `((1, 5), (7, 7))`, instead of
  one event per dip.
- **Event text:** the `precip_range` detail is now neutral.

**Status of the round-1 findings:**

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `src/sivin/core/daily.py` | Auxiliary daily aggregates were taken over T/RH-valid rows | resolved: `auxiliary_exclude_mask`, default `PRE_DEPLOYMENT \| MANUAL_EXCLUDE` (owner/orchestrator decision), `precip_n_samples`; off-site exclusion verified after the WP-1.8 merge |
| minor | `src/sivin/ingest/parsers/tabular.py`, `validation.py` | Out-of-bounds aux values were kept | resolved: read as missing, with a WARNING |
| minor | `src/sivin/quality/checks/precip.py` | Event text claimed a set-aside | resolved |
| minor | `src/sivin/quality/checks/battery.py` | Battery flapping | resolved: hysteresis, `recovery_margin_v` 0.1 V [to be tuned] |
| minor | `web/src/contract/validateSeries.ts` | A malformed optional field rejected the whole file | resolved: field ignored with a warning, required fields stay strict |
| minor | `MIGRATION_PLAN.md` §2.6 | `daily.json` example lacked the new fields | resolved outside this branch: orchestrator commit `ec3f11f` (not yet on `origin/main` at review time) |
| nit | `src/sivin/storage/merge.py:218` | `source` of an old row moves to the new export when only precipitation is filled | open (existing WP-1.4 rule; accepted) |
| nit | `src/sivin/ingest/parsers/columns.py` | `l/m²` not accepted | resolved |
| nit | `web/tests/contract.optional.test.ts` | Message `like "t"` for daily files | open (existing `FieldReader` text, outside scope) |

**New observations (round 2):**

| Severity | File:line | Finding | Status |
|---|---|---|---|
| nit | `src/sivin/core/daily.py` / plan §2.6 | `precip_n_samples` exists in `DailyWeather` but not in the web `daily.json` contract. WP-3.2 should decide whether to publish it, so the portal can mark partial rain days. | open (follow-up) |
| nit | `docs/wp_log/WP-1.9.md` | The worker edited the Status column of the round-1 review table. The statuses are correct (verified above), but per the reviewer role, review statuses should be set by the reviewer. | open (process note) |

No blockers or majors remain.
