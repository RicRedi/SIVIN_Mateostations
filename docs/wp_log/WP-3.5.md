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
Verdict: _pending_
| Severity | File:line | Finding | Status |
|---|---|---|---|
