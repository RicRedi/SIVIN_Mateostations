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

## Changes after review round 1

1. **major, CSV formula injection** (`app/CsvWriter.ts`): text fields starting with `=`, `+`,
   `-`, `@`, tab or CR are prefixed with `'`; fields that are plain numbers (`-0,25`, `-5`) are
   left alone so they stay numeric. Test with `=HYPERLINK("http://x","c")`, `-5 m`,
   `+cmd|calc`, `@SUM(A1)`, tab and CR (`tests/ui/ChartCsv.test.ts`). Documented in
   `docs/web.md` (CSV export).
2. **minor, citation**: the Wallace & Hobbs (2006) value for `R_v` is marked
   "[source not verified]" in `domain/psychrometry.ts` and `docs/web.md`; the value 461.5 is
   kept (open question 3).
3. **minor, wheel**: `ZoomPanPlugin` no longer consumes a wheel that cannot zoom (out of the
   whole window, or in at the minimum span); the event bubbles, so the side panel scrolls. Test
   in `tests/ui/ZoomPanPlugin.test.ts`.
4. **minor, hourly precipitation**: `Resampler.hourlySums` replaced by
   `Resampler.hourlyPrecipitation`. Each amount is counted in the hour of the midpoint of its
   interval `(t_prev, t]`; an hour is `null` unless complete (every counted sample valid and
   covering ≤ 1.5 nominal steps = 2745 s). Hand-computed tests in `tests/auxiliary.test.ts`
   (0.2 / 0.7 / 0.5 mm on a synthetic 1830 s grid; a missed sample or a MANUAL_EXCLUDE sample
   makes the hour `null`; MISSING does not). Documented in `docs/web.md`.
5. **minor, performance**: measured with the reviewer's script
   (`/tmp/claude-0/review-3.7/perf.mjs`, 8 sensors × 29 days raw, dialog 1280 px, wheel event →
   second animation frame, 30 steps), same sandbox:
   - before (ff0f2e0): temp + RH median 66 / 73 ms (p90 77 / 84), five quantities median
     113 / 120 ms (p90 147 / 151) — two runs;
   - after: temp + RH median 63 / 65 / 76 ms (p90 84 / 89 / 86), five quantities median
     132 / 110 / 109 ms (p90 152 / 147 / 137) — three runs.

   No measurable change. Derived series were already not recomputed on zoom (a zoom step is
   only `setScale` on the x axis). A CPU profile and a Chromium trace of 20 wheel steps show
   about 13 ms of JavaScript per step (≈ 260 ms for 20) and about 95 ms per step in the
   compositor "Commit" (1909 ms for 20) — Chromium's software rasterisation of the large canvas
   in this GPU-less sandbox. Hiding the backdrop/shadow, the legend or all line dashes did not
   change the numbers. The only change kept: `ChartToolbar.update` skips re-rendering when its
   state did not change (no effect on the numbers). Cutting the raster cost would need fewer
   drawn points or series (e.g. decimation), which changes what the chart shows; not done.
   `docs/web.md` now quotes these numbers and the dependence on the number of quantities.
6. **nits**: `dailyColumnSeries.ts` imports before the type declaration; the zoom is kept when
   the new window is **equal** (`TimeWindow.equals`: bounds and resolution, tested in
   `tests/TimeWindow.test.ts`) instead of the same object; with no sensor selected the dialog's
   chart area shows "Není vybráno žádné čidlo. Vyberte čidla v nastavení grafu (Čidla)." (new key
   `chartDialogEmpty` cs/de/en; shown by CSS `:has()` while the chart section is hidden).

### Owner decisions of 2026-11-26 (open questions 1, 2, 4), implemented in this round

- **(a) CSV decimal mark: a comma in every UI language** (cs/de/en); separator stays `;`.
  `ChartCsv` uses a fixed `DECIMAL_MARK = ','`; the English test now expects `20,00`;
  `docs/web.md` updated.
- **(b) No leaf-wetness estimate at daily resolution.** `ChartQuantity.availableAt(resolution)`
  (default: every resolution; `LeafWetnessQuantity`: not `daily`). `ChartModel.build` leaves
  unavailable quantities out, so at daily resolution the band is not drawn and the column not
  exported. `QuantityControl` disables the check box and shows "– jen pro surová data a hodinové
  průměry" (new key `quantityNotDaily`, cs/de/en); the selection is kept and applies again at
  raw/hourly. Tests in `tests/quantities.test.ts`, `tests/ui/ChartCsv.test.ts`,
  `tests/ui/chartChrome.test.ts`; documented in `docs/web.md`.
- **(c) The open dialog is not in the URL** — kept as it is.

