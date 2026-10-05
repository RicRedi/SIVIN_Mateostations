# WP-3.1 — Web portal MVP

## Summary

Added `web/`, a static map portal built with Vite, strict TypeScript, Leaflet and uPlot, with no
UI framework. It reads only the site data contract of MIGRATION_PLAN.md §2.6. Small classes with
one job each (`DataClient`, `Resampler`, `TimeWindowFactory`, `MapView`, `SensorPanel`,
`SeriesChart`, `TimeWindowControl`, `I18n`, `Store`, ...) are wired in `main.ts` through
constructors. There are no globals or singletons. Every contract file is validated at run time
and a mismatch raises `ContractError` with file and JSON path. Until WP-3.2 produces real files,
the app runs on a deterministic **synthetic** fixture in `web/public/data/` (547 KB) and shows a
"demo data" badge. The UI is in Czech, German and English. The selection, time window,
resolution and language are kept in the URL hash. A CI workflow `.github/workflows/web.yml` runs
the four web gates. Architecture and usage are in `docs/web.md`.

## Changed files

- `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/vite.config.ts`
  (also Vitest and coverage config), `web/eslint.config.js`, `web/.gitignore`, `web/index.html`
- `web/src/contract/*`: types mirroring §2.6/§2.4, `FieldReader`, validators, `ContractError`
- `web/src/data/*`: `DataClient`, `DataLoadError`, `utcMonthKeys`
- `web/src/domain/*`: `TimeSeries`, `RawSeries`, `Resampler`, `QcFlags`/`QcMask`, `TimeZone`,
  `TimeWindow`, `WindowSpec`, `TimeWindowFactory`, `ResolutionPolicy`, `alignSeries`,
  `dailyColumnSeries`, `units`
- `web/src/app/*`: `SensorCatalog`, `ChartDataLoader`, `ChartPresenter`
- `web/src/state/*`: `Store`, `AppState` (+ selection helpers), `HashStateCodec`
- `web/src/i18n/*`: `I18n`, `LanguagePreference`, `languages`, `cs`/`de`/`en`
- `web/src/ui/*`: `App`, `HeaderView`, `MapView`, `SensorPanel`, `SensorList`,
  `TimeWindowControl`, `SeriesChart`, `HashSync`, `palette`, `dom`; `web/src/styles.css`,
  `web/src/main.ts`, `web/src/vite-env.d.ts`
- `web/tests/**`: 12 test files (96 tests)
- `web/scripts/generate-fixture.mjs`, `web/scripts/screenshot.mjs`
- `web/public/data/**`: synthetic fixture (29 files incl. `README.md`)
- `.github/workflows/web.yml`
- `docs/web.md`, `docs/wp_log/WP-3.1.md`, `docs/wp_log/img/WP-3.1-desktop.png`,
  `docs/wp_log/img/WP-3.1-mobile.png`

## How it was verified

Gates, run in `/home/user/wt/wp-3.1/web` after `rm -rf node_modules dist coverage && npm ci`
(Node 22.22.0, npm 10.9.4):

```
npm run lint       → eslint . (no output, exit 0)
npm run typecheck  → tsc --noEmit (no output, exit 0)
npm test           → Test Files  12 passed (12)
                     Tests  96 passed (96)
                     Statements   : 99.58% ( 712/715 )
                     Branches     : 88.53% ( 278/314 )
                     Functions    : 100% ( 210/210 )
                     Lines        : 99.56% ( 681/684 )
npm run build      → dist/index.html 0.84 kB, dist/assets/index-*.css 23 kB,
                     dist/assets/index-*.js 242 kB (gzip 81 kB), ✓ built
```

- **Coverage scope:** `src/**/*.ts`, minimum 85 % lines (enforced in `vite.config.ts`).
  Excluded as thin glue: `src/main.ts`, `src/ui/App.ts`, `src/ui/MapView.ts` (Leaflet) and
  `src/ui/SeriesChart.ts` (uPlot/canvas). The DOM components without those libraries are tested
  under jsdom.
- **Tests with hand-computed expectations:**
  - Contract validation: the whole fixture passes, and broken files fail with exact messages.
  - `DataClient.getRawRange`: month selection across a boundary, windows outside the data,
    months not in the manifest, a missing listed month, a foreign `sensor_id`, caching, network
    and JSON errors.
  - Merging and sorting with duplicates.
  - `Resampler` hourly means with nulls, SPIKE (excluded) and STEP (kept), plus gap breaks.
  - `TimeZone` across both 2026 DST transitions.
  - `TimeWindowFactory`: 24 h / 7 d / 30 d, season 2026, a 7-day window over 25 Oct 2026
    (7 d + 1 h), custom ranges in either order, and resolution limits.
  - URL hash round-trips, including the documented example
    `#s=77678271,77680921&w=7d&r=hourly&lang=cs`.
  - `I18n` fallback (language → Czech → key) and `LanguagePreference` with throwing storage.
  - `TimeWindowControl`, `SensorPanel`, `SensorList`, `HeaderView` and `HashSync` in jsdom.
- **Base path:** `dist/index.html` references `/SIVIN_Mateostations/assets/...` and the app
  loads data from `/SIVIN_Mateostations/data/`. Checked with `vite preview`.
- **Browser check:** headless Chromium from `/opt/pw-browsers` against `vite preview`:
  - No page errors.
  - At 360, 390 and 1440 px, `document.scrollWidth` equals the viewport width, so there is no
    horizontal scroll.
  - Plain marker click selects one sensor; ctrl-click adds a sensor; a checkbox toggled from the
    keyboard (Space) adds a sensor.
  - The season preset switches to "Automatic (Daily means)".
  - The language switch updates the title, the hash and `localStorage`.
  - An unknown sensor id in the hash is dropped.
  - Event markers are rendered.
