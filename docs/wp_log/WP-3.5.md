# WP-3.5 — Sensor picker for larger networks

## Summary

The registry replaces `site` with two required, nullable keys `municipality` (obec) and `track`
(viniční trať); the committed `sensors/sensors.geojson` is migrated with `null` values (nothing
guessed from coordinates), the JSON Schema is regenerated, and an old file with `site` still
loads (deprecated alias, read as `track` with a warning). `sivin build-site` now publishes the
**public projection** of the registry: every sensor's `notes` and every placement's `note` are
`null` (owner decision 2026-10-05); a test puts marker texts into all notes and checks that
none reaches any site file. In the web, the checkbox list is replaced by `SensorPicker`: a
disclosure button "Čidla (n/N) ▾", search (id, label, municipality, track, variety; case- and
diacritics-insensitive), groups municipality → track with tri-state "select all" within the
8-sensor limit, retired sensors last and greyed, chips in the line colour, keyboard support and
a full-screen sheet on phones. The map clusters overlapping markers (`leaflet.markercluster`,
bundled). The synthetic web fixture has 20 sensors in three fictional municipalities.

## Changed files

Commits on `wp/3.5-sensor-picker` (base `c809d21` = approved `wp/3.2-site-builder` + plan
update):

| Commit | Content |
|---|---|
| `35a2df5` | `src/sivin/registry/{model,geojson,gpx}.py`, `sensors/sensors.geojson`, `sensors/sensors.schema.json`; `tests/registry/{conftest,test_model,test_registry,test_geojson}.py`, `tests/registry/test_site_migration.py` (new) |
| `3291499` | `src/sivin/site/public_registry.py` (new), `src/sivin/site/{site_files,model,builder}.py`; `tests/site/{test_site_files,test_service}.py`, `tests/site/test_public_registry.py` (new); regenerated `web/tests/fixtures/python-site/sensors.geojson` |
| `39dfbe8` | `web/src/ui/picker/{SensorPicker,PickerTree,SensorChips}.ts` (new), `web/src/app/{SensorGroups,SensorQuery}.ts` (new), `web/src/state/GroupSelection.ts` (new), `web/src/ui/ClusterIcon.ts` (new), `web/src/ui/SensorList.ts` (deleted), `web/src/{main.ts,styles.css}`, `web/src/ui/{App,MapView,SensorPanel}.ts`, `web/src/app/SensorCatalog.ts`, `web/src/contract/{types,validateSensors}.ts`, `web/src/i18n/{cs,de,en}.ts`, `web/package.json`, `web/package-lock.json`; `web/tests/picker.logic.test.ts`, `web/tests/ui/SensorPicker.test.ts` (new), `web/tests/{app,contract,pythonSite}.test.ts`, `web/tests/ui/{App,components}.test.ts`; `web/scripts/generate-fixture.mjs`, regenerated `web/public/data/**` (one commit, so its tests run green on their own) |
| `6fddb64` | `docs/sensors.md`, `docs/site.md`, `docs/web.md`, `docs/wp_log/img/WP-3.5-*.png`; a wording fix of the `track` description in `model.py` + schema |
| this commit | `docs/wp_log/WP-3.5.md` |

### Public API

```python
# sivin.registry.model
Sensor(..., municipality: str | None, track: str | None, ...)   # both required, nullable
DEPRECATED_SITE_KEY = "site"; SITE_REPLACEMENT_KEYS = ("municipality", "track")
# sivin.registry.geojson
GeoJsonRegistryStore.loads(text: str | bytes, source="<text>") -> SensorRegistry
GeoJsonRegistryStore.document(registry) -> dict        # dumps() = render_json(document())
# sivin.site
PublicRegistryProjection(store=None).document(registry_file: bytes) -> dict
PublicRegistryProjection.sensor(sensor) / .placement(placement)   # notes / note -> None
PublicRegistryWriter(projection=None, redactor=None)   # replaces RegistryCopyWriter
default_site_writers(...)                              # signature unchanged
```