Open question 3 (absolute-humidity source) remains open; open question 5 is the orchestrator's.

Gates after the changes, re-run after rebasing onto `origin/main` (8fd1797), in `web/`:
`npm run lint` clean, `npm run typecheck` clean, `npm test` 31 files / 314 tests passed,
coverage lines 99.49 % (1983/1993), statements 99.47 %, branches 93.59 %, functions 99.46 %;
`npm run build` OK. Browser checks (Playwright, Chromium 1243): at daily resolution the legend
has no leaf-wetness series; a wheel down over the fully zoomed-out small chart scrolls the side
panel (scrollTop 100 → 300); after removing every sensor in the dialog the empty-state note is
displayed; no page errors.

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer agent, 2026-11-26. Diff `origin/main...HEAD` (ff0f2e0, 9999b94).

### Gates (run by the reviewer in `web/`, Node 22)

- `npm run lint` → clean.
- `npm run typecheck` → clean.
- `npm test` → 31 files, 307 tests passed; coverage of `src/**` lines 99.58 %, statements
  99.56 %, branches 93.75 %, functions 99.46 % (matches the hand-off note). `SeriesChart.ts`
  stays excluded from coverage (pre-existing exclusion), although it gained the zoom-keeping
  logic of this WP.
- `npm run build` → built (JS 328.56 kB, gzip 106.34 kB).

### What the reviewer verified independently

Browser checks with `vite preview` + Playwright (Chromium 1243, headless, tiles blocked); scripts
outside the repository; synthetic demo data only.

- **Wheel zoom around the cursor:** 5 notches at 25 % of the plot width: span 8 d → 90.7 h, the
  anchor time stayed at 25.3 % of the new view (rounding of the minute-resolution file name).
  Zoom out never leaves the loaded window.
- **Drag pan:** 100 px drag → shift −31.47 h vs. expected −31.45 h, span unchanged, uPlot's
  select box stays at width 0 (no conflict). **Shift + drag** zooms to the selection (expected
  span 31.46 h, got 31.45 h). **Double-click** resets to the window and disables "Celé okno".
- **Touch** (CDP `Input.dispatchTouchEvent`, 390 px, `hasTouch`): pinch 80 → 240 px gave span
  ratio exactly 1/3; a 100 px one-finger swipe panned −21.38 h vs. expected −21.37 h.
- **Dialog:** `role="dialog"`, `aria-modal="true"`, focus on ✕ on open; header/main/status are
  `inert`; 60 × Tab stays inside; the sensor picker, time window, resolution and quantity
  control are inside; toggling dew point + VPD in the dialog changes the hash (`q=…`), the CSV
  and, after closing, the panel check boxes (one store). Escape closes, focus returns to ⤢, no
  `inert` left, the panel order of sections is restored, the zoom is kept across open and close.
  At 390 px the dialog is full screen (390 × 844), plot 374 × 653, controls collapsed, no
  horizontal scroll (scrollWidth 390) before and after. Removing the last sensor inside the
  dialog keeps it open with only the picker (acceptable, see nit).
- **CSV:** BOM `EF BB BF`, `;`, CRLF, decimal comma (cs), both time columns, header with units;
  rows equal the zoomed view (686 rows for 8 days → 294 after zoom, first/last rows inside the
  view), columns = 2 + sensors × quantities (42 for 8 sensors × 5 quantities incl. the 0/1 leaf
  wetness). DST end 2026-10-25: local times 02:30, 02:00, 02:30 are disambiguated by the UTC
  column; year boundary 2026-12-31T23:30Z → local 2027-01-01 00:30 and file name
  `…_20261025T0230_20270101T0200.csv` correct.
- **Formulas** against `docs/indices/dew_point.md` / `vpd.md`: constants identical
  (17.625 / 243.04 °C; 0.6108 / 17.27 / 237.3 °C); `RH <= 0` → no value as in Python. Hand
  check of an exported demo row (19.9 °C / 67.9 %): dew point 13.796 → `13,80`, VPD 0.746 →
  `0,746` — match. Absolute humidity ρ_v = e_a/(R_v·T): 20 °C/50 % = 8.64 g/m³, 30 °C/100 % =
  30.33 g/m³ (standard tables ≈ 30.4), plausible; the formula is the standard ideal-gas form.
  R_v = 461.5 J kg⁻¹ K⁻¹ is the usual value; the Wallace & Hobbs page/value could **not** be
  verified by the reviewer either (no access in the sandbox).
- **QC masking:** derived quantities use the masked temperature/humidity (`combineSeries`), the
  off-site blanking is applied per sensor after derivation (`withoutBands`); precipitation and
  battery use mask 288 as documented (owner decision Q9).
