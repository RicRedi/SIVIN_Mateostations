# WP-3.7 — Chart explorer: maximise, zoom and pan, derived quantities, CSV export

## Summary

Web-only workpackage approved by the owner on 2026-11-26 (not yet in MIGRATION_PLAN §4). The
chart of the map portal can now be **maximised** into a modal dialog (⤢, "Zvětšit graf") that
moves the existing chart and all its controls — sensor picker, time window, resolution and the
new quantity control — into itself, so there is one chart, one set of controls and one
`AppStore`. **Mouse wheel zoom** around the cursor, **drag pan**, Shift + drag selection,
double-click reset and touch **pinch / swipe** work in the small and the maximised chart, inside
the loaded window only (`ZoomPanPlugin` with the arithmetic in `domain/ViewRange`). **Derived
quantities** (dew point, VPD, absolute humidity, estimated leaf wetness as bands) and the
auxiliary **precipitation** (bars) and **battery voltage** can be switched on per quantity, with
at most one third axis. **"Stáhnout CSV"** exports exactly what the chart shows (zoomed range,
resolution, sensors, quantities) as UTF-8-with-BOM, `;`-separated CSV with local and UTC time.
The shown quantities are part of the URL hash (`q=`).

## Changed files

New (`web/src`):
- `domain/psychrometry.ts` — dew point (Magnus, a = 17.625, b = 243.04 °C), `e_s`/`e_a`/VPD
  (FAO-56 eq. 11, 0.6108 / 17.27 / 237.3 °C as `docs/indices/vpd.md`), absolute humidity
  (ideal-gas law, `R_v` = 461.5 J kg⁻¹ K⁻¹), leaf-wetness proxy RH ≥ 90 %.
- `domain/derivedSeries.ts` — `combineSeries`, `leafWetnessIndicator`, `wetIntervals`.
- `domain/quantities.ts` — quantity ids, extra-axis group, default.
- `domain/ViewRange.ts` — visible range value object; zoom/pan/clamp math, wheel factor,
  minimum span.
- `app/ChartQuantities.ts` — `ChartQuantity` ABC, `MeasuredQuantity`, `PsychrometricQuantity`,
  `LeafWetnessQuantity`, `QuantityRegistry`, `createQuantityRegistry`.
- `app/CsvWriter.ts` — CSV text (BOM, `;`, CRLF, quoting, decimal mark).
- `state/QuantitySelection.ts` — normalise / toggle the shown quantities.
- `ui/ChartModel.ts` — aligned columns (sensor × quantity), off-site blanking, wetness lanes,
  rows inside a view; shared by chart and CSV.
- `ui/ChartSeriesFactory.ts` — uPlot scales, axes, series per quantity style; tick decimals.
- `ui/ZoomPanPlugin.ts` — uPlot plugin (wheel, drag, Shift-select, double-click, pinch).
- `ui/WetnessBands.ts` — leaf-wetness lanes in `drawClear`.
- `ui/ChartToolbar.ts` — ⤢ / Celé okno / Stáhnout CSV buttons, zoom hint; `ChartExport`.
- `ui/ChartDialog.ts` — the maximised chart (moves elements in and back; reuses `ModalSheet`).
- `ui/QuantityControl.ts`, `ui/QuantityLabels.ts` — quantity check boxes / third-axis radios;
  labels.
- `ui/ChartCsv.ts`, `ui/FileDownload.ts` — CSV of the visible data, file name; Blob download.

Changed (`web/src`): `main.ts` (composition), `ui/SeriesChart.ts` (quantities, plugin, fill
height in the dialog, zoom kept across redraws), `ui/App.ts` (`onQuantitiesChange`, quantities
redraw without reload), `ui/SensorPanel.ts` (`quantitySlot`), `ui/EventMarkers.ts` (clip to the
plot, hide markers outside the zoomed range), `app/ChartDataLoader.ts` (loads `precip_mm`,
`battery_v`), `domain/RawSeries.ts` (auxiliary columns), `domain/Resampler.ts` (hourly sums,
auxiliary mask), `domain/QcFlags.ts` (`AUXILIARY_DISPLAY_EXCLUDE_MASK` = 288),
`domain/dailyColumnSeries.ts` (optional daily columns), `state/AppState.ts`,
`state/HashStateCodec.ts` (`q=`), `i18n/cs.ts`, `de.ts`, `en.ts` (25 new keys each),
`styles.css`, `contract/types.ts` (comment only).

