# Web portal (`web/`)

Static map portal for the SIVIN vineyard weather sensors. It is served by GitHub Pages at
`https://ricredi.github.io/SIVIN_Mateostations/` and reads only static JSON files that follow the
site data contract, [MIGRATION_PLAN.md §2.6](../MIGRATION_PLAN.md) (`schema_version: 1`). There
is no server and no API key.

Stack: TypeScript (`strict`, `noUncheckedIndexedAccess`), Vite, Leaflet (map), uPlot (time
series), ESLint (typescript-eslint, strict type-checked), Vitest (+ jsdom for DOM components).
No UI framework: components are plain TypeScript classes that own a DOM subtree.

## Run locally

```bash
cd web
npm ci
npm run dev         # http://localhost:5173/SIVIN_Mateostations/
npm run lint && npm run typecheck && npm test && npm run build   # the CI gates
npm run preview     # serves dist/ at http://localhost:4173/SIVIN_Mateostations/
npm run fixture     # regenerates the synthetic data in public/data/
npm run screenshot  # with `npm run preview` running: docs/wp_log/img/WP-3.1-*.png
```

`npm run screenshot` uses `playwright-core` with an existing Chromium (`CHROMIUM_PATH`, default
`/opt/pw-browsers/...` in the agent sandbox); it never downloads a browser.

### Base path

`vite.config.ts` sets `base: process.env.SITE_BASE ?? '/SIVIN_Mateostations/'`. All asset URLs and
the data URL (`${import.meta.env.BASE_URL}data/`) are prefixed with it. For a different host path
build with e.g. `SITE_BASE=/ npm run build`.

## Architecture

```
main.ts  (composition root: builds every object, injects collaborators through constructors)
  │
  ├─ data/      DataClient ── fetch + cache + validate ──► contract/ (types + validators)
  ├─ domain/    TimeSeries, RawSeries, Resampler, QcMask, TimeZone,
  │             TimeWindow, WindowSpec, TimeWindowFactory, ResolutionPolicy, alignSeries
  ├─ app/       SensorCatalog, ChartDataLoader, ChartPresenter        (no DOM)
  ├─ state/     Store<T>, AppState, HashStateCodec                    (no DOM)
  ├─ i18n/      I18n, LanguagePreference, cs/de/en dictionaries
  └─ ui/        App, HeaderView, MapView, SensorPanel, SensorList, TimeWindowControl,
                SeriesChart, HashSync, palette, dom
```

Dependencies point downwards only: `ui` → `app` → `domain`/`data` → `contract`. There are no
globals or singletons; `main.ts` is the only place that touches `window`, `fetch` and
`localStorage` directly and passes them in.

