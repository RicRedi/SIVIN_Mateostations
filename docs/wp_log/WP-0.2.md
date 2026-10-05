# WP-0.2 — Owner decisions in the core and the first real export

## Summary

Implements the owner decisions of 2026-10-05 in the shared core, the ingest layer, the
`MissingValueCheck` default and the web display mask, and adds the first real export as a
regression fixture. **Whole-row validity:** a measurement is valid only if both temperature and
humidity are present. `DailyWeather` counts only such rows (new
`MeasurementSeries.complete_mask`). Parsers set `MISSING` when either value is missing,
`values-present` rejects a table with one empty variable, `MissingValueCheck` defaults to
`any`, and the web hides MISSING rows (`DISPLAY_EXCLUDE_MASK` = 311). `SensorId.parse` accepts
the underscore file name of the real export without becoming ambiguous. The default
`expected_interval_s` is now 1830 s, the median step measured on the real export. A trimmed
excerpt of the real export (300 original rows) and a regression test cover sensor id, row count,
UTC range, newest-first reversal, extra columns, CRLF/UTF-8 and the trailing `;` line.

## Changed files

Core:
- `src/sivin/core/defaults.py`: new `DEFAULT_SAMPLING_INTERVAL_S = 1830.0` (origin documented).
  `LEGACY_SAMPLING_INTERVAL_S = 1825.0` is unchanged because several out-of-scope subsystems
  derive their defaults from it (see *Out of scope*).
- `src/sivin/core/schema.py`: new `MeasurementSeries.complete_mask(exclude_mask)` = `valid_mask`
  and both values present. This is an **addition** to the core contract; nothing existing changed.
- `src/sivin/core/daily.py`: whole-row validity. `n_samples`/`coverage` are row-level.
  `temp_n_samples`, `rh_n_samples`, `temp_coverage` and `rh_coverage` are kept for API
  stability and always equal them. The constructor enforces the equality, so the old check on
  the temperature columns now covers the humidity columns too.
- `src/sivin/core/ids.py`: new `UNDERSCORE_FILE_NAME_PATTERN`, tried after the existing
  `SENSOR_NAME_PATTERN`. It requires the `MeteoData_` prefix, a device number of 1–7 digits
  (shorter than a serial), a label that starts with a letter, and the fixed `8_6` export time.
  So `MeteoData_77799986_20260301.csv` is rejected instead of being read as sensor `20260301`.

Configuration:
- `src/sivin/config.py`: only the default and description of `time.expected_interval_s`
  (1830 s).
- `config/sivin.yaml`: `expected_interval_s: 1830.0`. The `source_timezone` comment now says
  "local time, owner Q2".

Ingest:
- `src/sivin/ingest/parsers/tabular.py`: `MISSING` if temperature **or** humidity is missing.
- `src/sivin/ingest/validation.py`: `values-present` is an ERROR when any one variable has no
  value at all. Every row would then be `MISSING`, so the file holds no valid measurement.
  The `ValidationSettings` docstring was updated.
- `src/sivin/ingest/parsers/columns.py`: `expected_interval_s` defaults to
  `DEFAULT_SAMPLING_INTERVAL_S`. The `long_step_factor` text now says 48 × 1830 s = 24.4 h.
  Descriptions updated where the real export confirmed something (timestamp header name, title
  row, newest-first order, local time Q2).
- `src/sivin/ingest/parsers/portal.py`: module docstring only (CSV layout verified on one real
  export).

Quality:
- `src/sivin/quality/checks/missing.py`: default `rule = any`, with the description citing the
  owner decision.

Web:
- `web/src/domain/QcFlags.ts`: `DISPLAY_EXCLUDE_MASK = DEFAULT_EXCLUDE_MASK`. The exported
  name is kept, so `web/src/main.ts` (out of scope) did not need a change.
- `web/src/domain/Resampler.ts`: `NOMINAL_STEP_S = 1830`, so the raw gap threshold is
  3 × 1830 s.
- `web/src/domain/ResolutionPolicy.ts`: comment only (≈ 1466 samples per 31 days).