Tests (`web/tests`): new `psychrometry`, `derivedSeries`, `ViewRange`, `quantities`,
`auxiliary`, `ui/ChartCsv` (ChartModel, CsvWriter, ChartCsv), `ui/ZoomPanPlugin`,
`ui/ChartSeriesFactory`, `ui/chartChrome` (ChartDialog, ChartToolbar, ChartExport, FileDownload,
QuantityControl, WetnessBands); extended `state`, `ui/App`, `ui/EventMarkers`.

Docs: `docs/web.md` (architecture tree and table rows, new section *Chart explorer (WP-3.7)*,
real-data notes, "Adding a new variable", tests), `README.md` (*What it does*, map portal line),
this note, screenshots `docs/wp_log/img/WP-3.7-{chart-1280,zoom-1280,dialog-1280,chart-390,
dialog-390,dialog-controls-390}.png` (synthetic demo data).

## How it was verified

In `/home/user/wt/wp-3.7/web` (Node 22):

- `npm run lint` → clean (0 problems).
- `npm run typecheck` → clean.
- `npm test` → 31 files, **307 tests passed**; coverage of `src/**` (with the existing
  exclusions `main.ts`, `MapView.ts`, `SeriesChart.ts`): lines 99.58 % (1939/1947), statements
  99.56 %, branches 93.75 %, functions 99.46 %. New and changed files: every file 100 % lines
  except `ui/ZoomPanPlugin.ts` 98.5 % and `ui/ChartSeriesFactory.ts` 98.33 %.
- `npm run build` → built (JS 328 kB, gzip 106 kB).
- Expected values in the formula tests are hand-computed from the formulas (e.g. dew point
  20 °C / 50 % = 9.2611 °C, the value `docs/indices/dew_point.md` quotes; `e_s(0 °C)` = 0.6108 kPa;
  absolute humidity 0 °C / 100 % = 610.8 / (461.5 · 273.15) = 4.8454 g/m³); the inputs are
  synthetic round numbers.
- Browser checks (`vite preview` + Playwright with Chromium 1243 at `/opt/pw-browsers`,
  headless, map tiles blocked): no page errors; wheel zoom enables "Celé okno"; drag pans; the
  dialog opens with `role="dialog"`, focus on ✕, Escape closes it and focus returns to ⤢;
  CSV download is named `sivin_77678271-77799986_<from>_<to>.csv`, starts with a BOM, has the
  documented header and decimal commas; touch pinch (80 → 280 px) zoomed 7 d → 2 d and a
  one-finger swipe of 120 px panned ~22 h (CDP `Input.dispatchTouchEvent`, touch emulation).
  Precipitation bars and the battery axis were checked against a scratch copy of
  `web/tests/fixtures/python-site` with invented non-zero precipitation and battery values
  (not committed).
- Performance, 8 sensors × 30 days raw (`#…&w=30d&r=raw`), maximised dialog at 1280 px: time
  from a wheel event to the second animation frame after it, 40 steps — median 33 ms with
  temperature + humidity (= two frame intervals, i.e. the redraw fits in a frame), median 54 ms,
  p95 117 ms with four quantities (32 series). Headless Chromium without GPU in the sandbox.
- Screenshots: `docs/wp_log/img/WP-3.7-*.png` (1280 px and 390 px: small chart with dew point,
  leaf wetness and VPD; after a wheel zoom; maximised dialog with controls; phone dialog with
  the controls collapsed and expanded).

## What did not work / what was not verified

