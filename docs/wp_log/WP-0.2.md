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
4. Q8, Q9, Q10, Q11 from the plan remain open; nothing in this WP depends on their answers.

## Review
Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