- **Fixture:** `npm run fixture` is deterministic (same md5 on rerun). It is 546,574 bytes,
  well under 3 MB.

Screenshots (Chromium, `npm run screenshot`). Map tiles are **blank** because the sandbox cannot
reach the OpenStreetMap tile servers:

- Desktop, 1440 × 900: sensors 77678271 + 77799986, custom window 1–7 Jun 2026, raw data. The
  orange sensor starts after its `deployment` marker on 3 Jun, because its office period is
  flagged `PRE_DEPLOYMENT` and hidden.
  ![desktop](img/WP-3.1-desktop.png)
- Phone, 390 × 844: 77678271 + 77680921, 30 days with automatic hourly means, bottom sheet
  scrolled to the chart.
  ![mobile](img/WP-3.1-mobile.png)

## What did not work / what was not verified

- **Map tiles:** OSM/OpenTopoMap tiles never loaded in the sandbox (`ERR_TUNNEL_CONNECTION_FAILED`),
  so the tile layers, the layer switch and the attribution have not been seen with real tiles.
- **GitHub Actions:** `web.yml` has not run on GitHub. The same commands passed locally.
- **Real data:** not tested against real data. WP-3.2 does not exist yet; everything runs on the
  synthetic fixture.
- **Browsers and devices:** only headless Chromium was tested; no Firefox, Safari or real phones.
  No screen-reader test was done.
- **Map keyboard access:** Leaflet circle markers are not keyboard-focusable. The keyboard path is
  the checkbox list in the panel.
- **Date inputs:** the native `<input type="date">` shows the browser's locale (US format in
  headless Chromium), not the UI language.
- **`ui/App.ts`:** not unit-tested. Its behaviour was only checked with the headless interaction
  script above, which is not committed.

## Deviations from the brief (and why)

- **`contract.ts` became the directory `src/contract/`** (`types.ts`, `FieldReader.ts`,
  `validateMeta.ts`, `validateSeries.ts`, `validateSensors.ts`, `index.ts`). This keeps files
  small, and it is imported as `../contract`.
- **TypeScript 6.0.3, not 7.x:** typescript-eslint 8.71 supports TypeScript `<6.1.0`.
- **`playwright-core` is a devDependency** (no browser download) for `npm run screenshot`, so the
  screenshots can be reproduced.
- **One `eslint-disable-next-line`** in `SeriesChart.ts`. uPlot's `Axis.Side` is an ambient
  `const enum` that cannot be referenced under `isolatedModules`, so the numeric value is used,
  with a reason comment.
- **Relative presets end at the end of the data, not at "now".** The end is the largest
  `last_t`, rounded up to a full hour. With "now" (5 Oct 2026), the fixture, which ends on
  30 Sep, would show an empty 24 h / 7 d chart; real data lag behind by up to a cron interval.
- **7 d / 30 d count local calendar days** (same wall-clock time), so they are 7 d ± 1 h across a
  DST change. 24 h is exactly 86,400 s.
- **QC-excluded samples are hidden at raw resolution too**, not only in hourly means, so the
  office period of a sensor appears as a gap before its deployment marker.
- **Hourly means are stamped with the start of the hour.**
- **Comparison is capped at 8 sensors**, the size of the colour-blind-checked palette. A further
  sensor is refused with a message.
- **The fixture placement dates are synthetic** (1 Jun 2026, and 3 Jun for 77799986). The plan's
  §2.4 example uses `2025-12-01` as its own placeholder. Real dates wait for Q3.

## Out of scope

- **`.gitignore` (root, owned by WP-0.1)** ignores every `data/` directory and every `*.png`.
  This hits `web/public/data/` (fixture), `web/src/data/` (the `DataClient` sources) and the
  screenshots. All of them were committed with `git add -f`, and new files there need the same.
  Proposal: add `!web/public/data/`, `!web/src/data/` and `!docs/wp_log/img/`, or the targeted
  rules WP-0.1 task 4 already plans.
- **Deployment to Pages** is WP-4.1. At deploy time it must build with `VITE_DEMO_DATA=false`
  and put `site/data/` at `dist/data/` (see `docs/web.md`).
- **Showing `indices/<season>.json`:** it is typed, validated and loaded by
  `DataClient.getIndices`, but nothing displays it. Display belongs to WP-3.4.
- **Toggle for QC-excluded data:** a "show QC-excluded values" option for researchers who want to
  see e.g. the office period. This is a small UI addition and is not done.

## Open questions for the owner

1. **Contract details implemented leniently:** §2.6 shows these fields only by example, so I
   accept them as follows:
   - `null` for daily statistics on a day without valid data;
   - `null` or missing for `class` in `indices`, and for `confidence` and `detail` in `events`
     (e.g. events taken from the registry);
   - `null` or missing for `elevation_m` and `note` in a placement.

   The contract itself is unchanged. Please confirm, or WP-3.2 should always write these fields.
2. **Two y-axes:** temperature (left) and humidity (right) share one chart, as the brief
   requires. Dataviz guidelines advise against dual axes; the alternative is two stacked charts
   with a shared time axis. Keep it as is?
3. **Marker colours:** the map's neutral class 10–15 °C is almost white, so on a mild day the
   markers look empty (see the desktop screenshot, 11 °C). Is the diverging scale centred near
   the vine base temperature acceptable, or would you prefer a sequential scale?
4. **Should relative presets end at "now"** instead of at the end of the data?

## Review

Verdict: (pending)

| Severity | File:line | Finding | Status |
|---|---|---|---|
