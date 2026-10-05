# WP-3.2 — SiteBuilder: static site data for the web

## Summary

`sivin build-site [--out DIR] [--season YEAR …] [--full]` generates `site/data` exactly per
MIGRATION_PLAN §2.6 (`schema_version: 1`) with the §2.8 `off_site` intervals and the WP-1.9
optional fields, and `sivin run` builds the site as its last step (`--skip-site` to disable;
never in a dry run). Every published sensor is read through `QualityService.checked` (QC with
the off-site log and the precipitation set-aside) and the indices come from a dry-run
`IndicesService`. The new package `sivin.site` has one writer class per file kind behind two
ABCs (per-sensor and site-wide), pure column builders, a QC-event mapping and an incremental
build state: sensors whose store files and outputs are unchanged are reused without being
read; a test shows incremental and full builds are byte-identical. The web contract now skips
unknown event types with a warning, shows `low_battery` and `unlogged_off_site` as amber
markers, and accepts the new optional fields. A cross-language test runs
`sivin run --skip-fetch` on the real export of 77799986 plus a synthetic sensor, commits the
output as `web/tests/fixtures/python-site/`, and validates every file with the web's
validators and `DataClient`.

## Changed files

Commits on `wp/3.2-site-builder` (base `bb4290b`, head of `wp/1.7-integration`):

| Commit | Content |
|---|---|
| `d127a53` | `src/sivin/site/` (new: `settings`, `columns`, `files`, `labels`, `events`, `model`, `indices`, `sensor_files`, `site_files`, `sensor_builder`, `state`, `builder`, `__init__`); `tests/site/{helpers,test_columns,test_files,test_labels_events,test_sensor_files,test_site_files,test_builder}.py` |
| `ed6dd41` | `src/sivin/config/model.py` (`site` section), `config/sivin.yaml`, generated reference in `docs/configuration.md`, `tests/config/test_schema.py` (section lists) |
| `8b0341b` | `src/sivin/app/site.py` (new), `app/factory.py` (`site_service`, `run_service(skip_site)`), `app/run.py` (site step, `RunReport.site`/`site_failures`), `app/workspace.py` (`site_data_dir`), `src/sivin/cli/commands/site.py` (new), `cli/main.py` (registration), `cli/commands/pipeline.py` (`run --skip-site`); `tests/site/{test_service,python_site}.py`, `tests/e2e/test_site.py`; `web/tests/fixtures/python-site/**` |
| `ace27d8` | `web/src/contract/{types,validateMeta,validateSeries}.ts`, `web/src/ui/EventMarkers.ts`, `web/src/i18n/{cs,de,en}.ts`; `web/tests/{contract.site,pythonSite}.test.ts` (new), `web/tests/{app,contract}.test.ts`, `web/tests/ui/EventMarkers.test.ts` |
| `83020a1` | `docs/site.md` (new), `docs/web.md`, `docs/cli.md`, `docs/configuration.md` (sections table) |
| this commit | `docs/wp_log/WP-3.2.md` |

### Public API

