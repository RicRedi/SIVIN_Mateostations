# WP-1.8 — Off-site log

## Summary

The hand-maintained off-site log `sensors/offsite_log.yaml` (plan §2.8, owner decision of
2026-10-05) is now the source of truth for `PRE_DEPLOYMENT`. `sivin.registry.offsite` reads and
validates it: `OffSitePeriod` (frozen pydantic: sensor in any name spelling, `from`, `to | null`,
reason, note), `OffSiteLog` (immutable, checked against the `SensorRegistry`: known sensor, no
overlap per sensor, at most one open period and it is the last) and `OffSiteLogStore.load(path,
registry, timezone)`, whose errors name the entry index and field. Times are local
`YYYY-MM-DD HH:MM` (Europe/Prague, configurable) or ISO 8601 with an offset/`Z`, stored in UTC;
DST-ambiguous and nonexistent local times are rejected with a request for an explicit offset.
`OffSiteCheck` sets `PRE_DEPLOYMENT` exactly inside the logged periods (`from <= t < to`) and
emits one `off_site` event per period overlapping the series; `QualityPipeline` takes an
optional log. `DeploymentDetector` has `mode: advisory | enforce` (default `advisory`): advisory
sets no flags and only warns ("possible unlogged off-site period …") about detected indoor
periods the log does not cover. The web contract accepts `off_site` interval events and the chart
draws them as grey bands without the sensor's lines. Verified on synthetic data only.

## Changed files

- `sensors/offsite_log.yaml` (new: `entries: []`, header comment, commented-out example),
  `sensors/offsite_log.schema.json` (new, generated)
- `src/sivin/registry/offsite.py` (new), `tests/registry/test_offsite.py` (new)
- `src/sivin/quality/checks/offsite.py` (new), `src/sivin/quality/pipeline.py`,
  `src/sivin/quality/deployment.py` (advisory mode)
- `src/sivin/quality/events.py` — **outside the listed scope**, see *Deviations*
- `src/sivin/quality/__init__.py`, `src/sivin/quality/checks/__init__.py` (re-exports, §0.3/2)
- `tests/quality/test_offsite.py` (new); `tests/quality/test_deployment.py`,
  `tests/quality/test_pipeline.py` (flagging tests now run with `mode: enforce`)
- `web/src/contract/types.ts`, `web/src/contract/validateMeta.ts`, `web/src/ui/EventMarkers.ts`,
  `web/src/ui/SeriesChart.ts`, `web/scripts/generate-fixture.mjs` + regenerated
  `web/public/data/` (only the files of 77799986, `sensors.geojson` and `indices/2026.json`
  changed)
- `web/src/i18n/{cs,de,en}.ts`, `web/src/app/ChartDataLoader.ts` — **outside the listed scope**,
  see *Deviations*
- `web/tests/{app,contract}.test.ts`, `web/tests/helpers.ts`, `web/tests/ui/EventMarkers.test.ts`,
  `web/tests/ui/components.test.ts`
- `docs/sensors.md` (section *Off-site log*), `docs/quality-control.md`, `docs/web.md`
  (*Off-site periods*), `docs/wp_log/img/WP-1.8-offsite-band.png`,
  `docs/wp_log/img/WP-1.8-offsite-band-chart.png` (new; the WP-3.1 screenshots are unchanged),
  this note

### Public API