- **No real phone / no real mouse hardware.** Touch was verified only with Chromium's touch
  emulation; Safari/iOS and Firefox were not tried. `touch-action: pan-y` keeps vertical page
  scrolling native; whether iOS Safari delivers the second pointer reliably was not checked.
  Double-tap to reset is not implemented on touch (the "Celé okno" button does it).
- **Performance** was measured only in headless software-rendered Chromium (numbers above); not
  on a desktop browser with GPU or a phone.
- **Precipitation and battery** could not be shown with the demo data (the synthetic fixture in
  `web/public/data` has no such columns; the Python fixture has precipitation 0 and battery
  constant 3.6 V). Rendering was checked on a scratch copy with invented values only.
- **Absolute humidity:** the formula (ideal-gas law, `R_v` = 461.5 J kg⁻¹ K⁻¹, `e_a` from FAO-56
  as for the VPD) is standard; the citation "Wallace & Hobbs, *Atmospheric Science*, 2nd ed.,
  2006 (461.51)" is from memory, the page was not checked in the sandbox.
- Screen readers were not tried; the dialog follows the existing `ModalSheet` pattern
  (`role="dialog"`, `aria-modal`, inert background, Tab trap) and the buttons have accessible
  names. Zoom/pan has no keyboard equivalent beyond "Celé okno" (not required by the brief).

## Deviations

- **The sensor picker is in the dialog too** (with its chips), not only window, resolution and
  quantities: "which curves are shown" also means which sensors. It is the same component,
  moved, so its phone sheet and limits behave as in the panel.
- **Derived values at hourly and daily resolution are computed from the shown means**
  (hourly means; `temp_mean`/`rh_mean` of `daily.json`), not as means of per-sample values,
  because daily per-sample data are not loaded at daily resolution. For non-linear formulas the
  difference is small but real; documented in `docs/web.md`. The leaf-wetness band at daily
  resolution is therefore "daily mean RH ≥ 90 %", which is coarse.
- **Precipitation and battery** are masked with PRE_DEPLOYMENT | MANUAL_EXCLUDE (288), the
  pipeline's `DEFAULT_AUXILIARY_EXCLUDE` (owner decision Q9), not with the temperature/humidity
  display mask — "QC-masked rows stay masked" holds for every quantity derived from temperature
  and humidity; rain in a row with missing humidity is shown, as in `daily.json`.
- Drawing precipitation and battery was listed as WP-3.4 in `docs/web.md`; it is done here as
  the brief asks. WP-3.4 (index cards, season curves) is not touched.
- Uncovered by the brief, added because needed: the chart quantities in the URL hash (`q=`,
  omitted for the default), event markers hidden and canvas drawing clipped outside the zoomed
  range, axis tick decimals derived from the tick spacing (the third axis showed duplicate
  labels such as "0,5 0,5" for 0.05 mm steps).
- The zoom hint text is always shown above the chart (small, muted), not only in the dialog.

## Out of scope

- `web/scripts/generate-fixture.mjs` / `web/public/data/`: the synthetic demo has no
  `precip_mm`/`battery_v`, so the new quantities show nothing in the demo. Proposal: add
  synthetic precipitation and battery columns (labelled synthetic) to the generator.
- `web/scripts/screenshot.mjs` only produces the WP-3.1 screenshots; the WP-3.7 screenshots were
  made with a throw-away Playwright script. Proposal: extend the script with the chart-explorer
  shots.
- `docs/architecture.md` does not list web modules at this level; no change needed there.

## Open questions for the owner

1. Is the **CSV decimal mark per UI language** right (comma in cs/de, point in en; separator
   always `;`)? The alternative is a comma everywhere.
2. **Derived quantities at hourly/daily resolution** from the means (see *Deviations*) — fine, or
   should the leaf-wetness band be hidden at daily resolution?
3. **Absolute humidity** formula and constant — confirm, or name the source you prefer.
4. The URL hash now carries the shown quantities (`q=`); the open dialog is **not** in the URL.
   OK?
5. WP-3.7 still needs an entry in MIGRATION_PLAN §4 (orchestrator).

## Review

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