```python
# sivin.site
SiteSettings(stale_after_s=129600.0, events=(off_site, deployment, retrieval, step,
             low_battery, unlogged_off_site))                      # config section `site`
SiteBuilder(source: CheckedSource, indices: IndexSource, sensors: SensorSiteBuilder,
            site_writers, fingerprints: StoreFingerprints, clock, error_text=str)
    .build(output: SiteOutput, inputs: SiteInputs, seasons=None, full=False, checked=None)
    -> SiteReport(out_dir, generated_at, full, seasons, built, reused, written, removed, failures)
SiteInputs(sensors: {SensorId: status}, registry: bytes, settings: str, display_timezone)
CheckedSource (Protocol: checked(sensor_id) -> QualityResult)
IndexSource (Protocol: specs() -> tuple[IndexSpec], compute(season, checked) -> IndexBatch)
SensorSiteBuilder(DailyAggregation, SummaryBuilder, writers).build(sensor_id, result)
SensorFileWriter (ABC): RawMonthsWriter, DailyWriter, SiteEventsWriter; default_sensor_writers()
SiteFileWriter (ABC): ManifestWriter, RegistryCopyWriter, LatestWriter, SeasonIndicesWriter;
    default_site_writers()
SiteEventMapping(published).entries(events); POINT_KINDS
SiteFile(path, content), SiteOutput(root).write/has/read/prune, encode_json()
BuildState / SensorState / StoreFingerprints / StateFile / fingerprint();
    STATE_FILE = "site-build-state.json" (in paths.derived_dir; round 2)
IndexCatalog, INDEX_LABELS, VARIABLES, Label, IndexSpec; index_entry(IndexResult)
columns: unix_seconds, rounded, utc_month_keys, local_years, iso_utc_seconds, VALUE_DECIMALS=2,
    SHARE_DECIMALS=3, INDEX_DECIMALS=2, CONFIDENCE_DECIMALS=2

# sivin.app
ServiceFactory.site_service() -> SiteService(builder, SiteInputsLoader, default_out)
    .build(out=None, seasons=None, full=False, checked=None) -> SiteReport
ServiceFactory.run_service(dry_run, skip_fetch, headed, skip_site=False)
RunService(..., site: SiteService | None = None); RunReport.site, RunReport.site_failures
SiteIndices(IndicesService, IndexRegistry); SITE_OUTPUT_FORMAT = 1
Workspace.site_data_dir  # <paths.site_dir>/data
```

CLI: `sivin build-site`, `sivin run --skip-site` ([docs/cli.md](../cli.md)); output format and
decisions: [docs/site.md](../site.md).

## How it was verified

All commands in `/home/user/wt/wp-3.2` (venv by `uv`, Python 3.12; Node 22).

- `make lint` → `All checks passed!`, `288 files already formatted`.
- `make type` → `Success: no issues found in 176 source files`.
- `make test` / `make cov` → **1837 passed**; total coverage 99 % (threshold 85 %). New code:
  every module of `sivin/site/*` **100 %**, `sivin/app/site.py` 100 %, `app/workspace.py`
  100 %, `app/factory.py` 99 % (line 137, pre-existing), `app/run.py` 99 % (line 55,
  pre-existing), `cli/commands/site.py` 100 %, `cli/commands/pipeline.py` 99 % (exempt).
- Web (`cd web`): `npm run lint` → clean; `npm run typecheck` → clean; `npm test` → **165
  passed**, lines 99.38 % (threshold 85 %); `npm run build` → built.
- Acceptance:
  - `sivin run --skip-fetch` on the e2e fixtures (real export of 77799986, off-site log,
    synthetic 77678271) produces the committed `web/tests/fixtures/python-site/`
    (`tests/e2e/test_site.py::test_run_skip_fetch_matches_the_web_fixture`), and
    `web/tests/pythonSite.test.ts` reads every file there through the validators (no
    `ContractError`, **no warning**) and the `DataClient` (raw ranges match `first_t`/`last_t`,
    all real samples `PRE_DEPLOYMENT`, the `off_site` period 2025-07-30T08:00Z –
    2026-03-01T21:30Z, Huglin entry with `estimated`).
  - Incremental vs full: build, append a second synthetic export, incremental build (1 sensor
    built, 1 reused) and full build into another directory → identical trees, build state
    included (`tests/site/test_service.py::test_incremental_and_full_builds_are_byte_identical`).
- Hand-computed unit expectations: Unix times (2026-01-01 = (56·365+14)·86 400 s), UTC month
  split vs local time, daily aggregates of a 3-row synthetic series (mean (1.234+2)/2 → 1.62,
  coverage 2·1830/86 400 → 0.042), staleness exactly at 36 h, event shapes.
- Smoke run on the real export: `low_battery` event of 77799986 at the start of the export
  (2 readings below 3.3 V, lowest 3 V) is published and parsed by the web.