```python
# sivin.registry.offsite
OffSiteReason = Literal["office", "service", "transport", "storage", "other"]
class OffSiteLogError(ValueError)
class LocalTimeReader(timezone: str): read(value: str | datetime) -> datetime  # UTC
class OffSitePeriod(BaseModel, frozen):  # file keys sensor, from, to, reason, note
    sensor: SensorId; from_utc: datetime; to_utc: datetime | None; reason; note: str | None
    is_open, detail ("<reason>: <note>"), start_ts, end_ts, contains(t), overlaps(start, end),
    mask(t_ns) -> ndarray[bool]
    # local times: zone from validation context {"timezone": ...}, default Europe/Prague
class OffSiteLog(periods, registry: SensorRegistry):
    empty(), periods_for(sensor_id), is_off_site(sensor_id, t), mask(series) -> ndarray[bool],
    sensors(), __iter__, __len__
class OffSiteLogStore: load(path, registry, timezone="Europe/Prague"), loads(text, registry, timezone)
class OffSiteLogSettings(BaseModel, frozen): file=Path("sensors/offsite_log.yaml"), timezone
build_json_schema(), render_json_schema()

# sivin.quality.checks.offsite (not in check_registry: needs the log as collaborator)
class OffSiteCheck(QualityCheck[OffSiteSettings]): __init__(log, settings=None), check(series)

# sivin.quality.events
EventKind.OFF_SITE = "off_site", EventKind.UNLOGGED_OFF_SITE = "unlogged_off_site"
EventSource.LOG = "log"   # off_site: t_utc = from, end_utc = to (None = still off site)

# sivin.quality.deployment
class DetectorMode(StrEnum): ADVISORY, ENFORCE
DeploymentSettings.mode = ADVISORY; DeploymentSettings.log_tolerance_s = 21600
DeploymentDetector(settings=None, segmenter=None, policy=None)
    .detect(series, known_deployments=(), logged_off_site: Sequence[OffSitePeriod] = ())
class DetectionPolicy(ABC) + register_policy; AdvisoryPolicy, EnforcePolicy; LoggedCoverage
true_ranges(mask) -> tuple[(start, stop), ...]

# sivin.quality.pipeline
QualityPipeline(screening, deployed, detector, off_site_log=None)
QualityPipeline.from_settings(settings, registry=check_registry, off_site_log=None)
```

Web: `PointSensorEvent | OffSiteEvent` union, `isOffSiteEvent`, `eventInWindow` in
`web/src/contract/types.ts`; `offSiteBands`, `withoutBands`, `EventMarkers.setBands` /
`drawBands` in `web/src/ui/EventMarkers.ts`.

### Proposed wiring (WP-1.7)

- Config section `offsite_log: {file: sensors/offsite_log.yaml, timezone: Europe/Prague}`
  (`OffSiteLogSettings`), and `quality.deployment.mode` / `log_tolerance_s` in the existing
  proposed `quality` section.
- `sivin qc`: load the registry, then `OffSiteLogStore().load(...)`; an `OffSiteLogError` must
  stop the run (plan §2.8); pass the log to `QualityPipeline.from_settings(..., off_site_log=log)`.
- `sivin sensors check` should validate the off-site log too.
- WP-3.2 (`SiteBuilder`): map `QualityEvent(kind=OFF_SITE)` to
  `{type: "off_site", t, t_end, source: "log", detail}`; `end_utc is None` means **open**
  (`t_end: null`), not a point event. `unlogged_off_site` warnings belong in the run summary, not
  in the site events.

## How it was verified

Python (in `/home/user/wt/wp-1.8`, `.venv` with Python 3.12):

- `make lint type test` → ruff check: all checks passed; ruff format: 195 files already
  formatted; mypy --strict: no issues in 118 source files; pytest: **1365 passed**.
- `make cov` → 1365 passed, total 99.92 %. Changed/new modules: `registry/offsite.py` 100 %
  lines (one partial branch), `quality/checks/offsite.py` 100 %, `quality/pipeline.py` 100 %,
  `quality/events.py` 100 %, `quality/deployment.py` 99 % (the two uncovered lines, 234 and
  678, are WP-1.5 code not touched here).
- Acceptance tests: overlap, unknown sensor, `from == to` and `from > to`, open period not last
  (and two open periods), DST-ambiguous and nonexistent local time, explicit offsets and `Z`
  accepted (`tests/registry/test_offsite.py`); flags exactly inside the interval across the
  spring and the autumn change, expected rows computed by hand
  (`TestOffSiteCheck` in `tests/quality/test_offsite.py`); pipeline with log + advisory detector →
  `PRE_DEPLOYMENT` only from the log, `unlogged_off_site` warning for the unlogged service
  stay, no warning when every stay is logged (also with boundaries 2 h off, within tolerance)
  (`TestPipelineWithLog`). The committed log loads against the real registry; the commented
  example in it is also loaded in a test. The committed schema equals the generated one.

Web (in `web/`, Node 22):

- `npm run lint` OK, `npm run typecheck` OK, `npm test` → 14 files, **142 tests passed**,
  coverage lines 99.45 % / branches 90.3 % (`EventMarkers.ts` 100 % lines), `npm run build` OK.