Tests:
- `tests/core/test_daily.py`: the hand-computed fixture was recomputed under whole-row validity
  (day 2: RH mean (95 + 85) / 2 = 90, all counts 2, coverage 0.5). The test of one missing
  variable is parametrised for both variables and for exclusion masks 311 and 0. The tests
  for the new constructor invariant were extended.
- `tests/core/test_schema.py`: `complete_mask`.
- `tests/core/test_ids.py`: 10 accepted underscore spellings (including POSIX and Windows paths
  and a copy suffix) and 8 rejected ambiguous ones.
- `tests/ingest/parsers/test_portal.py`, `tests/ingest/test_validation.py`: expectations that
  relied on per-variable validity were updated (one empty variable is now an ERROR; a row with
  one missing value is `MISSING`).
- `tests/quality/test_checks.py`: rule `all` is tested explicitly; the default `any` is tested
  on four rows.
- `tests/analytics/disease/test_botrytis.py`: one line. A day with all humidity missing now has
  `temp_coverage` 0.0 instead of 1.0. The index result in that test did not change.
- `tests/test_config.py`, `tests/test_cli.py`: the default is 1830.0.
- `tests/ingest/test_real_export.py` (new): 8 regression tests on the real export.
- `tests/ingest/conftest.py`, `tests/ingest/test_fixtures.py`: `REAL_EXPORTS`. The
  synthetic-generator check excludes `real/`.
- `tests/fixtures/exports/real/MeteoData_8615620_77799986_VUT_20260301_223842.csv` and
  `README.md` (new). `tests/fixtures/exports/README.md` got 3 lines that point to the
  exception `real/` (see *Deviations*).
- `web/tests/Resampler.test.ts`: the display mask equals 311, and MISSING hides the
  temperature of a row whose RH is `null`.

Docs: `docs/architecture.md` (contract table, new section *Row validity*),
`docs/data-format.md` (header note, real-export layout, values, `values-present`, settings, new
section *Verified against a real export*), `docs/web.md` (quality flags in the chart, 1830 s).

## Real export fixture

The source was `/tmp/claude-0/realexport/MeteoData_8615620_77799986_VUT_20260301_223842.csv`,
165 551 bytes. A copy with the spaced name was byte-identical.

The excerpt keeps the original title line, the header line, the 150 newest data rows (original
lines 3–152), the 150 oldest data rows (original lines 3373–3522), the trailing `;` line and
CRLF endings. It is 14 211 bytes, and every kept line is an original line byte for byte (checked
by script). The cut between the two blocks adds a gap of 1638.25 h that is not in the original;
the README says so. No DST transition is in the data, and none was fabricated.

## How it was verified

All commands ran in `/home/user/wt/wp-0.2`.

- `make lint type test` → ruff check: all checks passed. ruff format: 193 files already
  formatted. mypy --strict: no issues in 116 source files. pytest: **1306 passed**.
- `make cov` → 1306 passed, total 99.93 % (required 85 %). Every changed module is at 100 %
  line and branch coverage: `core/daily.py`, `core/ids.py`, `core/schema.py`,
  `core/defaults.py`, `config.py`, `ingest/parsers/{columns,portal,tabular}.py`,
  `ingest/validation.py`, `quality/checks/missing.py`.
- `cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build` → 0
  vulnerabilities; ESLint and tsc clean; Vitest **14 files, 130 tests passed** (all-files line
  coverage 99.41 %); vite build OK.

The orchestrator's facts were checked on the **full** real export (script, not committed). It
parses under both names (underscores and spaces) with **no validation finding**:

| Fact | Result |
|---|---|
| Sensor | 77799986 |
| Data rows | 3520 |
| First timestamp | 2025-07-30 08:22:29Z |
| Last timestamp | 2026-03-01 21:27:05Z |
| Median step | 1830 s |
| Largest steps | 3.54 h, 23.44 h, 3336.6 h |
| Other step | 1.02 h |
| Shortest step | 49 s |
| Empty value cells | none |
| `qc` after parsing | all 0 |

All facts match the brief.

## What did not work / what was not verified

- DST handling is still verified only on synthetic data: the real export has no transition
  inside its data.
- The XLSX export layout and exports of the other three sensors are unverified (Q11).
- Whether the portal itself produces the underscore names (Q8) is unknown. Both spellings are
  accepted.