- **Performance** (8 sensors × 29 days raw, dialog 1280 px, wheel event → second animation
  frame, headless software rendering in this sandbox): median 62 ms (temp + RH) and 112 ms
  (p90 144 ms) with five quantities. Slower than the worker's numbers (machine variance); wheel
  events are coalesced per frame, so it stays usable, but with several quantities it is not
  60 fps here.
- **Security / scope:** no credentials, tokens or portal content in the diff; every changed file
  is in the Files scope (`web/src/**`, `web/tests/**`, `docs/web.md`, README, this note,
  `docs/wp_log/img/WP-3.7-*.png`); no new npm dependency. README *What it does* updated.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | web/src/app/CsvWriter.ts:51 | CSV formula injection: header fields starting with `=`, `+`, `-`, `@` (sensor label first) are written as is; quoting does not stop Excel from evaluating them. | open |
| minor | web/src/domain/psychrometry.ts:24, docs/web.md:364 | Citation "Wallace & Hobbs 2006, 461.51" is stated as fact in code and docs but is from memory (hand-off note says so); not marked as unverified. | open |
| minor | web/src/ui/ZoomPanPlugin.ts:193 | Wheel over the small chart always `preventDefault`s, so scrolling the (scrollable) side panel with the wheel stops whenever the cursor passes over the chart, even when fully zoomed out and wheeling outwards. | open |
| minor | web/src/domain/Resampler.ts:89 | Hourly precipitation sums: a sample's "rain since the previous sample" is binned by its own time stamp, and a partial hour (masked/missing samples) gives a partial sum indistinguishable from a complete one (daily data have `precip_n_samples` for this). | open |
| minor | docs/web.md (performance), hand-off note | Performance with several quantities measured at 112 ms median per wheel step here (vs. 54 ms in the note); the claim "smooth" holds only for temp + RH in this sandbox. | open |
| nit | web/src/domain/dailyColumnSeries.ts:3-4 | `export type OptionalDailyColumn` sits between the import statements. | open |
| nit | web/src/ui/SeriesChart.ts:147 | Zoom keeping depends on `TimeWindow` object identity; untested because `SeriesChart.ts` is excluded from coverage. | open |
| nit | web/src/ui/ChartDialog.ts | After removing the last sensor inside the dialog the chart area is hidden and the dialog shows only the picker; acceptable, but could show the "select a sensor" hint. | open |

Details (input → wrong behaviour → suggested fix):

1. **major, CSV formula injection.** A sensor label such as `=HYPERLINK("http://x","c")` or
   `+cmd|calc` (probe with a stub catalog) is exported as
   `"=HYPERLINK(""http://x"",""c"") – Teplota (°C)"` / `+cmd|calc – Teplota (°C)`; Excel
   interprets such cells as formulas (DDE / hyperlink). Labels come from the registry, so the
   risk is low, but the export is meant to be opened in Excel by the public and the fix is cheap.
   Fix: in `CsvWriter.field` prefix text fields starting with `=`, `+`, `-`, `@`, tab or CR with
   `'` (OWASP CSV injection), applied to text cells only (not to numbers written by `number()`,
   so negative values stay numeric); add a test.
2. **minor, unverified citation.** Mark it as unverified in the code comment and `docs/web.md`
   (e.g. "[citation not verified]") until the owner confirms the source (open question 3), per
   CLAUDE.md "never invent citations".
3. **minor, wheel captures page scroll.** Wheel down over a fully zoomed-out chart → panel does
   not scroll. Fix: do not `preventDefault` when the view already covers the window and the
   wheel zooms out (let the event scroll the panel), or document the behaviour.
4. **minor, hourly precipitation.** Either bin a sample into the hour of `t − ε` (rain fell
   before its time stamp) or document the up-to-one-sample shift; consider documenting that
   hourly sums ignore coverage.
5. **minor, performance.** Record the reviewer's numbers or note the dependence on the number
   of quantities in `docs/web.md`; no code change required.

### Deviations assessment

- Sensor picker in the dialog: reasonable reading of "which curves are shown"; same component,
  moved — accepted.
- Derived values from hourly/daily means: documented, honest; owner question 2 is the right
  place — accepted.
- Precipitation/battery with mask 288: consistent with the pipeline and Q9 — accepted.
- Precipitation/battery drawn here instead of WP-3.4: the brief asked for it — accepted.
- `q=` in the hash, markers hidden/clipped outside the zoom, tick decimals: small, needed, in
  scope — accepted.
- Zoom hint always visible: harmless — accepted.

Re-review after round 1 needs only finding 1 fixed (and ideally 2); the rest may go to *Out of
scope* if the worker prefers.