## What did not work / what was not verified

- The site was never built from real **vineyard** data: the only real export (77799986) is off
  site for its whole span, so it has no valid latest sample and no index value; the second
  sensor is synthetic. Index values in the fixture come from synthetic data.
- The portal UI was not checked in a browser with the generated data (no screenshot); only the
  validators, `DataClient`, `EventMarkers` (jsdom) and the unit tests ran.
- Performance on a large store was not measured (a reused sensor costs reading its store files
  for the fingerprint and its outputs for the SHA-256).
- CI did not run (nothing pushed).

## Deviations

1. **Files outside the literal Files scope**, required by task 3 of the brief ("a marker style
   + i18n label"): `web/src/ui/EventMarkers.ts` (labels and amber style for the two new
   marker types; without it the new contract types would reach `EVENT_LABELS` with no entry)
   and `web/src/i18n/{cs,de,en}.ts` (two keys each). `tests/config/test_schema.py` lists the
   configuration sections and had to learn `site`.
2. **Web behaviour change**: an event of an unknown `type` is now skipped with a warning
   instead of failing the whole events file (requested by the brief). Two existing web tests
   that used an unknown type as the example of an invalid file were changed to a non-numeric
   `t`; the warning text for `t_end` on point events now says "only interval events have an
   end" (marked intervals also have one).
3. **Contract additions** (all optional in the web, tolerated when absent or malformed):
   manifest sensor `status`, daily `precip_n_samples`, index `estimated`, two event types
   `low_battery` and `unlogged_off_site` with an integer `t_end ≥ t`, and two more manifest
   `variables` (`precip_mm`, `battery_v`). Listed for the owner below.
4. **Seasons**: the output holds exactly the selected seasons (default: every calendar year
   with data); `sivin run` uses the default, not its `--season`.
5. **`computed_at`** of `indices/<season>.json` is the `generated_at` of the build that wrote
   the file (needed for byte-identical incremental builds), not the time the cached entry was
   computed.
6. **Store fingerprint** reads the files of `<data_dir>/raw/<id>/` directly (the store has no
   public listing of its partition files; `_partition_files` is private and storage is out of
   scope).
7. **`RunService`** got an optional `site` argument at the end and `RunReport` two fields with
   defaults, so the existing `tests/app` (out of scope) run unchanged.

## Out of scope

- `docs/architecture.md`: "the site export (8) is WP-3.2" and the flow diagram should now point
  to `sivin build-site` / `docs/site.md`; `README.md` quick start could add `sivin build-site`.
- `src/sivin/storage/store.py`: a public `partition_files(sensor_id)` (or a fingerprint method)
  would let the site builder stop reading `raw/<id>/` itself.
- Web (WP-3.4): grey out retired sensors (manifest `status`), draw `unlogged_off_site` as a
  band, show precipitation/battery and the index cards; `web/scripts/generate-fixture.mjs`
  still uses a 1825 s step (only the doc wording was changed here).
- WP-4.1: keep `site/data` and `data/derived/site-build-state.json` between scheduled runs
  (e.g. on the `data` branch), or every run is a full build; report the `unlogged_off_site`
  warnings (no longer public by default) in the job summary.
- **WP-2.3 (disease models)**: `powdery_mildew_gt` and `botrytis_broome` return a value of 0.0
  and the class `"low"` (powdery mildew) when there are no data at all (coverage 0, e.g. a sensor
  off site for the whole season). The site now publishes `null`/`no_data` for them at the
  publication boundary, but the models themselves should return `value=None` and no class at
  zero coverage (also for `data/derived/indices/` and every other consumer).
- The root `.gitignore` already ignores `/site/` (generated output) and every `data/`
  directory; the fixture `web/tests/fixtures/python-site/` is not affected.

## Open questions for the owner

1. Contract §2.6 additions (all optional, see *Deviations* 3): accept them into the plan text
   (`status` in the manifest, `precip_n_samples`, `estimated`, `low_battery` and
   `unlogged_off_site` events, the two extra variables)?