- Earlier per-variable behaviour that this WP replaced cannot be "seen" on the real export: it
  has no missing values. The whole-row rule is tested on synthetic data only.

## Deviations

- `tests/fixtures/exports/README.md` is outside the literal Files scope
  (`tests/fixtures/exports/real/**`). Its first sentence says every file in the directory is
  synthetic. With a real file under `real/` that would mislabel real data, which CLAUDE.md
  forbids. I added a 3-line *Exception* paragraph and changed nothing else.
- `tests/ingest/conftest.py` and `tests/ingest/test_fixtures.py` changed because
  `test_generator_reproduces_the_committed_fixtures` and
  `test_readme_lists_every_fixture_directory` would otherwise treat the real file as a missing
  synthetic fixture. Both are matching ingest tests.
- `tests/analytics/disease/test_botrytis.py` (1 assertion), `tests/test_cli.py` and
  `tests/test_config.py` are tests of other packages. The brief requires updating every test
  that relied on per-variable validity or on the 1825 s default.

## Out of scope

The following places still treat temperature and humidity separately or default to 1825 s. Once
rows are flagged `MISSING` (parsers, `MissingValueCheck` with `any`) and the exclusion mask
contains `MISSING`, they behave consistently. They do not enforce the rule on unflagged data,
though:

- `src/sivin/analytics/disease/botrytis.py:289-309`: separate `rh_valid` and `has_temp`
  masks.
- `src/sivin/analytics/disease/botrytis.py:455-460`: `_covered_days` checks `temp_coverage`
  and `rh_coverage` separately. They are now equal, so this is redundant but harmless.
- `src/sivin/analytics/disease/powdery_mildew.py:72`: valid = not excluded and temperature
  present (humidity ignored).
- `src/sivin/analytics/ripening/common.py:100` (`rh_coverage`, now equal to `coverage`) and
  `:156` (temperature present only).
- `src/sivin/analytics/ripening/durations.py:60,140,270`: per-variable `NaN` handling.
- `src/sivin/alignment/grid.py:302`: `temp_c.notna() | rh_pct.notna()`. A row with one value
  counts as having a value.
- `src/sivin/alignment/strategies.py:104`: per-variable `usable` mask. `docs/alignment.md:47`
  says every variable is aligned independently.
- `docs/quality-control.md:86` and `:92` still state `rule: all` as the default with the old
  rationale (file owned by WP-1.8 in this wave).
- Hard-coded 1825 s defaults via `LEGACY_SAMPLING_INTERVAL_S` or literals in
  `src/sivin/quality/checks/sampling.py:42`, `quality/checks/spike.py:26,51`,
  `quality/checks/step.py:80`, `quality/contrast.py:101`, `quality/regime.py:107`,
  `alignment/strategies.py:40,285`, `alignment/config.py:59`,
  `analytics/disease/sampling.py:52,61`, `analytics/ripening/params.py:27,111`, and the
  matching `docs/indices/*.md` and `docs/quality-control.md`, `docs/alignment.md`. Proposal:
  switch them to `DEFAULT_SAMPLING_INTERVAL_S`, or better, pass `time.expected_interval_s`
  from the configuration (planned in WP-1.7).
- Prose mentions of 1825 s (docstrings and comments, no behaviour), found in review:
  `src/sivin/alignment/grid.py:32-37` (default grid step and `MIN_GRID_STEP_S` docstrings),
  `src/sivin/alignment/aligner.py:3`, `src/sivin/analytics/ripening/durations.py:3`,
  `src/sivin/quality/checks/sampling.py:3`, `src/sivin/analytics/disease/sampling.py:3`.
- `docs/alignment.md:99` says the aligner's `params.expected_interval_s` default of 1825 s is
  "same as `time.expected_interval_s`". Since this WP that is wrong: the time default is
  1830 s. It should be fixed together with the aligner default (WP-1.7).
- `src/sivin/config.py:58-64`: the `source_timezone` description still says "Not yet confirmed
  by a real export (owner question Q2)". Only `expected_interval_s` was in scope.
- `config/one_variable_plot.yaml`, `config/two_variable_plot.yaml`: legacy `T_s: 1825`
  (legacy, untouched).