| Class / module | Responsibility |
|---|---|
| `contract/types.ts` | TypeScript mirror of §2.6 (`Manifest`, `LatestFile`, `RawMonthFile`, `DailyFile`, `EventsFile`, `IndicesFile`, `SensorsGeoJSON` with the registry properties of §2.4). |
| `contract/validate*.ts`, `FieldReader`, `ContractError` | Hand-written runtime validation of every file. A mismatch throws `ContractError` with file, JSON path and problem, e.g. `manifest.json: $.schema_version must be one of [1], got 2`. Unknown extra fields are ignored (forward compatible); `schema_version` must be exactly 1. |
| `data/DataClient` | Fetches contract files relative to the data base URL, validates and caches them (one request per file per page load; failed requests are retried on the next call). `getRawRange(id, start, end)` picks the UTC months overlapping `[start, end)` that the manifest lists, fetches them in parallel and merges them into one `RawSeries`. A listed month that cannot be loaded is an error; months not listed are skipped. |
| `domain/RawSeries` | Columnar raw samples of one sensor, merged from monthly files, sorted by `t`, one sample per time. |
| `domain/TimeSeries` | Immutable value object of one variable (`t[]`, `values[]`, `null` = no valid value). `withGapBreaks` inserts `null` where samples are too far apart so charts draw gaps. |
| `domain/QcFlags` | `QcFlag` bits and `DEFAULT_EXCLUDE_MASK` = MISSING \| OUT_OF_RANGE \| SPIKE \| STUCK \| PRE_DEPLOYMENT \| MANUAL_EXCLUDE (§2.7); `QcMask` decides exclusion. |
| `domain/Resampler` | Raw → chart series: QC-masked raw values (gap threshold 3 × 1825 s), or hourly means over UTC hours (time = start of the hour; an hour without valid values is `null`). Daily values are not computed in the browser; they come from `daily.json`. |
| `domain/TimeZone` | Unix seconds ↔ wall-clock time of an IANA zone via `Intl` (DST-aware): local midnights, shifting by local days. |
| `domain/WindowSpec`, `TimeWindow`, `TimeWindowFactory`, `ResolutionPolicy` | What the user asked for (`24h` / `7d` / `30d` / `season` / `custom`) → a concrete `[startT, endT)` with a resolution. Details below. |
| `domain/alignSeries` | Puts several series on one union time axis for uPlot (`undefined` = no sample, skipped; `null` = gap). |
| `app/SensorCatalog` | Joins `sensors.geojson`, manifest and `latest.json` into `SensorInfo` per sensor; colour index = registry position. |
| `app/ChartDataLoader` | Loads raw / hourly / daily series and in-window events for the selected sensors. |
| `app/ChartPresenter` | Resolves the window from the state, shows "loading", the data or an error; drops responses of superseded requests. |
| `state/Store`, `AppState`, `HashStateCodec` | Observable immutable state (selection, window, resolution, language) and its URL-hash form, e.g. `#s=77678271,77680921&w=7d&r=hourly&lang=cs`, `#w=season&y=2026`, `#w=custom&from=2026-06-01&to=2026-06-15`. `r` is omitted for automatic resolution. |
| `i18n/I18n`, `LanguagePreference` | UI strings cs (default) / de / en, manifest labels, number/date formatting. Lookup: language → Czech → key. The language is stored in `localStorage` (every access in `try/catch`). Priority at start: URL hash → stored preference → Czech. |
| `ui/MapView` | Leaflet map, OSM tiles (layer switch to OpenTopoMap), fit to sensors, circle markers coloured by latest temperature, grey with dashed outline when `stale` or missing, tooltip (label, value, local time), legend. Click selects one sensor, ctrl/⌘-click toggles it in the comparison. |
| `ui/SensorPanel` | Right-hand panel (bottom sheet ≤ 760 px, collapsible): sensor list, metadata and latest values of the selected sensors, time-window controls, chart. |
| `ui/SensorList` | Checkbox list of all sensors (keyboard path to the comparison). |
| `ui/TimeWindowControl` | Preset buttons (`aria-pressed`), season year, custom from–to form, resolution selector whose "automatic" entry names the resolution it picks. |
| `ui/SeriesChart` | uPlot chart: temperature (left axis, °C, solid) and relative humidity (right axis, %, dashed), one colour per sensor, events as dashed vertical lines with focusable markers and tooltips, x axis in the display time zone, resizes with its container. |
| `ui/HeaderView` | Title, "demo data" badge, language switch. |
| `ui/App` | Coordinates store and views: user actions update the store, changes re-render views and reload the chart. |
| `ui/HashSync` | Two-way binding between store and `location.hash` (`replaceState`, no history spam). |

### Time windows and resolution

- Relative presets end at the end of the available data (the largest `last_t` in the manifest,
  rounded up to a full hour), not at "now": a portal whose data lag behind still shows data.
- `24h` = exactly 86 400 s. `7d` and `30d` go back 7 / 30 *local calendar days* to the same
  wall-clock time, so a 7-day window across a DST change is 7 d ± 1 h.
- `season` = 1 April 00:00 – 1 November 00:00 local time of the chosen year (the 1 Apr – 31 Oct
  period of MIGRATION_PLAN.md §3.1); years come from `manifest.seasons`.
- `custom` = whole local days from–to, both inclusive.
- Automatic resolution (`ResolutionPolicy`): ≤ 8 days raw, ≤ 62 days hourly, longer daily. The
  user can override it; the choice is part of the URL.

### Quality flags in the chart

Samples whose QC flags hit `DEFAULT_EXCLUDE_MASK` are shown as gaps at raw resolution and left
out of hourly means. Daily values are taken from `daily.json` as delivered by the pipeline.
STEP, NEIGHBOR_OUTLIER and TIMESTAMP_SUSPECT are informative and do not hide data.