2. ~~Should `unlogged_off_site` be public?~~ Decided in round 2 (orchestrator): not by default;
   it stays an opt-in in `site.events`, and WP-4.1 reports it in the job summary.
3. Staleness 36 h (`site.stale_after_s`) — fine with the daily 06:00 run?
4. A stored sensor that is not in the registry is not published (no position); is that right,
   or should it appear in the manifest without a map marker?
5. `sensors.geojson` is a byte copy of the registry (§2.6 "kopie registru"). It publishes
   `portal_name` (with the provider account number 8615620) and internal placement notes such as
   "placeholder deployment date — owner to confirm (MIGRATION_PLAN Q3)". Publish as is (current
   behaviour, kept in round 2), or publish only the public properties? (Raised by the
   orchestrator.)
6. Round 2: a sensor whose build failed is marked in the manifest with **`data_status: "error"`**
   and `last_built_at`, not with `status: "error"` as the orchestrator suggested: `status` is the
   registry life-cycle state, and overwriting it would hide that a sensor is retired. Rename if
   you prefer.

## Round 2 (changes after review round 1)

Orchestrator decisions on review round 1, all implemented (see the Status column):

- **Major, no-data index entries:** `index_entry` publishes `value: null`, `class: null`,
  `status: "no_data"`, `detail: "no data"` when `coverage` is 0, and a `class` only for a
  `complete` result (no index declares its own rule for partial classes, so none is published
  partially). Every entry now has `status` (`ok`/`no_data`). Tests: `tests/site/test_indices.py`
  and `tests/site/test_service.py::test_no_index_value_or_class_without_data` (77678271 off site
  for the whole 2026 season: powdery mildew, Broome, Huglin and Winkler all `null`/`no_data`);
  the web fixture test checks every entry of 77799986. WP-2.3 follow-up under *Out of scope*.
- **Failed sensor survives a full build:** the stored state is always read; a failing sensor
  takes its last state (also when the shared inputs changed or `--full` is given), keeps its
  files and stays in the manifest with `data_status: "error"` and `last_built_at` (open question
  6). Test with the reviewer's reproduction: `test_failed_sensor_survives_a_full_build`
  (broken store, then changed settings, then `--full`: nothing removed, files byte-identical).
- **Failures are retried:** `SensorState` has `retry` (a failed index or sensor) and `failed`; a
  state with `retry` is never reused, so every build retries and exits 1 while it keeps failing.
  `IndexBatch.failed_sensors` carries the sensors with failed indices. Tests:
  `test_failed_index_is_retried_and_fails_every_run`, `test_failed_sensor_is_retried_until_it_succeeds`.
- **`unlogged_off_site`** removed from the default `site.events` (opt-in); `config/sivin.yaml`,
  configuration reference and docs updated; the python-site fixture did not contain one.
- **Labels:** `gdd_winkler` cs "Suma efektivních teplot (Winklerův index)", de "Gradtage nach
  Winkler"; also checked the others and changed `cool_night` de to "Index kühler Nächte" and
  `vpd` cs to "Sytostní doplněk (deficit tlaku vodní páry)" (the Czech term for VPD).
- **Build state** moved out of the published directory to
  `<paths.derived_dir>/site-build-state.json` (`StateFile`, `Workspace.site_state_file`; state
  format 2). Documented in `docs/site.md`, `docs/cli.md`, `docs/web.md`.
- **Staleness at viewing time:** the manifest publishes `stale_after_s`; the web
  (`SensorCatalog.build(..., nowS)`, `withStaleness`) marks a latest sample stale when it is
  older than that at the current time, the build-time `stale` stays. Web test in
  `tests/app.test.ts`; optional contract fields `stale_after_s`, `data_status`,
  `last_built_at`, index `status`/`detail` with tolerance tests in `tests/contract.site.test.ts`.