- No `.gitattributes`: a Windows checkout with `core.autocrlf` could rewrite the CRLF fixture.
  Proposal: `tests/fixtures/** -text`.

## Open questions for the owner

1. **Proposed config/CLI wiring (WP-1.7):** `ParserSettings.expected_interval_s` should be fed
   from `time.expected_interval_s` rather than having its own default. No new config section or
   CLI command is introduced by this WP.
2. **Contract addition:** `MeasurementSeries.complete_mask` is new in `sivin.core.schema`
   (additive). The `DailyWeather` constructor now also rejects frames whose `rh_*` count or
   coverage differs from `n_samples`/`coverage`. Is that stricter invariant acceptable? All
   in-repo code satisfies it.
3. **Should the analytics and the aligner enforce whole-row validity themselves** (e.g. use
   `complete_mask`)? Today they rely on the `MISSING` flag (see *Out of scope*).
4. **`values-present` quarantines the whole file** when one variable has no value at all (for
   example a failed humidity channel). Under the whole-row rule that file holds no valid
   measurement, so the valid values of the other variable never reach the store. They stay in
   quarantine and could be re-imported if the rule ever changes. Is that consequence
   acceptable, or should such files be imported with every row `MISSING`, which keeps the raw
   values in the store?
5. Q8, Q9, Q10, Q11 from the plan remain open; nothing in this WP depends on their answers.

## Review

Verdict: APPROVE (round 1)

Reviewer: independent reviewer agent, 2026-10-05. Diff reviewed: `11f71ef...c09eddf`.

### Gates observed (run by the reviewer in `/home/user/wt/wp-0.2`)

- `make lint type test`: ruff check passed, 193 files already formatted, mypy strict clean on
  116 source files, **1306 passed**.
- `make cov`: 1306 passed, total 99.93 % (required 85 %). `core/daily.py`, `core/ids.py`,
  `core/schema.py`, `ingest/parsers/{columns,tabular}.py`, `ingest/validation.py` and
  `quality/checks/missing.py` are at 100 % line and branch coverage.
- `cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build`:
  0 vulnerabilities, lint and tsc clean, **14 files, 130 tests passed**, build OK.

### Independent checks (throwaway scripts in `/tmp/claude-0/review-0.2/`)

- **Full real export:** parsed `/tmp/claude-0/realexport/…223842.csv` with default settings. It
  is accepted with no issue: 3520 rows, 2025-07-30 08:22:29Z to 2026-03-01 21:27:05Z, median
  step 1830 s, all `qc` = 0.
- **Fixture byte-exactness:** fixture lines 1–2 = original lines 1–2; lines 3–152 = original
  3–152; lines 153–302 = original 3373–3522; the trailing `;` line and the final CRLF are
  identical. The file has 303 LF, all of them CRLF, and no BOM. The README provenance (rows,
  ranges, artificial 1638.25 h cut gap, no DST) matches the file.
- **Hand-derived test values** were re-derived from the raw lines: 47 rows on 2026-02-28; the
  five oldest timestamps and steps 12 736 s, 84 398 s, 49 s and 139 d + 2154 s; first and last
  values. All match.
- **CRLF safety:** I cloned the branch with `core.autocrlf=true` and with `input`. The fixture
  stayed byte-identical (md5 equal), because git does not convert files whose index copy
  already contains CRLF. Only a future `* text=auto` plus `git add --renormalize` rewrites it.
  It would also rewrite the 15 synthetic CRLF fixtures. `test_raw_file_layout_is_the_original`
  would then fail loudly. There is no silent risk today.
- **SensorId:** 48 hand-picked adversarial names, plus a 300 000-case random fuzz of old
  (`11f71ef`) against new `SensorId.parse`. **No name accepted before resolves differently
  now**; 11 fuzz names are newly accepted, all underscore spellings. The trailing
  `20260301_223842` is never taken as an id. `MeteoData_77799986_20260301.csv`,
  `…_VUT_20260301.csv`, 8-digit device numbers, a missing `MeteoData_` prefix and a lowercase
  prefix are all rejected with `ValueError`. Lowercase labels, labels with digits (`VUT2`,
  `V2T`), `.CSV`/`.xlsx`, copy suffixes and POSIX and Windows paths are accepted. Labels with
  an inner `_`, with diacritics, or starting with a digit are rejected (see m2).
  `is_portal_export_name` and `PortalCsvParser.can_parse` accept the real name.
