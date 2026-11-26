# WP-3.4 — Analytics on the web: season index cards, daily risk strip, records and extremes

## Summary

The map portal has a new "Ukazatele" section below the chart. It covers the selected sensors (up
to 8) and a season. It has three parts:

- **Season index cards.** A comparison table with GDD/Winkler, Huglin, BEDD, GST, the Cool Night
  Index and the phenology estimates (marked "orientační"). Each value comes with its unit,
  class, coverage, "odhad" mark, the no-data states and a "Jak se počítá" link to
  `docs/indices/<id>.md` on GitHub.
- **Daily risk strip.** Strips for grey mould (Broome), powdery mildew (Gubler-Thomas) and frost
  in traffic-light colours, with hatching, a text summary, a legend and the bands/inputs
  explanation. Days without data are grey, never green, and the estimated wetness input is
  marked.
- **Records and extremes.** Computed in the browser from `daily.json`, using complete days only.

The daily values need a contract extension. It is backward compatible (`schema_version` stays 1):

- An index entry in `indices/<season>.json` gets an optional `daily` block
  (`levels`, `start`, `end`, `date`, `value`, `level`).
- The manifest gets an optional `min_daily_coverage`.

In Python, the risk indices now expose their daily level as a new optional
`IndexResult.daily_levels` (`DailyLevels`). The levels are only the classes the indices already
define; seasonal values are unchanged.

## Changed files

- Python, analytics:
  - `src/sivin/analytics/base.py`: `DailyLevels`, `IndexResult.daily_levels`.
  - `__init__.py` re-export.
  - `disease/result.py` (`daily_levels_series`, `_result` parameter).
  - `disease/botrytis.py`, `disease/powdery_mildew.py`, `ripening/common.py`, `ripening/frost.py`.
- Python, site:
  - `src/sivin/site/indices.py`: `daily_block` and the `daily` key.
  - `site_files.py`: manifest `min_daily_coverage`.
  - `state.py`: `STATE_FORMAT` 3.
- Python, app (scope extended by the orchestrator for this one change): `src/sivin/app/factory.py`
  passes `analytics.min_daily_coverage` to `default_site_writers`, so the manifest carries the
  configured value; test `tests/site/test_service.py::test_manifest_carries_the_configured_complete_day_rule`
  (0.75 in the config → 0.75 in `manifest.json`).
- Python tests:
  - `tests/analytics/test_base.py`, `disease/test_botrytis.py`, `disease/test_gubler_thomas.py`,
    `ripening/test_hour_indices.py`.
  - `tests/site/test_indices.py`, `tests/site/test_site_files.py`.
- Web, contract and data:
  - `web/src/contract/{types,validateMeta}.ts`.
  - `web/src/domain/{isoDates,RiskStrip,SensorRecords}.ts`.
  - `web/src/app/{AnalyticsCatalog,AnalyticsLoader,AnalyticsPresenter,IndexDocs}.ts`.
- Web, i18n and UI:
  - `web/src/i18n/{cs,de,en,analyticsTerms}.ts`.
  - `web/src/ui/{AnalyticsSection,IndexCardsView,RiskStripView,RecordsView,IndexFormat}.ts`.
  - `ui/App.ts`, `ui/SensorPanel.ts`, `main.ts`, `vite-env.d.ts`, `styles.css`.
- Web, scripts, tests and fixtures:
  - `web/scripts/generate-fixture.mjs`, which writes placeholder indices and daily blocks and
    `min_daily_coverage`.
  - New `web/scripts/screenshot-analytics.mjs`.
  - `web/tests/analytics.test.ts`, `web/tests/ui/analytics.test.ts`, `pythonSite.test.ts`,
    `ui/App.test.ts`.
  - Regenerated `web/public/data/` (synthetic) and `web/tests/fixtures/python-site/`.
- Docs:
  - `docs/site.md`, `docs/web.md` (new section "Indicators (WP-3.4)"), `docs/indices/README.md`
    (new section "On the web portal"), `MIGRATION_PLAN.md` §2.6 only.
  - `README.md` ("What it does", the "not yet done" list, the indices paragraph).
  - Screenshots `docs/wp_log/img/WP-3.4-*.png`.

## Design decisions

- **Where the daily data live.** They go in `indices/<season>.json` as an optional `daily`
  block, not in a new `risk/<season>/<sensor>.json` file:
  - The change is additive, and the web already loads this file for the cards.
  - The incremental build needs no new file kind, deletion rule or SHA tracking: the entries are
    already part of the build state.
  - Size: about 6 KB per risk index, sensor and season, so about 20 KB per sensor and season.
    Splitting the file is noted as a proposal in `docs/site.md`.
- **Which levels.**
  - Powdery mildew: the UC IPM class of the day's index, `null` on days with temperature coverage
    below `min_daily_coverage`.
  - Frost: `none` / `frost` (≤ 0 °C hours) / `hard_frost` (≤ −2 °C hours), complete days only.
  - Grey mould: the configured `risk_bands` of the day's highest Y. **Default: no bands exist**,
    because the literature gives no class limits. In that case the levels are only
    `no_wetness` / `wetness`: "an estimated wetness period ended that day". This is not a risk
    class. The web shows it as green / amber, not red. Open question 1 asks whether you want bands.
- **Colour by rank.** The web colours a level by its rank: lowest green, highest of ≥ 3 red,
  the rest amber. It does not use level names, so configured Botrytis bands work without code
  changes.