### Colours

- Map: classed diverging scale, ColorBrewer RdBu (9 classes, reversed; colour-blind safe), edges
  −5 … 30 °C in 5 °C steps. The neutral class 10–15 °C contains 10 °C, the base temperature of
  grapevine growing-degree days. Stale/missing = grey fill with dashed outline (not colour alone).
- Chart: up to 8 compared sensors, categorical palette validated for colour-vision deficiency on
  adjacent pairs; a sensor keeps its colour (registry order), temperature solid, humidity dashed.

## Data loading (contract §2.6)

On start the app loads `manifest.json`, `sensors.geojson` and `latest.json` in parallel. Each
chart reload fetches, per selected sensor, `events/<id>.json` plus either the needed
`series/<id>/raw/<YYYY-MM>.json` months (raw and hourly) or `series/<id>/daily.json` (daily).
Every file is validated before use; a contract violation is shown as an error message in the
panel instead of a silently wrong chart. `indices/<season>.json` is typed, validated and
available through `DataClient.getIndices` but not displayed yet (WP-3.4).

## Synthetic fixture and real data

`web/public/data/` holds a **synthetic** data set generated by `scripts/generate-fixture.mjs`
(seeded PRNG, documented model, 4 real sensor positions, 1 Jun – 30 Sep 2026, ≈ 0.55 MB). It is
not a measurement; `public/data/README.md` says so and the UI shows a "demo data" badge.

The badge is controlled at build time by `VITE_DEMO_DATA`: any value other than `false`
(including unset) shows it. Nothing in the contract marks data as synthetic.

To use real data (WP-3.2 `SiteBuilder`, deployed by WP-4.1):

1. Generate `site/data/` with the pipeline.
2. Build with `VITE_DEMO_DATA=false npm run build`.
3. Replace `dist/data/` with the generated `site/data/` before uploading the Pages artifact
   (or copy `site/data/` into `web/public/data/` before the build). The app always reads
   `<base>/data/`; to read from elsewhere, change `DATA_BASE_URL` in `src/main.ts`.

Note: the root `.gitignore` ignores every `data/` directory, so `web/public/data/` and
`web/src/data/` were added with `git add -f`; new files there need the same until `.gitignore`
gets an exception.

## Internationalisation

- UI strings live in `src/i18n/cs.ts` (reference; defines the key type), `de.ts`, `en.ts`. The
  German and English dictionaries are typed as complete, so a missing key fails `typecheck`;
  `I18n` still falls back to Czech and then to the key at run time.
- Variable and index labels come from the manifest (`label: {cs, de, en}`), not from the
  dictionaries.
- Placeholders use `{name}`: `i18n.t('comparisonLimit', { max: 8 })`.
- To add a language: add it to `LANGUAGES` and `LOCALES` in `src/i18n/languages.ts`, add a
  dictionary and pass it in `main.ts`.

## Adding a new variable

The contract fixes the raw columns to `temp_c` and `rh_pct` and the daily columns to
`temp_*` / `rh_*`, so a new variable is **a contract change approved by the owner** first. Then:

1. `contract/types.ts` and `contract/validateSeries.ts`: add the column to `RawMonthFile` /
   `DailyFile` and validate it (same length as `t` / `date`).
2. `domain/RawSeries.ts`: add the column and extend `RawVariable`.
3. `app/ChartDataLoader.ts`: load it and map it to its daily column in `DAILY_COLUMN`.
4. `ui/SeriesChart.ts`: give it a scale and an axis (or a separate chart if its unit differs
   from °C and %).
5. Label and unit come from `manifest.variables`; add tests for validation and loading.

## Tests and coverage

`npm test` runs Vitest with V8 coverage over `src/**` and fails below 85 % of lines. Excluded
from coverage, because they are thin glue over Leaflet, uPlot/canvas or the page bootstrap and
are checked by the screenshots instead: `src/main.ts`, `src/ui/App.ts`, `src/ui/MapView.ts`,
`src/ui/SeriesChart.ts`. DOM components without those libraries (`SensorPanel`,
`TimeWindowControl`, `SensorList`, `HeaderView`, `HashSync`) are tested under jsdom.
