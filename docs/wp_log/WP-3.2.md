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
BuildState / SensorState / StoreFingerprints / fingerprint(); STATE_FILE = ".build-state.json"
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
- WP-4.1: keep `site/data` (incl. `.build-state.json`) between scheduled runs, e.g. on the
  `data` branch, or every run is a full build; decide whether `.build-state.json` should be
  deployed to Pages (harmless: fingerprints, relative paths, summaries only).
- The root `.gitignore` already ignores `/site/` (generated output) and every `data/`
  directory; the fixture `web/tests/fixtures/python-site/` is not affected.

## Open questions for the owner

1. Contract §2.6 additions (all optional, see *Deviations* 3): accept them into the plan text
   (`status` in the manifest, `precip_n_samples`, `estimated`, `low_battery` and
   `unlogged_off_site` events, the two extra variables)?
2. Default published event kinds (`site.events`): off_site, deployment, retrieval, step,
   low_battery, unlogged_off_site. Should `unlogged_off_site` (an advisory detector warning with
   a long text telling how to fill the log) be public on the portal, or only in the job
   summary?
3. Staleness 36 h (`site.stale_after_s`) — fine with the daily 06:00 run?
4. A stored sensor that is not in the registry is not published (no position); is that right,
   or should it appear in the manifest without a map marker?

## Review
Verdict: _pending_ (round 1)

| Severity | File:line | Finding | Status |
|---|---|---|---|