- Tests: contract validation of `off_site` (closed, open, missing/invalid `t_end`, `t_end` on a
  point event, window membership), band clipping, `withoutBands` (values blanked independently
  of flags, break inserted in a band without samples), band drawing and labels in cs/de/en,
  loader keeps a period that starts before the window.
- Screenshots of the built preview with the regenerated fixture (taken with a temporary copy of
  `scripts/screenshot.mjs`, deleted afterwards): the band is drawn, the 77799986 lines stop at
  the band while 77678271 continues, the handle tooltip reads
  "Mimo vinici: service: synthetic example, … – 77799986 (VUT) · 4. 6. 2026 8:00 – 5. 6. 2026
  16:00".

## What did not work / what was not verified

- **No real data.** Everything is tested on synthetic series. I did **not** add an entry for
  Q10 (77799986 indoor-looking 17 Dec 2025 – 1 Mar 2026): only the owner knows whether and
  exactly when the sensor was in the building.
- The JSON Schema was not run through a JSON Schema validator (no such dependency; the
  `pattern` is only tested to match the Python regex). WP-3.3 should validate YAML → JSON against
  it.
- `log_tolerance_s` (6 h) is a project default, not tuned.
- Map tiles are blank in the screenshots (no network to OpenStreetMap in the sandbox).
- `SeriesChart.ts` stays excluded from web coverage (as in WP-3.1); the band rendering was
  checked by the screenshot and by unit tests of the functions it calls, not by a chart test.

## Deviations

- `src/sivin/quality/events.py` is not in the WP's `Files` list but had to change:
  `EventKind` and `EventSource` are closed `StrEnum`s and the `off_site` event, the advisory
  warning and the source `log` need new members (3 members + docstrings, nothing else).
- `web/src/i18n/{cs,de,en}.ts`: two keys (`eventOffSite`, `eventOngoing`) — the brief requires a
  translated label; the dictionaries are typed as complete, so the keys must be in all three.
- `web/src/app/ChartDataLoader.ts`: the event filter used `window.contains(event.t)`, which drops
  an `off_site` period that starts before the window; it now uses `eventInWindow` (3 lines).
- The band handle is styled inline (`event-marker` class + grey square) because
  `web/src/styles.css` is outside the scope.
- An `off_site` event is emitted only for periods that overlap the series; periods entirely
  outside the series produce no event (the check works on one series).
- `to` is a required key (write `to: null` for "still off site"), so an open end is never an
  accident; `note` is optional.
- In advisory mode, transitions and `deployment_mismatch` warnings are not reported (they
  describe flags this mode does not set); `unconfirmed_transition` warnings are kept unless the
  log covers their time.

## Out of scope

- `src/sivin/quality/deployment.py` is now ~700 lines; `DetectionPolicy`, `AdvisoryPolicy`,
  `EnforcePolicy` and `LoggedCoverage` could move to their own module (e.g.
  `quality/advisory.py`), which was not in the file list.
- `src/sivin/registry/schema.py` has a private `_summary` helper that `offsite.build_json_schema`
  repeats inline; a shared helper in `registry/geojson.py` or `schema.py` would remove it.
- `DeploymentResult.deployed_ranges()` is no longer used by the pipeline (it uses the combined
  `PRE_DEPLOYMENT` mask); kept for compatibility.
- `web/scripts/screenshot.mjs` hard-codes the WP-3.1 shots; a parameter for file name and hash
  would let later WPs add screenshots without a temporary copy.
- `web/src/styles.css`: a proper `.event-marker--off-site` style (instead of inline style).
- Without a log entry, an office stay's boundaries are now flagged `STEP` by the deployed
  checks (informative, not excluded), because the whole series is one stretch. Expected with the
  advisory detector; mentioned in `docs/quality-control.md`.

## Open questions for the owner

1. **Q10:** was 77799986 in the building from 17 Dec 2025 to 1 Mar 2026? If yes, add the entry
   (the commented example in `sensors/offsite_log.yaml` uses these dates as a template, with a
   guessed end 15 Mar 2026 from plan §2.8 — please correct).
2. The `detail` of the site event is `"<reason>: <note>"` with the reason in English (plan
   §2.8); the web shows it as is, untranslated. Translate the reason on the web (needs a contract
   statement that `detail` starts with the reason), or keep it?
3. Should the site (WP-3.2) list *all* logged periods of a sensor, also those outside its data?
   This check only reports periods overlapping the series.

## Review

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