- **Whole-row rule, store paths.** Synthetic series: 144 rows at 1830 s, 10 rows with only the
  temperature missing, 10 with only the humidity missing. Written with `MeasurementStore.append`
  and read back, every row has `qc` = 0 and the NaN values survive.
  - store → `DailyWeather`: 124 valid samples. The 20 half-rows are dropped and all
    count/coverage columns are equal, so it is **safe without flags**.
    Edge cases also passed: all rows half-missing, a single row, and the 25 h DST day
    (coverage clipped to 1).
  - store → `SensorAligner` (default config) **without QC**: **20 grid points are valid for
    one variable and not the other**. This shows the per-variable code below is reachable.
  - store → `QualityPipeline` (default `missing` with `any`) → `SensorAligner`: 20 rows
    `MISSING`, 0 half-valid grid points. **Safe once the QC pipeline runs first.**

### Classification of the remaining per-variable code (hand-off *Out of scope*)

| Location | Safe without the MISSING flag? | Why |
|---|---|---|
| `analytics/disease/botrytis.py:455-460` `_covered_days` | **safe** | reads `DailyWeather` coverage, which checks the values directly |
| `analytics/ripening/common.py:100` (`rh_coverage`) | **safe** | the same; the column equals `coverage` |
| `analytics/ripening/common.py:156` `count_non_positive_humidity` | **safe** | only counts and logs artefacts, no result value |
| `alignment/grid.py:302` (`notna() \| notna()`) | low risk | only widens the grid span by an end sample with one value |
| `analytics/disease/botrytis.py:289-309` | **risk on unflagged data** | an RH-only row counts as wet and extends a wetness period |
| `analytics/disease/powdery_mildew.py:72` | **risk on unflagged data** | day eligibility comes from `DailyWeather` (safe), but the per-sample hours use temperature-only rows |
| `analytics/ripening/durations.py:60,140,270` | **risk on unflagged data** | values masked by flags only, `NaN` per variable |
| `alignment/strategies.py:104` | **risk on unflagged data** | reproduced above: half-valid grid points |
| `web` (`DISPLAY_EXCLUDE_MASK`) | risk on unflagged data | a `null` without MISSING keeps the other value (documented in `docs/web.md`) |