```ts
// web
SensorGrouping.group(sensors): MunicipalityGroup[]      // app/SensorGroups.ts
SensorQuery.parse(text).matches(sensor); foldText(text) // app/SensorQuery.ts
checkState(groupIds, selected); toggleGroupInSelection(selected, groupIds, max = 8)
type LimitNotice                                        // state/GroupSelection.ts
SensorPicker(root, catalog, i18n, colors, { onSensorToggle, onGroupToggle })
App.onGroupToggle(ids); AppViews.picker.render(ids, notice)   // was AppViews.list
parseSensorsGeoJSON(value, file?, warn?)                // municipality, track; site ignored
SensorInfo: + municipality, track, status; - site
```

No new configuration section and no CLI change: the public projection is part of
`default_site_writers`, which the factory already uses (nothing for WP-1.7 to wire).

### Decisions

- **Old `site` key: deprecated alias, not an error.** `site` is read as `track` (a single
  site name is closest to a vineyard track), `municipality` as `null`, with a warning naming
  the sensor; saving writes the new keys. `site` together with `municipality` or `track` is an
  error (`'site' was replaced by 'municipality' and 'track' (2026-10-05); remove 'site', …`).
  Reason: old files (and `tests/quality/test_offsite.py`, outside this scope, which still builds
  a sensor with `site`) keep working, while the JSON Schema accepts only the new keys. The web
  ignores `site` with a warning and does not guess.
- **Projection through the models**, not by editing JSON: the published file is validated and
  canonical (same text form as the registry file). The projection's store has no
  allowed-area check (the registry was already validated with the configured area).
- **Group "select all" works on the visible sensors**: during a search it selects the matches
  only; tri-state and the "selected/visible" count also refer to the visible sensors.
- **Clustering radius 28 px** (`2 × marker radius + 8`): markers cluster only where they would
  overlap, so the four real sensors (≈ 100 m apart) stay separate at the initial zoom.

## How it was verified

In `/home/user/wt/wp-3.5`:

- `make lint` → ruff check + format: all checks passed, 292 files formatted.
- `make type` → mypy --strict: no issues in 177 source files.
- `make test` / `make cov` → **1869 passed**; total coverage 99 %. Changed/new modules:
  `registry/model.py` 100 %, `registry/geojson.py` 100 %, `registry/gpx.py` 100 %,
  `site/site_files.py` 100 %, `site/public_registry.py` 96 % (one partial branch).
- `tests/e2e/test_site.py` passes against the regenerated python-site fixture
  (`.venv/bin/python -m tests.site.python_site`: only `sensors.geojson` changed — new keys,
  notes `null`).
- `cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build` → lint
  and typecheck clean, **200 tests passed** (19 files), line coverage 99.57 % (all new picker
  files 100 %), build OK (bundle 297 kB / 96 kB gzip).
- Fixture: `npm run fixture` twice → byte-identical; 1.4 MB, 77 files; the series files of the
  four original sensors are unchanged (the random stream is preserved).
- Browser check (Chromium 1194 via `playwright-core`, `vite preview`, same procedure as
  `npm run screenshot` but with a scratch script, see below): no page errors, no horizontal
  scroll at 1440 px and 390 px; Enter on a focused cluster badge zoomed in (6 → 1 cluster
  visible); Ctrl+click on a marker added it to the comparison (`#s=90000201,90000303`);
  "select all" of Obec A with 2 sensors selected added 6 and showed the limit notice.
  Screenshots, all looked at (layout fixed: cluster count was not centred because
  `leaflet.css` overrides `display`; the selector is now qualified):
  `docs/wp_log/img/WP-3.5-desktop-picker.png` (open, search "ryzlink", groups selected),
  `WP-3.5-desktop-limit.png` (group selection hit the limit), `WP-3.5-desktop-map.png`
  (clustered map), `WP-3.5-desktop-cluster-zoomed.png` (after Enter on a cluster),
  `WP-3.5-phone-picker.png` (full-screen sheet, search "ryzl"), `WP-3.5-phone-map.png`
  (clustered map, chips).

## What did not work / what was not verified

- **Map tiles** do not load in the sandbox (no internet), so the screenshots have a grey
  background.
