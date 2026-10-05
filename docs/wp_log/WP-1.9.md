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
3. **Values outside the auxiliary gross bounds are kept**, as for temperature and humidity, and
   left to QC. For precipitation, `precip_range` catches them. For the battery, nothing removes
   e.g. a millivolt column; it only gives a `battery-bounds` warning.
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
- **`docs/web.md`** (not in scope) should mention the optional contract fields.
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

1. **Daily precipitation sum over which samples?** Now: over the same valid samples as
   temperature and humidity (as the brief says). As a result, rain recorded in a sample without
   temperature or humidity, or in an excluded sample (e.g. `SPIKE` in temperature,
   `PRE_DEPLOYMENT`), is not counted. Alternative: sum over all samples not excluded by
   location flags (`PRE_DEPLOYMENT`, `MANUAL_EXCLUDE`), independent of temperature and humidity
   problems. That needs a separate exclusion mask for auxiliary aggregates.
2. **Defaults to confirm or replace:** `precip_max_mm` = 50 mm per ~30 min interval,
   `low_battery_v` = 3.3 V, `tolerance_mm` = 0.15 mm. Is the device data sheet (rain gauge
   resolution, battery cut-off) available?
3. **Should a broken auxiliary column ever reject a file?** (Deviation 2.) Now never.
4. **`precip_total_mm` on the web**: the plan's contract carries only `precip_mm` and
   `battery_v` in the raw months, so the counter is not part of the web contract. Is that
   intended?

## Review

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