- **`sensors.geojson`:** unchanged byte copy; owner question 5.
- Outside the literal Files scope (requested by the orchestrator): `web/src/app/SensorCatalog.ts`
  (staleness at viewing time, `nowS` defaults to the clock, so `main.ts` is unchanged).
- The python-site fixture was regenerated (`indices/*.json`, `manifest.json` changed).

Gates after round 2 (in `/home/user/wt/wp-3.2`): `make lint` → all checks passed; `make type`
→ `Success: no issues found in 176 source files`; `make cov` → **1844 passed**, total 99 %,
every `sivin/site/*` module, `app/site.py` and `app/workspace.py` 100 %. Web: lint and
typecheck clean, `npm test` → **168 passed**, lines 99.39 %; `npm run build` OK.

## Review
Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer session, 2026-10-05. Throwaway scripts and screenshots are in
`/tmp/claude-0/review-3.2/` (outside the repository).

### Gates observed (worktree `/home/user/wt/wp-3.2`, head `c1e0fa2`)

- `make lint` → `All checks passed!`, `288 files already formatted`; `make type` → `Success: no
  issues found in 176 source files`; `make test` → **1837 passed**.
- `make cov` → 1837 passed, total 99 %; every module of `sivin/site/*` 100 %, `app/site.py`
  100 %, `cli/commands/site.py` 100 %, `app/run.py` 99 %, `cli/commands/pipeline.py` 99 %.
- Web (`npm ci && npm run lint && npm run typecheck && npm test && npm run build`) → exit 0;
  17 test files, **165 passed**, lines 99.38 %; build OK.

### What I verified beyond the worker's tests

- **Contract fidelity.** I compared every file in `web/tests/fixtures/python-site/` field by field
  with §2.6/§2.8 and the WP-1.9 fields. Required fields, key order, `null` for missing, Unix seconds
  and ISO `Z` times all match. The raw months are UTC months: the last May sample of 77678271 is
  1780271350 < 1780272000 = 2026-06-01T00:00Z, local time would put it in June. `off_site` matches
  §2.8: `source: log`, `detail` = `"<reason>: <note>"`, `t_end` set.
- **Real data through the real web.** I built a copy of `web/` with the python-site fixture as
  `public/data` (`SITE_BASE=/ VITE_DEMO_DATA=false`), served it and drove it with playwright-core
  and `/opt/pw-browsers/chromium`. Screenshots: `/tmp/claude-0/review-3.2/0*.png`.
  - 77799986 shows its grey off-site band with no line, the "no data" note and "bez hodnoty" as
    the latest value. The amber `low_battery` marker shows its interval in the label (2025-07-29 ..
    2025-08-02 window).
  - The synthetic 77678271 shows its daily cycle. 24 h / 7 d / 30 d end at the end of the data and
    switch to the correct resolution; season 2025/2026 and the custom window work.
  - The console had no contract warnings or errors. The only failures were OSM tile requests,
    because there is no network.
- **Incremental build.**
  - A change to the off-site log alone gives a full build (1 built, 0 reused), and the events,
    flags (`qc` all 32), latest and indices are updated.
  - A registry change gives a full build. A retired sensor (placement closed) gets
    `status: "retired"` in the manifest and keeps its data.
  - A stored sensor removed from the registry is left out with a warning, and its files are pruned.
  - Appending data to one sensor rebuilds only that sensor. Written: `daily.json`,
    `raw/2026-09.json`, manifest, latest, state. The result is byte-identical to a `--full` build
    at the same clock.
- **Performance.** I used 4 sensors × 3 years of SYNTHETIC 1830 s data (≈ 52 k rows each).
  - Full build 14.1 s, 163 files, 6.9 MB in total: raw month ≈ 46 KB, `daily.json` 67 KB,
    `manifest.json` 5.3 KB, `.build-state.json` 47 KB.
  - Incremental build with no change 0.1 s; with one sensor changed 3.6 s.