All five "risk" rows are correct **if and only if** the QC pipeline (or the parser) has set
`MISSING` before them. `MeasurementStore.read` returns `qc = 0`, so the integration (WP-1.7,
site build) must run `QualityPipeline` on store data before analytics, alignment or the site
export. Alternatively, these places should use `MeasurementSeries.complete_mask`. Nothing wires
store data into them yet (no caller in `src/`), so this is not a defect of this WP. The
orchestrator should schedule it (hand-off open question 3).

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | docs/architecture.md:66-77 | "Every layer applies the same rule": the table leaves out analytics and alignment, which do **not** apply it on their own (see the classification). It also does not say that store data come back with `qc = 0`, so QC must run before them. Input: store → aligner → 20 half-valid grid points. Fix: add a row "analytics, alignment, web: rely on `MISSING`; run `QualityPipeline` on store data first" (or reword "every layer"). | fixed: the section now separates value-checked layers (core, `values-present`), flag producers (parsers, QC) and flag-dependent locations (the five risk locations), states that store reads return `qc = 0` so QC must run first, and notes that WP-1.7 switches them to `complete_mask` |
| minor | src/sivin/core/ids.py:61 | The underscore label is `[A-Za-z][A-Za-z0-9-]*`, while the spaced variant accepts any label. If spaces were replaced by `_`, a multi-word label (`VUT Brno` → `VUT_Brno`) or one with diacritics (`VÚT`) is rejected. Today all four labels are `VUT` (sensors.geojson), and a mismatch fails loudly (`sensor-id` error), never resolving to a wrong sensor. Fix if Q8 shows such names: allow non-digit-leading Unicode letters and document it. | fixed: a label is one or more `_`-separated words, each starting with a Unicode letter (`VÚT`, `VUT_Brno`, `Vinice_Žabčice-2`). The trailing export time stays unambiguous because no word starts with a digit. New tests: accepted and rejected cases, plus 300 seeded generated names. A throwaway fuzz against `11f71ef` and `c09eddf` (500 and 100 000 names) found 0 names that resolve differently from before; all newly accepted names resolve to their generated serial |
| nit | src/sivin/core/ids.py:60 | The device number in the underscore variant is limited to 1–7 digits (deliberate, for disambiguation). If the portal ever issues 8-digit device numbers, those names fail loudly. Worth one line in `docs/data-format.md`. | fixed: the 1–7 digit limit and the label and timestamp rules are documented in `docs/data-format.md` (portal CSV section) |
| nit | tests/fixtures/exports/README.md:9-12 | Still says the layouts are "not verified on a real export (owner questions Q1 and Q2)", two paragraphs after the new exception note. The worker already touched this file. | fixed: the paragraph now says the CSV layout is confirmed by `real/` and only XLSX is unverified (Q11) |
| nit | docs/wp_log/WP-0.2.md (*Out of scope*) | The 1825 s list leaves out prose mentions in `alignment/grid.py:32-37`, `alignment/aligner.py:3`, `analytics/ripening/durations.py:3`, `quality/checks/sampling.py:3` and `analytics/disease/sampling.py:3`. `docs/alignment.md:99` now wrongly says its 1825 default is "same as `time.expected_interval_s`". | fixed: the prose mentions and `docs/alignment.md:99` were added under *Out of scope* |
| nit | web/tests/Resampler.test.ts:91-96 | The gap test still uses 1825 s offsets, and no test pins `RAW_GAP_THRESHOLD_S` = 5490 s numerically. Harmless, because the test uses the symbol. | fixed: the gap test uses 1830 s offsets; a new test pins `NOMINAL_STEP_S` = 1830 and `RAW_GAP_THRESHOLD_S` = 5490, with 5490 s connected and 5491 s broken |

No blocker or major finding.

### Acceptance criteria / DoD

- The real export parses unchanged under its original name, with no finding (verified on the
  fixture and on the full file).
- Row-validity tests exist in core (`test_daily`, `test_schema`), parsers (`test_portal`,
  `test_validation`), QC (`test_checks`) and web (`Resampler.test.ts`).
- The 1830 s default is consistent across `core/defaults.py`, `config.py`, `config/sivin.yaml`,
  `ParserSettings` and `web/src/domain/Resampler.ts`. The remaining 1825 s defaults are outside
  the WP's scope and listed.
- Web mask: `DISPLAY_EXCLUDE_MASK === DEFAULT_EXCLUDE_MASK` (311). `main.ts` still uses
  `DISPLAY_EXCLUDE_MASK`. Tests cover MISSING hiding the row at raw and hourly resolution,
  with hand-computed values (`[null, 11]`, hourly mean 11).
- Gates green; changed-code coverage 100 %; docs updated; hand-off note complete.

### Deviations assessment

- `tests/fixtures/exports/README.md` (3 lines): **accepted.** Without it a real file would sit
  under a README that calls everything synthetic, which CLAUDE.md forbids.
- `tests/ingest/conftest.py`, `tests/ingest/test_fixtures.py`: **accepted.** They are matching
  ingest tests. Without the change the generator check would fail on the real file.
- `tests/analytics/disease/test_botrytis.py` (one assertion), `tests/test_cli.py`,
  `tests/test_config.py`: **accepted.** They are direct consequences of the `DailyWeather` and
  default changes, and the botrytis index result is unchanged. No production code outside
  scope changed.
- `values-present` one-empty-variable → ERROR (brief-sanctioned). Note for the owner: such a
  file is quarantined as a whole, so its valid other variable never reaches the store.
  It stays in quarantine and can be re-imported if the rule ever changes.
- `DailyWeather` constructor now rejects frames whose `rh_*` columns differ from `n_samples` /
  `coverage` (hand-off open question 2). It is consistent with the decision and all in-repo
  code passes; I see no problem.