- **Screen readers** were not tested; only the ARIA attributes (disclosure `aria-expanded` /
  `aria-controls`, native checkboxes with `indeterminate`, labelled group checkboxes, chips'
  remove buttons, cluster badges' hidden text) and keyboard behaviour in jsdom and Chromium.
- **Real phones / touch, Firefox, Safari** were not tested; only a 390 px Chromium viewport.
- **Hundreds of sensors** were not tried; the tree is built once and updated in place
  (20 sensors in the fixture).
- `leaflet.markercluster` 1.5.3 is the plugin of the Leaflet organisation and works with
  Leaflet 1.9.4, but it has had no release since 2021 (npm metadata last modified 2022). If
  "maintained" is meant strictly, `supercluster` (9.1.0, actively released) plus own Leaflet
  glue would be the alternative.
- The real municipality and track of the four sensors are unknown; they are `null`.

## Deviations from the brief / scope

- `web/package.json` and `web/package-lock.json` are not in the listed Files scope; they had to
  change to bundle `leaflet.markercluster` (dependency) and `@types/leaflet.markercluster`
  (dev), as the brief asks for an npm package without CDN.
- `web/scripts/screenshot.mjs` (not in scope) was not changed; the WP-3.5 screenshots were
  taken with an equivalent scratch script (same Chromium, `playwright-core`, preview URL).
- `vite.config.ts` needed no change: the clustering glue lives in `MapView.ts`, which is
  already excluded from coverage; `ClusterIcon` is tested.

## Out of scope

- `docs/cli.md:249` still says `sensors.geojson` is a "copy of the registry"; it is the public
  projection now (`docs/site.md`).
- `tests/quality/test_offsite.py:54` builds a sensor with `"site": None`; it passes through the
  deprecated alias (with a warning) — switch it to `municipality`/`track`.
- `web/scripts/screenshot.mjs`: add the WP-3.5 shots (picker open, clustered map) so the
  screenshots are reproducible with `npm run screenshot`.
- `ui/SensorPanel` shows its own limit hint (`comparisonLimit` with `max: selected.length`)
  under the chips in addition to the picker's notice; one of them could go.
- The manifest's per-sensor `status` and the registry `status` both exist; the picker uses the
  registry's. WP-3.4 should pick one source.

## Open questions for the owner

1. Please fill in `municipality` and `track` for the four sensors in
   `sensors/sensors.geojson` (docs/sensors.md, *Municipality and track*), and `variety` (Q4).
2. `portal_name` (`"8615620 77678271"`) stays public because the contract requires it. Is the
   prefix `8615620` (it looks like an account/gateway number at the provider) fine to publish?
   If not, the projection could blank it, but that is a contract change (§2.4/§2.6).
3. Keep the deprecated `site` alias permanently, or turn it into an error after the migration
   (e.g. once WP-3.3 writes the registry)?
4. Accept `leaflet.markercluster` (stable, no release since 2021), or switch to `supercluster`
   with own glue?

## Review

Verdict: APPROVE (round 1)

Reviewer: independent review agent; the diff `c809d21...8fcf98b` was read in full (Python, web, docs, fixtures). Throwaway scripts and screenshots are in
`/tmp/claude-0/review-3.5/`. They are not committed.

### Gates (re-run by the reviewer in `/home/user/wt/wp-3.5`)

- `make lint`: ruff check passed; ruff format reported 292 files already formatted. `make type`: mypy --strict reported no issues in 177 source files. `make test`: 1869 passed.
- `make cov`: TOTAL 99 %. `registry/model.py`, `registry/geojson.py` and `site/site_files.py` are at 100 %; `site/public_registry.py` is at 96 % (the partial branch is at 36->38).
- `cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build`: every step exited 0. Vitest ran 19 files with 200 tests passed, 99.57 % line coverage.
  The build is 297.15 kB of JS (95.86 kB gzip) and 28.67 kB of CSS. The base `c809d21`, built the same way, is 251.21 kB of JS (83.78 kB gzip) and 23.49 kB of CSS. So the WP adds +45.9 kB JS (+12.1 kB gzip) and +5.2 kB CSS. `leaflet.markercluster` alone is 34.1 kB minified (8.8 kB gzip). npm prints EBADENGINE warnings (jsdom wants Node ≥ 22.22.2, the sandbox has 22.22.0). These warnings do not come from this WP.

### What was verified in a real browser

The browser was Chromium 1194 driven by `playwright-core` against `vite preview`, with tile requests aborted. Viewports were 1440×900 and 390×844 (`isMobile`, `hasTouch`).

- **Grouping and order:** the fixture shows Obec A → Trať 1, 2; Obec B → Trať 3, 4; Obec C → Trať 5, 6, Nezařazeno; then Nezařazeno → Nezařazeno. The retired sensor 90000302 is last in Trať 4, greyed and struck through, with "· vyřazeno".
- **Search:** `RYZLÍNK`, `muller`/`müller` and `palava`/`pálava` are case- and diacritics-insensitive. `trať 4 zweig` uses AND semantics. A search with no match shows the empty message.
- **Tri-state under a search:** with "ryzlink" active, the group "select all" of Obec B selected only the 2 matches. After the search was cleared, Obec B and Trať 3 showed `mixed`.
- **8-sensor limit:**
  - A group toggle stopped at 8 and showed the notice "ze skupiny bylo přidáno jen 6".
  - A single checkbox beyond the limit was reverted, and the hash was unchanged.
- **Keyboard and focus:**
  - Escape closes the panel and returns focus to the trigger. Enter on the trigger opens it and focuses the search field. An outside click closes it.
  - ArrowDown/ArrowUp walk the visible controls.
  - Removing a chip moves focus to the next chip.
  - Collapsed groups re-expand when a search starts.
- **URL hash:** a reload with the same hash restores the selection and the chips. Unknown ids are dropped.
- **Phone:** the sheet is full-screen (390×844), and "Hotovo" returns focus to the trigger. There is no horizontal scroll at 390 px, also with 8 chips.
- **Map:**
  - Clicking a cluster zooms in (6 → 0 clusters). Enter on a focused cluster zooms in.
  - Clusters have `role=button` and the name "Skupina čidel: n – přiblížit".
  - A cluster that contains a selected sensor gets the ring, also when the sensor was selected in the picker.
  - After zoom-out/zoom-in, markers that re-enter the map get `tabindex=0`, `role=button`, `aria-label` and `aria-pressed` again. Enter on a marker selects it.
  - Two sensors with identical coordinates spiderfy at maximum zoom, and both spider markers are decorated.
- **Accessibility tree:** the pattern is a disclosure: the button has `aria-expanded` and `aria-controls`, and the panel is `role=group` labelled "Výběr čidel (n/N)". Native checkboxes are used. The group checkbox is exposed as `checkbox "Vybrat vše: Obec A" [checked=mixed]`, so the tri-state is announced. The group toggle is `button "Obec A 6/7" [expanded]`. The chip remove buttons are named "Odebrat … ze srovnání".
- **Scale:** I generated a synthetic site with 200 sensors in 10 municipalities × 7 tracks, a retired sensor every 17th, 2 identical positions, and notes with `<script>` plus 20 000 characters.
  - On desktop it rendered with no page error, load to chart in ≈ 0.4 s, and JS heap ≈ 9 MB. Opening the picker took ≈ 17 ms, search per keystroke 6–14 ms (26 ms when cleared back to all 200 rows), and a group toggle including the app render 50–70 ms. DOM nodes went from ≈ 5.8k to ≈ 11.7k.
  - The picker stays responsive.
  - The map shows 91 cluster badges on desktop and 42 on the phone (reviewer screenshots `s1440-picker.png`, `s390-map.png`).
- **Privacy:**
  - I fed the Python projection notes containing HTML/`<script>`, 20 000-character text, quotes and backslashes, and a U+2028 character. Each sensor had two placements, each with its own note. No note text survived.
  - The existing `test_no_registry_note_reaches_the_site` builds the whole site and greps every output file. It passes.
  - The web neither reads nor renders `notes`/`note`. `SECRET_NOTE` was not in the DOM of the 200-sensor page, and no dialog fired.
- **Registry migration:** the cases were tried through `GeoJsonRegistryStore.loads`.
  - A `site` string becomes `track`, with a warning naming the sensor. A `site` of null becomes null/null.
  - `site` together with `municipality` and/or `track` is an error that names the keys.
  - A missing `track` gives "Field required". After a save, the file contains no `site`.
  - The JSON Schema (sync test green) and the Python loader agree on every valid file. They differ only on `site`, by design (schema rejects it, loader accepts it with a warning), and `docs/sensors.md` documents this.
  - The web contract reads `municipality`/`track` and ignores `site` with a warning.
  - The Python side always writes the new keys, so the web never sees `site` from a build.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | `web/src/ui/picker/SensorPicker.ts:152` | The full-screen sheet on phones is not modal. Tab (and screen-reader swipe) leaves the sheet into content it covers: chips, time-window buttons, step select. | fixed in `ba5205b` (`ModalSheet`: `role=dialog`, `aria-modal`, rest of page `inert`, Tab trapped) |
| minor | `web/src/state/GroupSelection.ts:44` | At the limit, a partially selected group cannot be cleared through its checkbox, and the notice reads "přidáno jen 0". | fixed in `ba5205b` (any selected member → checkbox clears the group; no "jen 0" notice) |
| minor | `web/src/app/SensorQuery.ts:35` | Plain substring AND matching makes 1-character and digit tokens match broadly. | fixed in `ba5205b` (word-start matching for every field; tests incl. "obec b trat 4") |
| minor | `web/src/ui/MapView.ts:32` | The 28 px cluster radius barely declutters a dense network, and grey badges hide the temperature colours at low zoom. | fixed in `ba5205b` (badges coloured by mean temperature; radius 42 px after a 200-sensor check) |
| minor | `src/sivin/registry/model.py:304` | `municipality`/`track` with leading or trailing whitespace are accepted and form separate groups. The docs warn about this but the loader does not check it. | fixed in `86ebe7b` (strip + collapse whitespace on load, with a warning) |
| minor | `web/scripts/generate-fixture.mjs:47` | Fictional municipality, track and variety are given to the four **real** sensor ids. Before this WP they were null. | fixed in `ba5205b` (real ids keep null municipality/track/variety) |
| minor | `web/src/ui/picker/PickerTree.ts:129` | During a search the group checkbox acts on the matches only, but its name and its full check suggest the whole group. | fixed in `ba5205b` ("Vybrat nalezená v …" + "nalezeno m z n" during a search) |
| nit | `src/sivin/registry/model.py:326` | Errors caused by a bad `site` value are reported against `track`. The "remove `site`" error is followed by a second error on the next load. | fixed in `86ebe7b` (errors name `site` and the key still to add) |
| nit | `web/src/ui/SensorPanel.ts:59` | The limit is reported twice: the picker notice, and the panel hint "Srovnat lze nejvýše 8 čidel" (the worker noted this). | fixed in `ba5205b` (notice only in the picker) |
| nit | `web/src/styles.css:400` | Retired sensors are struck through, which reads as "unavailable/deleted", but their data are kept (§0.5). | fixed in `ba5205b` (greyed, not struck through) |

Details (input → behaviour → suggested fix):

1. **Phone sheet not modal.** Input: 390 px, open the picker, press Tab about 15 times. Behaviour: focus moves past the last tree item to `Odebrat 90000201…`, then `24 h`, `7 dní`, … `SELECT`, all hidden behind the sheet. Fix: in the sheet layout, mark the rest of the page `inert` while the panel is open (or make the panel `role=dialog aria-modal=true` and trap focus). Keep the desktop disclosure as it is.
2. **Group at limit.** Input: 8 sensors selected, 6 of them from Obec A. Behaviour: clicking Obec A's mixed checkbox adds nothing, keeps it mixed and shows "Srovnat lze nejvýše 8 čidel – ze skupiny bylo přidáno jen 0." The only way to clear the group is chip by chip. Fix: when `room === 0` and the group is `some`, either deselect the group's selected sensors, or at least show the plain `comparisonLimit` text instead of "jen 0".
3. **Search tokens.** Input: `obec b trat 4`. Behaviour: Obec C's Trať 5 and Trať 6 match as well, because "b" ⊂ "obec" and "4" ⊂ id "90000401". Input `trat 4` also returns Obec C. Fix (optional): match tokens against word starts of the folded fields (`startsWith` per word) and keep substring matching only for ids. Not wrong per the brief ("every word occurs"), but surprising with real names.
4. **Cluster radius.** Input: 200 synthetic sensors. Behaviour: 91 badges of 2–3 sensors, almost touching, on desktop; no temperature colour is visible until zoomed in. Fix: make `maxClusterRadius` a function of zoom (larger at low zoom), or set `disableClusteringAtZoom`. Optionally colour the badge by the members' median temperature. Today's 20-sensor fixture looks fine (worker's screenshots).
5. **Whitespace in names.** Input: `"municipality": "Mikulov "`. Behaviour: the file loads, and the web shows two groups "Mikulov". Fix: a field validator on `municipality`/`track` (in scope) that rejects leading/trailing whitespace with a message, or `str_strip_whitespace`, mirrored in the schema with a `pattern`.
6. **Real ids in the fixture.** `77678271` shows "Obec A / Trať 1 / Ryzlink rýnský" in the demo. The README and the "Ukázková data" badge mark it as fictional, but the demo now attributes a variety and a location to a real device. Fix: leave the four real sensors `null` (they would also exercise *Nezařazeno*) and give the groups only to the `(demo)` ids.
7. **Search-scoped group checkbox.** Phone screenshot `WP-3.5-phone-picker.png`: "ryzl" → Obec B shows fully checked (2/2) although 4 of its 6 sensors are not selected. Fix: name the checkbox to match its behaviour during a search (e.g. "Vybrat nalezená: Obec B") and/or show the group's total next to the visible count.
8. **`site` errors.** `site: ""` → "track: String should have at least 1 character". `site` + `municipality` → "remove 'site'…", and after removal the next load fails with "track: Field required". Fix: validate the `site` value in `_migrate_site` and name `site` in the message, and say "add 'track' too" when one of the two keys is missing.

### Dependency assessment (`leaflet.markercluster` vs `supercluster`)

- **`leaflet.markercluster` 1.5.3**
  - License: MIT, compatible.
  - Last release: 1.5.3 in 2021; the npm metadata was last modified 2022-06-19.
  - Peer dependency: `leaflet ^1.3.1`.
  - Size: +34 kB min / +8.8 kB gzip JS plus 0.9 kB CSS.
  - It works with Leaflet 1.9.4 in all the checks above: zoom-on-click, spiderfy of identical points, keyboard access to cluster and marker elements.
  - Its UMD build depends on the global `L`, which Leaflet 1.x's `leaflet-src.js` sets. I expect it to break if the project moves to an ESM-only Leaflet 2.x, but I did not verify this. I did not check its issue tracker (no network); the worker's tests and mine found no runtime error.
- **`supercluster` 9.1.0**
  - License: ISC.
  - Actively released; the npm metadata was modified 2026-09.
  - Small, with `kdbush` as its only runtime dependency.
  - It is only an index: rendering cluster badges, zoom-on-click (`getClusterExpansionZoom`), re-rendering on `moveend`, spiderfying identical coordinates, and keyboard decoration would all be our own code (likely 150–250 lines plus tests).
- **Recommendation:** keep `leaflet.markercluster` for now. It is the stable, de-facto standard Leaflet plugin, it is small, and it is MIT-licensed. Record a trigger to replace it with `supercluster` plus own glue when Leaflet is upgraded to 2.x or a markercluster bug blocks us. Pinning `~1.5.3` instead of `^1.5.3` is optional (no 1.6 exists). The owner decides this (worker's question 4).

### Deviations assessment

- **`web/package.json` / `package-lock.json` outside the Files scope:** justified. The brief requires a bundled npm package with no CDN. The lockfile diff is minimal: only the two new packages, nothing else bumped. Accepted.
- **`site` as a deprecated alias mapped to `track` instead of an error:** the brief allows either option. This one is documented in the model docstring, `docs/sensors.md` and the hand-off, and raised as owner question 3. The mapping to `track` is a guess about meaning, but every real `site` value was `null`, so it has no practical effect. Accepted.
- **Group "select all" acts on the visible sensors during a search:** reasonable and documented. See finding 7 about labelling it.
- **Screenshots taken with a scratch script instead of `screenshot.mjs`:** acceptable. The script is listed under out of scope.
- **The projection goes through the models and a store without the area check:** sound. The output is canonical and validated, and the redactor is now applied too (the old copy writer ignored it).

### Out of scope (for the owner / later WPs)

- **Off-site log notes are published.** `src/sivin/registry/offsite/model.py:201-203` writes `"<reason>: <note>"` into the `detail` of the site's `off_site` events. The 2026-10-05 decision names only the registry's `notes`/`note`. Please decide whether off-site notes are internal too. Not part of this WP (`offsite/` is excluded from its scope).
- **Duplicate ids in the hash are kept.** `#s=90000201,90000201` gives two identical chips and "Čidla (2/20)". This comes from `HashStateCodec`, which predates this WP. It should de-duplicate.
- **Stale docstring:** `src/sivin/app/site.py:103` still says the registry is "copied to `sensors.geojson`" (the worker already listed `docs/cli.md:249`).

### Follow-up after review round 1 (worker)

Requested by the orchestrator before push; the scope was extended to `src/sivin/registry/offsite/**`,
`src/sivin/app/site.py` (docstring), `web/src/state/HashStateCodec.ts` and its test.

| Item | Change | Commit |
|---|---|---|
| Phone sheet modal | `web/src/ui/picker/ModalSheet.ts` (new): open sheet = `role="dialog"`, `aria-modal="true"`, every sibling of the panel and of its ancestors up to `<body>` `inert` (pre-existing `inert` left alone), Tab/Shift+Tab wrap; undone on close. `SensorPicker` gets `isSheet()` (`main.ts`: `(max-width: 760px)`, checked on each opening). | `ba5205b` |
| Group checkbox at the limit | `toggleGroupInSelection`: a group with any selected sensor is cleared; otherwise added up to 8. `groupNotice` gives `{kind: 'full'}` (plain limit text) instead of "přidáno jen 0". | `ba5205b` |
| Search | `SensorQuery`: every query word must be the start of a word (split at non-letters/digits) of id, label, municipality, track or variety; tests for "obec b trat 4", "8271", "link". | `ba5205b` |
| Group checkbox during a search | name "Vybrat nalezená v <group>" (de/en too), state over the matches, hint "nalezeno m z n". | `ba5205b` |
| Registry whitespace, `site` errors | `src/sivin/registry/sensor_input.py` (new): `migrate_site` then `normalise_names` (label, municipality, track, variety: strip, collapse runs, warning when changed). `site` errors name `site` and the key still to add; a blank/non-string `site` is reported on `site`. | `86ebe7b` |
| Demo fixture | the four real ids have municipality/track/variety `null`; groups only on the 9xxxxxxx sensors. | `ba5205b` |
| Clustering | badge colour = mean current temperature of the members on the marker scale, grey + dashed only without any value, ink by WCAG contrast (`ClusterIcon`). `CLUSTER_RADIUS_PX` = max(marker 20, badge 34) + 8 = **42 px**: with a synthetic 200-sensor site at 1440 × 900, 28 px gave 26 badges, many overlapping (a badge is larger than a marker), 44 px 16, 60 px 8. Documented in `docs/web.md` (*Clustering*); screenshot `WP-3.5-200-sensors-map.png`. | `ba5205b` |
| Nits | limit message once (in the picker, under the button or inside the open panel; `SensorPanel.render(selected)`); retired greyed, not struck through; `HashStateCodec` de-duplicates ids; `app/site.py:103` docstring. | `ba5205b`, `86ebe7b` |
| Off-site notes | `public_reason` (`sivin.registry.offsite`) and a per-kind detail filter in `SiteEventMapping` (`PUBLIC_DETAILS`): the site's `off_site` `detail` is only the reason (unknown text → `null`). Derived events, run summary and CLI keep `"<reason>: <note>"`. The web translates the reason (cs/de/en), older free text is shown as is. Test: a marker note in the off-site log reaches no site file but stays in `data/derived/events/`. python-site and web fixtures regenerated. | `86ebe7b`, `ba5205b` |

Gates after the follow-up (worktree): `make lint` clean (293 files), `make type` no issues in 178
files, `make cov` **1887 passed**, total 99 % (`registry/sensor_input.py` 100 %,
`registry/model.py` 100 %, `site/events.py` 100 %, `registry/offsite/model.py` 100 %);
web lint/typecheck clean, **217 tests passed**, lines 99.6 %, build OK (300.6 kB JS / 97.1 kB
gzip). Browser check (Chromium, 390 px): after 40 Tabs in the open sheet focus is still inside,
10 elements `inert`, `aria-modal="true"`; Enter on a cluster zooms in; Ctrl+click on a marker
adds it. Screenshots refreshed and looked at.

Not verified: real screen readers and phones; `inert` behaviour in Safari < 15.5 (no
polyfill). The sheet mode is decided when the panel opens; rotating a phone while it is open
does not switch modes until it is reopened.

Open for the owner: the off-site rule changes the example of MIGRATION_PLAN §2.8
(`"detail": "<reason: note>"`) — the plan text should say "reason only" if the owner confirms.
