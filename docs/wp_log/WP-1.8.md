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

- **No real data** in the QC tests (synthetic series). (Round 1 did not add a Q10 entry; round 2 added it after the owner's decision, see *Round 2 changes*.)
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

1. ~~Q10~~ answered (round 2): entry added as decided by the owner.
2. The `detail` of the site event is `"<reason>: <note>"` with the reason in English (plan
   §2.8); the web shows it as is, untranslated. Translate the reason on the web (needs a contract
   statement that `detail` starts with the reason), or keep it?
3. Should the site (WP-3.2) list *all* logged periods of a sensor, also those outside its data?
   This check only reports periods overlapping the series.

## Round 2 changes

- Merged `origin/wp/0.2-owner-decisions` and `origin/claude/funny-sagan-jge9is` (plan v2.1)
  into the branch before the gates; no conflicts (`docs/web.md` merged automatically, both
  sections kept: WP-0.2's display mask 311 and *Off-site periods*). The fixture regenerates
  byte for byte after the merge.
- **Q10 (owner decision):** first real entry in `sensors/offsite_log.yaml`: 77799986,
  `2025-07-30 10:00` – `2026-03-01 22:30` local, `service`, note as decided. It loads against
  the real registry; tests check its UTC bounds and that the first (10:22) and last (22:27)
  sample of the real export are inside it.
- `sivin.registry.offsite`: `StrictLogLoader` (duplicate keys, blank values as `BlankValue`,
  unquoted serial kept as text, line numbers via `LocatedMapping`); `_EntryReader` validates entry
  by entry and turns pydantic errors into messages with a fix; `OffSiteLog(..., timezone=,
  labels=)` for cross-entry messages; `format_local`, `format_local_iso`,
  `unknown_sensor_message`; `to: open`. Schema regenerated (`to` accepts `open`).
- `DeploymentSettings.display_timezone` (default Europe/Prague) for the advisory warning text.
- Web: `parseEventsFile(value, file, warn = console.warn)` ignores `t_end` on point events;
  stacked band handles.
- Docs: `docs/sensors.md` (*Off-site log*: `open`, strict reading, Q10 entry, new message table),
  `docs/quality-control.md` (warning format, `display_timezone`), `docs/web.md` (tolerant `t_end`,
  stacked handles).
- Gates after round 2: `make lint type test` → ruff clean, mypy --strict clean (118 files),
  **1424 passed**; `make cov` → `registry/offsite.py` 99 % (1 line: a defensive message branch
  for mappings without line numbers),
  `quality/checks/offsite.py` 100 %, `quality/pipeline.py` 100 %, `quality/deployment.py` 99 %
  (WP-1.5 lines only). Web: lint, typecheck OK, **145 tests passed** (lines 99.46 %), build OK.
- Q10 answered; open questions 2 and 3 above remain.
- **Package split (scope extended by the orchestrator):** the ~1050-line `registry/offsite.py`
  became the package `src/sivin/registry/offsite/` — `model.py` (OffSitePeriod, OffSiteLog,
  OffSiteLogFile, 460 lines), `local_time.py` (LocalTimeReader, `format_local*`, 193),
  `strict_yaml.py` (StrictLogLoader, BlankValue, LocatedMapping, 94), `store.py`
  (OffSiteLogStore and the per-entry error formatting, 230), `messages.py` (OffSiteLogError,
  file keys, example lines, hints, 69), `settings.py` (OffSiteLogSettings, 39), `schema.py` (52).
  `__init__.py` re-exports the public API, so every import stays `sivin.registry.offsite`. Pure
  move: no behaviour change; helpers used across modules lost their leading underscore
  (`offset_text`, `timezone_of`, `report`, `JSON_TIME_PATTERN`) but are not re-exported. Tests
  unchanged (still one file, all imports via the package); the generated schema is identical.
  Gates after the split: ruff clean, mypy --strict clean (125 files), **1424 passed**; package
  coverage 99 % (one defensive line in `store.py`).

## Review

Verdict: CHANGES_REQUESTED  (round 1)

Reviewer: independent Claude reviewer, 2026-10-05. Diff reviewed: `11f71ef...5500bec`.

### Gates observed (run by the reviewer in `/home/user/wt/wp-1.8`)

- `make lint type test` → ruff check and format clean, mypy --strict clean, **1365 passed** (exit 0).
- `make cov` → 1365 passed, total 99 %; `registry/offsite.py` 99 % (1 partial branch),
  `quality/checks/offsite.py` 100 %, `quality/pipeline.py` 100 %, `quality/events.py` 100 %,
  `quality/deployment.py` 99 % (lines 234, 678, WP-1.5 code).
- `cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build` → all green,
  14 files / **142 tests passed**, build OK.
- `npm run fixture` reproduces the committed `web/public/data/` byte for byte (deterministic).

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `sensors/offsite_log.yaml:24-38`, `src/sivin/registry/offsite.py:635` | Following the header instruction ("remove the leading `# `") produces a file with two top-level `entries:` keys; `yaml.safe_load` keeps the last one (`entries: []`) and the log loads **silently empty**. Duplicate keys inside an entry are also silently resolved (last wins). The example also contains an open `service` period for 77678271 that would exclude all its data if uncommented as is. | fixed in round 2: `StrictLogLoader` rejects duplicate keys at any level (key and both lines named); example now commented list items under the one real `entries:`, closed period in the year 2000; tests `TestStrictYaml`, `test_uncommenting_the_example_is_harmless`, `test_uncommenting_every_comment_line_fails_loudly` |
| minor | `src/sivin/registry/offsite.py:281-286`, `docs/sensors.md` (*Format* table) | `to:` with no value (YAML null) is accepted as an open period, the same as `to: null`. The docs say "the key must be written even then, so an open end is never an accident", but a half-filled entry (`to:` left blank to fill in later) silently excludes every sample from `from` onwards. | fixed in round 2: blank `to:` (empty plain scalar, detected by the loader as `BlankValue`) is an error with a hint; `to: open` (recommended) and `to: null` mean open; docs and YAML header recommend `open` |
| minor | `src/sivin/registry/offsite.py:199-205, 685-688` | Several messages name entry and field but do not say how to fix it: an unquoted serial (`sensor: 77799986`, YAML int) → "expected a sensor name as text, got int" (the int could simply be accepted, or the message could say "put the serial in quotes"); missing key → bare pydantic "Field required" (for `to` it should say "write `to: null` if the sensor is still off site"); a typo key → "Extra inputs are not permitted" without the list of allowed keys; unknown sensor → "is not in the registry." without "check the serial or add the sensor to sensors/sensors.geojson". Most of these are explained in the `docs/sensors.md` table, but the brief requires the message itself to say it. | fixed in round 2: unquoted serial accepted as written (loader keeps the digits, so no octal surprise); missing key → example line; unknown key → list of allowed keys; unknown sensor → known serials + fix; type errors → "put the text in quotes" |
| minor | `src/sivin/registry/offsite.py:294-298, 529-541` | `from >= to`, overlap and open-period messages print the times in UTC (`2025-12-17T11:00:00Z`) while the owner wrote local time (`2025-12-17 12:00`); with two overlapping entries the owner has to convert back to find them. Print the times in the log's zone (or the original text) as well. | fixed in round 2: all owner-facing times local with UTC in brackets (`format_local`) |
| minor | `web/src/contract/validateMeta.ts:104-106` | `t_end` on a point event is a hard contract error that drops the **whole** events file of the sensor. A SiteBuilder that serialises `QualityEvent.end_utc` uniformly (`t_end: null` on every event) would lose all markers. The owner approved tolerant reading of optional contract fields (§0.5); accept `t_end: null` (or ignore `t_end`) on point events, or state the strict rule explicitly for WP-3.2. The brief asked for "only allowed for off_site", so this is a contract-level choice for the owner. | fixed in round 2 (orchestrator decision: tolerant): `t_end` on a point event is ignored with a `console.warn`; documented in `docs/web.md` |
| minor | `src/sivin/quality/deployment.py:495` | The advisory warning gives the period in UTC (`2026-04-13 23:.. UTC`), but the log is written in local time; the owner must convert before adding the entry. Give local time (or a ready-to-paste entry with offset). | fixed in round 2: warning in local time (`display_timezone`, default Europe/Prague) with UTC in brackets and ready-to-paste `from`/`to` with offset |
| nit | `src/sivin/registry/offsite.py:532, 538` vs `:688` | Two index formats in one error report: `entries.0.from` (pydantic) and `entries[0].from` (cross-entry rules), both 0-based. Documented in `docs/sensors.md`, but one 1-based form ("entry 1 (entries[0])") would be friendlier for a non-programmer. | fixed in round 2: one format `entry #N` (1-based) plus line number everywhere |
| nit | `src/sivin/registry/offsite.py:170-179` | For a nonexistent local time (spring forward) the message suggests both `+02:00` and `+01:00`; both are valid instants (01:30 CET / 03:30 CEST), which is confusing. The docs advise "use 03:00"; the message could say the same. | fixed in round 2: only the pre-change offset (`+01:00`) is suggested, plus "write a time after the change" |
| nit | `web/src/ui/EventMarkers.ts:166-173` | Bands of several sensors with the same period put their handles on the same x position (one hides the other visually; both stay focusable). All bands have the same grey, so which sensor a band belongs to is only in the tooltip. Acceptable for now. | fixed in round 2: handles of bands at the same place are stacked downwards (test) |

Details of the major finding (reproduced with a throw-away script outside the repo):

- Input: the committed `sensors/offsite_log.yaml` with the example lines uncommented as instructed.
  Result: `OffSiteLogStore().loads(...)` returns `OffSiteLog(periods=0)`, no error, no warning.
- Input: `entries:` with one entry followed by `entries: []` → 0 periods. An entry with two
  `from:` keys → the second one is used silently.
- Suggested fix: load with a `yaml.SafeLoader` subclass that raises on duplicate mapping keys
  (message: "key 'entries' appears twice (line N); keep one list"), test it; and restructure the
  commented example so uncommenting cannot duplicate the key (e.g. `entries: []` replaced by
  `entries:` with the example items commented *under* it, plus a line telling to delete `[]`).
  Use a closed period in the example or mark the open one clearly as "example only".

Verified correct (independent scripts, synthetic data):

- Time parsing: CRLF, UTF-8 BOM, seconds and fractions, `T` or space, `+01:00` / `Z`,
  unquoted YAML datetimes with and without offset, date-only (clear error), Czech
  `17.12.2025 12:00`, `2025/12/17`, single-digit hour, month 13, 30 Feb, `24:00` (all rejected with
  an example of the right format); ambiguous (`2025-10-26 02:00`/`02:30`, also in `to`) and
  nonexistent (`2026-03-29 02:00`/`02:30`) local times rejected with the field named; `03:00` on the
  fall-back day accepted. Several errors in one entry are all reported at once.
- Sensor names: serial, portal name, GPX name `77799986 (VUT)` and a unique legacy short name
  resolve via `SensorRegistry`; unknown and unparsable names rejected.
- Rules: `from == to`, `from > to`, duplicate entries, overlaps (also non-adjacent), two open
  periods, open not last → errors; touching periods accepted; empty file, comment-only file,
  `entries:` without value and a misspelt top key → one clear error pointing to `entries: []`.
- `OffSiteCheck` across the autumn change: a period `02:30+02:00 – 02:30+01:00` on 2026-10-25 flags
  exactly the two half-hour samples inside it; an open period flags to the end; a period of
  another sensor flags nothing; periods fully outside the data give no flag and no event; a
  period ending exactly at the first sample is not reported (half-open), one starting at the last
  sample flags only that sample.
- Advisory detector: never sets flags by default (pipeline test and own run on 4 seeds of
  office 3 d / vineyard 10 d / service 3 d / vineyard 10 d: `PRE_DEPLOYMENT` count 0, two
  `unlogged_off_site` warnings). Coverage with merged touching periods and `log_tolerance_s`
  checked by reading `LoggedCoverage` and its tests (partial logging → warning, logged within 6 h →
  no warning).
- Enforce mode: the only change to the WP-1.5 tests is `mode=enforce`; all their assertions are
  unchanged and pass, so the WP-1.5 flagging behaviour is preserved. The pipeline now cuts the
  deployed stretches from the combined `PRE_DEPLOYMENT` mask (log + detector), which equals the
  old behaviour when there is no log.
- New `STEP` flags without a log entry: on the 4 seeds above exactly 3 `STEP` rows (the three
  regime boundaries) and no `SPIKE`/`STUCK` inside the office stays; `STEP` is informative (not
  excluded). Expected consequence of the owner decision, documented in `docs/quality-control.md`.
- Web: `off_site` contract validation (closed/open/missing/invalid `t_end`, `t_end <= t`),
  `eventInWindow` overlap semantics, band clipping and open periods, `withoutBands` (explicit
  `null` only for the sensor of the band, other sensors get `undefined` in `alignSeries` and keep
  `spanGaps: false` semantics, i.e. their lines continue). XSS: `detail` reaches the DOM only
  through `setAttribute('aria-label' | 'data-tip')` and CSS `attr()`; no `innerHTML` anywhere in
  `web/src` → not injectable. Handles are `<button>`s with an accessible name and focus tooltip.
- Docs: an owner can add an office, service and still-off-site entry from `docs/sensors.md`
  alone; the validation table matches the real messages. Missing there: the duplicate-key trap
  above and the `to:`-blank behaviour.

### Deviations assessment

- `src/sivin/quality/events.py` (3 enum members): necessary, the enums are closed; minimal and
  does not collide with WP-0.2's scope. Accept.
- `web/src/i18n/{cs,de,en}.ts` (2 keys): necessary for the translated label. Accept.
- `web/src/app/ChartDataLoader.ts` (filter via `eventInWindow`): necessary, otherwise a period
  that starts before the window would be dropped. Accept.
- Inline style of the band handle: acceptable because `styles.css` is out of scope; the proposed
  `.event-marker--off-site` class in *Out of scope* is the right follow-up.
- `to` required, `note` optional, events only for periods overlapping the series, advisory mode
  hiding transitions/`deployment_mismatch`: reasonable and documented. Note that "`to` required"
  does not prevent an accidental open end (minor finding above).
- `docs/web.md` is also in WP-0.2's Files scope; expect a (textual) merge conflict there.

### Round 2

Verdict: APPROVE  (round 2)

Reviewer: independent Claude reviewer, 2026-10-05. Reviewed `2c3ea4a..673ef36`: the fix commit
`9738111`, the merges of `origin/wp/0.2-owner-decisions` (`a9819ce`) and plan v2.1 (`b46a7b1`),
and the package split `673ef36`.

**Gates (run by the reviewer in `/home/user/wt/wp-1.8`):**
- `make lint type test`: ruff, format and mypy --strict are clean; **1424 passed** (exit 0).
- `make cov`: total 99 %.
  - `registry/offsite/*`: 99–100 % (`local_time.py` one partial branch, `store.py` line 211).
  - `quality/checks/offsite.py` 100 %, `quality/pipeline.py` 100 %, `quality/deployment.py` 99 %.
- `cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build`: green,
  14 files / **145 tests passed**, build OK.

**Round-1 findings, re-checked with the round-1 probe scripts plus new ones (`/tmp/claude-0/review-1.8/exp1-5.py`):**

| Severity (round 1) | Finding | Round 2 |
|---|---|---|
| major | Duplicate `entries:` / duplicate key in an entry read silently; the example could not be uncommented safely | **resolved.** `StrictLogLoader` rejects any duplicate key and names the key and both lines (`line 6: the key 'entries' appears a second time (first on line 1) … put all entries as '- sensor: ...' items under one 'entries:'`). The example is now a commented list item under the single `entries:` key. Uncommenting its five lines as instructed gives a valid log with the extra period in the year 2000, so it touches no data. |
| minor | Blank `to:` read as an open period | **resolved.** A blank value gives `entry #1, 'to' (line 4): is empty - write a date/time, or 'open' if the sensor is still off site`. The same holds for every key, and for `""`. |
| minor | Messages without a fix | **resolved.** Each message names the key that is missing (with an example line), the key that is unknown (with the allowed keys) or the sensor that is unknown (with the known serials). It also covers the wrong type (put the text in quotes), the tab indent and an entry that is not a mapping. An unquoted serial is accepted. |
| minor | Cross-entry messages in UTC | **resolved.** Times are now local with the zone abbreviation and UTC in brackets, e.g. `2025-12-17 12:00 CET (11:00 UTC)`. |
| minor | Strict `t_end` on point events | **resolved.** The value is ignored with a contract warning, which goes to `console.warn` by default. |
| minor | Advisory warning in UTC | **resolved.** Times are local, and the warning includes ready-to-paste `from:`/`to:` values with an offset. These stay unambiguous in the repeated October hour (checked: `2026-10-25T02:30+02:00` / `+01:00`). |
| nit | Two index formats | **resolved.** One format: `entry #N` (1-based) with the line number. |
| nit | Spring-forward suggestion | **resolved.** The message now says to write a time after the change, or the clock time before it with its offset. |
| nit | Coincident band handles | **resolved.** Handles closer than one handle width are stacked downwards. |

**Refactor `673ef36` (one module split into the package `registry/offsite/`):**
- It touches only `src/sivin/registry/offsite*`, `docs/quality-control.md` and this note. No test changed, and all pass.
- I ran every probe script against `9738111` (old module, via a temporary worktree) and against `HEAD`. The output is byte-identical (`exp1`, `exp2`).
- The public names of `sivin.registry.offsite` are unchanged. Only imported helpers and private names are no longer reachable from the package root.
- The behaviour is unchanged.

**Merge with WP-0.2:**
- `origin/wp/0.2-owner-decisions` (`20ef2a5`) and the plan branch are ancestors of `HEAD`.
- The following are identical to WP-0.2: `src/sivin/core`, `src/sivin/config.py`, `config/`, `src/sivin/ingest`, `src/sivin/quality/checks/missing.py`, `web/src/domain`, and the core, ingest and fixture tests.
- On the web, `DISPLAY_EXCLUDE_MASK = DEFAULT_EXCLUDE_MASK = 311`, asserted in `web/tests/Resampler.test.ts`.
- The row rule (`MISSING` when either variable is missing) is preserved.
- `docs/web.md` contains both the WP-0.2 mask text and the *Off-site periods* section. No conflict markers are left in the tree.

**Q10 entry (owner decision §0.5, v2.1):**
- The entry is `77799986`, `2025-07-30 10:00` – `2026-03-01 22:30` local, reason `service`.
- The first sample of the real export fixture (`2025-07-30 10:22:29`) and its last sample (`2026-03-01 22:27:05`) both lie inside the period, so the whole export is flagged.
- The committed log loads against the real registry, and also with CRLF line endings.

**New findings:**

| Severity | File:line | Finding | Status |
|---|---|---|---|
| nit | `src/sivin/registry/offsite/strict_yaml.py` (`construct_mapping`) | A non-scalar YAML key (`? [a]`) raises a bare `TypeError: unhashable type: 'list'` instead of `OffSiteLogError`. An owner is very unlikely to write this; catch `TypeError` there, or keep it. | open |
| nit | `sensors/offsite_log.yaml`, `docs/sensors.md` vs plan §2.8 | The file and docs teach `to: open` (case-insensitive). The plan's `to: null` is still accepted, so this is a compatible superset. The §2.8 text only mentions `null`; the owner may want the plan updated to name `open`. | open |
| nit | `web/src/ui/EventMarkers.ts` (`HANDLE_SIZE_PX`, `HANDLE_TOP_PX`) | The values duplicate `.event-marker` sizes in `styles.css`, which is out of scope. This is already covered by the *Out of scope* note about a proper `.event-marker--off-site` style. | open |

**Other notes:**
- The worker filled the Status column of the round-1 table. This is acceptable: the findings themselves were not edited.
- No blockers or majors remain.