- **Leaks.** I searched the whole generated output for `/tmp`, `/home`, `/root`, `MeteoData`,
  `.csv`, `password` and `SIVIN_` and found nothing. Failure texts use relative paths and are not
  published.

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `src/sivin/site/indices.py:17-40` (`index_entry`), `docs/site.md` § indices | A sensor with **no valid sample in the season** still gets numeric risk values and a risk class (details below). | fixed: coverage 0 → `value`/`class` `null`, `status: "no_data"`, `detail: "no data"`; class only for complete results; tests (whole season off site); WP-2.3 note in *Out of scope* |
| minor | `src/sivin/site/builder.py:202,273` (`previous = None` drops `_previous_states`), `docs/site.md:182` | A failing sensor is unpublished by every full build, although `docs/site.md` says "Failures never remove published data" (details below). | fixed: the stored state is the fallback of a failed sensor in every build (also full); files kept, manifest `data_status: "error"` + `last_built_at`; test with the reproduction |
| minor | `src/sivin/site/builder.py:312-340` (`compute_indices` / `states`) | An index failure is cached by the incremental build (from reading the code, not reproduced; details below). | fixed: `retry` in the sensor state for a failed index or sensor; never reused, every build retries and exits 1; tests |
| minor | `src/sivin/site/settings.py:31` (`DEFAULT_PUBLISHED_EVENTS`) | `unlogged_off_site` is public by default with an operator instruction as its tooltip (details below). | fixed: not in the default `site.events` (opt-in); WP-4.1 job summary |
| minor | `src/sivin/site/labels.py:128-130` | The Czech label of `gdd_winkler` is "Sumy aktivních teplot (Winkler)", which names a different index (details below). | fixed: "Suma efektivních teplot (Winklerův index)"; also de Winkler, de cool_night, cs vpd |
| nit | `src/sivin/site/files.py` / `docs/site.md` § incremental | `.build-state.json` sits in `site/data` and would be deployed publicly (47 KB with 4 sensors). It is harmless, but WP-4.1 should exclude it from the Pages artifact or keep it outside `data/`. | fixed: state moved to `<paths.derived_dir>/site-build-state.json`, documented |
| nit | `src/sivin/site/site_files.py` (`RegistryCopyWriter`) | `sensors.geojson` is a byte copy, as the plan says. It publishes `portal_name` (with the provider account number 8615620) and internal placement notes ("placeholder deployment date — owner to confirm (MIGRATION_PLAN Q3)"). Owner decision: publish as is, or keep only the public properties. | kept (byte copy); owner question 5 |
| nit | `src/sivin/site/site_files.py` (`LatestWriter`) | `stale` is frozen at `generated_at`. If the daily job stops, the portal keeps showing `stale: false` indefinitely. The web could also compare `generated_at` with the current time (WP-3.4/4.1). | fixed: manifest `stale_after_s`; the web also judges staleness at viewing time; test |

**Major: zero-coverage index entries (`indices.py:17-40`).** A sensor with no valid sample in
the season still gets risk values and a risk class.
- Input: the committed fixture, or my scenario with an off-site period covering the whole 2026
  season of 77678271.
- Wrong behaviour: `powdery_mildew_gt: {value: 0.0, class: "low", coverage: 0.0}` and
  `botrytis_broome: {value: 0.0, coverage: 0.0}` are published. On a public site this says "low
  powdery mildew risk" for a sensor that was in the office: a statement made from no data.
  `complete: false` does not undo that for any consumer of the JSON.
- Suggested fix: at the publication boundary, write `value: null` and `class: null` when
  `coverage == 0`, or leave such a sensor out of that season, and add a test. Also note for
  WP-2.3 that the disease models should return no value at zero coverage.

**Minor: failing sensor unpublished by a full build (`builder.py:202,273`).** When the shared
inputs change or `--full` is used, `_previous_states` is empty, so a sensor that fails disappears.
- Verified: build, then corrupt `data/raw/77680921/2026.csv`. The incremental build keeps the old
  files (correct). Then add one line to the off-site log: a full build with **4 files removed**,
  and 77680921 is gone from the manifest.