- **No new thresholds.** A day without a level has `value: null` too. Daily levels are published
  for incomplete seasons, because they describe single days; the seasonal `class` stays `null`.
- **Full rebuild.** `STATE_FORMAT` was bumped 2 → 3 in `src/sivin/site/state.py`, so the first
  build after the update rebuilds everything. Otherwise reused sensors would keep entries
  without `daily`, and an incremental build would differ from a full one. `SITE_OUTPUT_FORMAT`
  is in `src/sivin/app/site.py`, which is outside the scope, so the state format was used
  instead. Side effect: the failure fallback of a sensor that fails in that first build is lost
  once, because the old state is ignored.
- **Records.**
  - Season = calendar year, the same as the manifest's seasons. Frost means `T_min ≤ 0 °C`, as
    the brief says; this is consistent with the frost hours, `T ≤ 0`.
  - Last spring frost: the last such day Jan 1 – Jun 30. First autumn frost: the first such day
    Jul 1 – Dec 31.
  - "All data" has no frost dates.
  - Ties keep the earliest date.
- **Season selector.** It belongs to the section, defaults to the latest manifest season, and is
  independent of the chart window. It is not in the URL hash.

## How it was verified

All commands were run in `/home/user/wt/wp-3.4`, after rebasing onto `origin/main` (5ab9e48, WP-3.7
merged).

- `make lint` → ruff check and format clean (311 files).
- `make type` → mypy strict: "Success: no issues found in 186 source files".
- `make test` → 2164 passed.
- `make cov` → 2164 passed, TOTAL 99 %. Changed modules:
  - `analytics/base.py`, `disease/powdery_mildew.py`, `disease/result.py`, `ripening/common.py`,
    `ripening/frost.py`, `site/indices.py`, `site/site_files.py`, `site/state.py`,
    `app/factory.py`: 100 %.
  - `disease/botrytis.py`: 99 %. The 2 missed lines (384-385) are earlier code, not changed here.
- `tests/e2e/test_site.py` (the Python fixture matches the committed `web/tests/fixtures/python-site`)
  and `test_incremental_and_full_builds_are_byte_identical` both pass.
- Web (`web/`):
  - `npm run lint` and `npm run typecheck` → clean.
  - `npm test` → 33 files, 341 tests passed. Coverage: all files 99.38 % lines. New files:
    100 % lines, except `RecordsView.ts` at 97.2 %.
  - `npm run build` → OK.
- Hand-computed tests:
  - Python: the PM daily levels of the 10-day hand-built example, including the two
    low-coverage days.
  - Frost levels of the 3-day example: hard frost / frost / none.
  - Botrytis levels with and without bands: Y = 0.131 → low and Y = 0.168 → elevated at a 0.15
    bound.
  - `daily_block` rounding and nulls.
  - Web: `RecordsCalculator`, with ties, an incomplete frost day, T_min exactly 0 °C, no
    precipitation and an empty season. Also `RiskStrip` grey days, tones by rank, the ISO date
    arithmetic, and the contract tolerance (a malformed block is ignored with a warning).
- Visual check with `vite preview` and Playwright (Chromium 1243):
  - `node scripts/screenshot-analytics.mjs` produced `docs/wp_log/img/WP-3.4-{cards,risk,records}-{desktop,mobile}.png`.
    They are from **synthetic demo data with placeholder values, not measurements**.
  - The document `scrollWidth` equals the viewport at 1280 px and 390 px (no horizontal page
    scroll). On a phone the index table scrolls sideways inside its own box.

## What did not work / what was not verified

- **No real data.** The real export (77799986) is off site the whole time, so its entries are
  `no_data` and have no daily block. The strips and cards were seen only on synthetic data:
  the demo fixture and the 4-day synthetic sensor of the Python fixture.
- **Screen readers.** Accessibility was checked only structurally in tests: `role="img"` with a
  text summary, tooltips, a legend and text in the table. No screen reader was used.
- The strip is not aligned under the chart's time axis. The chart window and the index period
  differ; the brief said "optional if simple".
- GFV shows only the véraison date (the published value). The flowering date is in the Python
  `details`, which are not published. No phenology model is configured by default, so every
  phenology card shows "bez odhadu".

## Out of scope

- `docs/web.md` earlier listed two things for WP-3.4 that are not in its approved scope:
  - a band for `unlogged_off_site` on the chart;
  - use of the manifest's `data_status` / `last_built_at` in the UI.

  Both remain open; the text now says so.
- If the number of sensors grows a lot, split the daily blocks into
  `risk/<season>/<sensor_id>.json`, as proposed in `docs/site.md`.

## Open questions for the owner

1. **Grey-mould bands.** By default the Broome index has no risk bands, because the literature
   gives no limits. So the strip shows only "estimated wetness yes/no" (green/amber), with the
   day's Y in the tooltip. Should local bands be set in `analytics.indices.botrytis_broome.risk_bands`
   (e.g. `low` 0, `elevated` 0.3)? They would be a project choice and documented as such.
2. **GFV flowering date.** Publish it as well? That needs a small contract addition, e.g. an
   optional `stages` map in the entry, and applies only once GFV parameters are configured.
3. **Season selector.** Should it follow the chart's "Sezóna" window, and should it go into the
   URL hash? It is independent at the moment.

## Review
Verdict: (pending)
| Severity | File:line | Finding | Status |