- Suggested fix: keep the parsed previous sensor states as a fallback for failed sensors even when
  `settings` changed, or correct the documentation.

**Minor: index failure cached (`builder.py:312-340`).** From reading the code; I did not
reproduce it.
- Wrong behaviour: when an index fails for a sensor that built fine, the sensor's state is saved
  with its current store fingerprint. The next incremental build reuses the sensor, so the failed
  index is not retried until its store changes. The failure (exit 1) is reported only once; later
  runs publish the missing entry with exit 0.
- Suggested fix: do not record the fingerprint (or force a rebuild) for a sensor that had index
  failures.

**Minor: `unlogged_off_site` public by default (`settings.py:31`).** This answers open question
2.
- What is published: an unconfirmed detector guess, whose `detail` is an operator instruction
  ("…add an entry to sensors/offsite_log.yaml with from: … and to: …"). It is shown verbatim in
  the public tooltip.
- Recommendation: leave it out of the default `site.events` and keep it in the run/job summary,
  where the owner can act on it. If the owner wants it public, publish it with a short neutral
  detail.

**Minor: wrong Czech label for `gdd_winkler` (`labels.py:128-130`).** In Czech viticulture,
*suma aktivních teplot* (SAT) is the sum of daily mean temperatures on days with mean ≥ 10 °C.
Winkler GDD is Σ(T − 10), i.e. *suma efektivních teplot*. Suggested label: "Suma efektivních
teplot (Winkler)" or "Růstové stupňodny (Winkler)".

### Contract additions (focus 1)

All the additions below are additive for this web and tolerated when absent:
- `manifest.sensors[*].status`;
- the extra manifest variables `precip_mm` and `battery_v` (the web looks variables up by id);
- `daily.precip_n_samples`;
- `indices[*][*].estimated`;
- `confidence: null` on `off_site` (it is not in the §2.8 example; harmless);
- the event types `low_battery` and `unlogged_off_site` with an integer `t_end ≥ t`.

The new event types are the only **breaking** addition, and only for a web build from before
WP-3.2: the old validator rejected the whole events file on an unknown `type`. Because web and data
are deployed together, this is tolerated, but WP-4.1 must deploy the web and the data of the same
commit. `latest.json` leaving out sensors without a valid sample is not covered by §2.6, but it is
handled by the web ("bez hodnoty"). `low_battery`/`unlogged_off_site` intervals always have an end
in QC (`IndoorInterval.end_utc` and the battery run end are never `None`), so the web's integer
`t_end` requirement holds.

### Deviations assessment

1. **Files outside the literal scope** (`web/src/ui/EventMarkers.ts`, `web/src/i18n/*`,
   `tests/config/test_schema.py`): justified, because the brief asked for a marker style and an
   i18n label. The changes are minimal.
2. **Unknown event types are skipped with a warning:** requested. The two web tests that were
   changed still test an invalid file.
3. **Contract additions:** acceptable, see above. Owner to confirm them into §2.6.
4. **Seasons = exactly the selected ones; `sivin run` uses the default:** fine and documented.
5. **`computed_at` = `generated_at`:** fine, and needed for byte-identical builds. The side effect
   is that the 4 indices files are rewritten on every run (commit churn on `data`).
6. **Fingerprint reads `<data_dir>/raw/<id>/` directly:** an acceptable workaround inside scope. It
   couples the site builder to the store layout; the proposed public `partition_files` is the right
   follow-up.
7. **`RunService(site=None)` / `RunReport` defaults:** fine.

Scope otherwise clean; no shared core/storage/CI file touched. The CLI registration and the
`config/model.py` change are within the WP's scope.

### Round 2

Verdict: APPROVE (round 2)

The review covers `135416f`. My scripts and screenshots are in `/tmp/claude-0/review-3.2/`:
`round2.py`, `idxfail.py`, `stale.cjs`, `r2-*.png`.

**Gates (all run by me):**
- `make lint`: all checks passed, 289 files formatted.
- `make type`: no issues found in 176 source files.
- `make test` and `make cov`: 1844 passed, 99 % total. Every module in `sivin/site/*` and
  `app/site.py` is at 100 %.
- `tests/e2e/test_site.py`: the fixture is up to date.
- Web (`npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`): exit 0,
  168 tests passed, 99.39 % line coverage.

**Round-1 findings:**

| Severity | Round-1 finding | Status | Evidence |
|---|---|---|---|
| major | zero-coverage index values and classes | resolved | A whole-season off-site period on 77678271 now gives no index with a non-null `value` or `class`. Entries look like `{value: null, class: null, coverage: 0.0, status: "no_data", detail: "no data"}`. Classes are now published only for `complete` results. The regenerated fixture validates in the web without warnings. |
| minor | a failing sensor was unpublished by a full build | resolved | With a corrupted store file and a changed off-site log, the full build keeps the sensor's files. The manifest then carries `data_status: "error"` and `last_built_at`. The same holds for `--full` and for incremental builds. After the store is repaired, the next build restores a normal entry. |
| minor | index failures were cached | resolved | I ran this end to end with a `HuglinIndex.compute` that raises. Builds 1 and 2 both rebuild the sensor and exit 1. After the fix, build 3 publishes `huglin` and exits 0. Build 4 reuses the sensor. |
| minor | `unlogged_off_site` was public by default | resolved | It is now opt-in, in the code default, in `config/sivin.yaml` and in `docs/site.md`. |
| minor | Czech label of `gdd_winkler` | resolved | It is now "Suma efektivních teplot (Winklerův index)". `vpd` is "Sytostní doplněk (deficit tlaku vodní páry)", which is the correct Czech term. |
| nit | build state published in `site/data` | resolved | The state is now `data/derived/site-build-state.json`, and nothing in `site/data` starts with `.` or contains "state". |
| nit | registry copy publishes `portal_name` and notes | open (owner decision) | Unchanged, as the plan specifies. |
| nit | `stale` frozen at `generated_at` | resolved | The manifest now carries `stale_after_s`, and `SensorCatalog` re-judges staleness against the current time. In a browser, a copy of the fixture with `latest.stale` set to `false` still shows "(neaktuální)" (`r2-09-client-stale.png`). |

**New finding:**

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | `src/sivin/site/builder.py` (`fallback` from `StateFile`), `src/sivin/app/workspace.py` (`site_state_file`) | The build state is one global file, but the output directory varies with `--out`. Details below. | open |

Details of the new finding:
- Reproduced: one sensor's store is corrupted, then I ran `sivin build-site --out other`. The new
  directory's manifest lists 77680921 with `raw_months` and `data_status: "error"`, but its
  `series/` files do not exist there. The web would fail on "listed month cannot be loaded".
- A build with `--out` also overwrites the state of the default `site/data`. This only costs a
  rebuild, because outputs are checked by SHA-256.
- Suggested fix: use a fallback state only if all its outputs exist in the current output
  (`output.has`), otherwise leave the sensor out. Alternatively, key the state by output
  directory.
- It is not blocking: `sivin run` and the scheduled workflow always use the default output.

**Web with real data (regenerated fixture, playwright-core and `/opt/pw-browsers/chromium`):**
- 77799986 shows its grey off-site band with no line, plus the amber low-battery marker.
- The synthetic 77678271 shows its data.
- 24 h, 7 d, 30 d, season and custom windows work.
- No contract warnings or errors appeared; only map tiles failed, because there is no network.
- Screenshots: `r2-01` … `r2-09`.

**Performance** (4 sensors × 3 years of synthetic 1830 s data, rerun):
- Full build: 14.1 s, 162 files, 6.9 MB.
- Incremental build with no change: 0.1 s. With one sensor changed: 3.8 s.
- Incremental and full builds are byte-identical.
- No leaks: no absolute paths, credentials or file names in the output.
