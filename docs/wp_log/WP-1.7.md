# WP-1.7 — Integration: CLI and one configuration

## Summary

One command-line tool and one configuration file now run the whole pipeline locally (and,
from WP-4.1, in GitHub Actions): `sivin fetch` → `sivin ingest` → `sivin qc` (with the off-site
log) → `sivin indices`, or all of them as `sivin run`; plus `sivin sensors check`,
`sivin config show` and `sivin config schema`. `config/sivin.yaml` composes the settings of
every subsystem; `time.expected_interval_s` (1830 s) and the time zones are written into every
subsystem field of the same name, and the registry-backed settings (quality checks, alignment
strategy, index parameters incl. `gsr.preset`) are validated when the file is loaded, so an
unknown key fails with its key path. The CLI is thin: the work is done by application services
in the new package `sivin.app`, built from the configuration by `ServiceFactory` and tested
without typer. The risk locations of WP-0.2 now check row validity on the values
(`complete_mask`), every interval default is based on the measured 1830 s, the store keeps a
short export identifier as `source`, and the quality pipeline enables the WP-1.9 checks and
applies the precipitation set-aside. An end-to-end test runs the real export of 77799986 and
synthetic exports through the real CLI with the WP-1.3 fake browser. Everything was verified on
the trimmed real export and synthetic data only; the real portal was not contacted.

## Changed files

Commits on `wp/1.7-integration` (base `0efaaaf`):

| Commit | Content |
|---|---|
| `db2c824` | row validity on the values: `analytics/disease/botrytis.py`, `analytics/disease/powdery_mildew.py`, `analytics/ripening/durations.py` (`masked_values`), `alignment/strategies.py` (`SampleSet.from_series`), `alignment/grid.py` (`usable_span`); tests with half rows and `qc = 0`; `docs/alignment.md`, `docs/architecture.md` |
| `5d0c20d` | interval defaults on `DEFAULT_SAMPLING_INTERVAL_S` (1830 s) instead of `LEGACY_SAMPLING_INTERVAL_S`: `quality/checks/{sampling,spike,step}.py`, `quality/{contrast,regime}.py` (text), `alignment/{strategies,config,grid,aligner}.py`, `analytics/disease/sampling.py`, `analytics/ripening/{params,durations}.py`; hand-computed test values; `docs/alignment.md` (incl. line 99), `docs/quality-control.md`, `docs/indices/*.md` |
| `448ab0a` | `storage/source.py` (`ExportSourceIds`), `storage/store.py`, `storage/__init__.py`; `tests/storage/test_source.py`, store tests; `docs/storage.md` |
| `fd6ca74` | `quality/pipeline.py` (WP-1.9 checks in the defaults, `ValueSetAside`, `QualityResult.values_set_aside`); tests; `docs/quality-control.md` |
| `117acbf` | `src/sivin/config/` package (`sections`, `shared`, `registered`, `resolver`, `model`, `loader`, `schema`) replacing `config.py`; `config/sivin.yaml`; docstrings of `storage/config.py`, `alignment/config.py`, `quality/pipeline.py`; `tests/config/`, `tests/test_config.py` |
| `a7f8066` | `src/sivin/app/` (`workspace`, `factory`, `catalog`, `fetch`, `ingest`, `quality`, `indices`, `run`, `environment`, `json_files`, `outcome`); `pyproject.toml` (`python-dotenv>=1.0`); `tests/app/` |
| `7bc3709` | `src/sivin/cli/` package (`main`, `state`, `common`, `commands/*`) replacing `cli.py`; `app/period.py`; `tests/cli/`, `tests/test_cli.py` |
| `1f14136` | `tests/e2e/test_pipeline.py`; `tests/app/fake_portal.py` |
| `ac6455a` | `docs/cli.md`, `docs/configuration.md` (new), `docs/storage.md`, `docs/architecture.md`, `README.md` (quick start), `.env.example` |
| this commit | `docs/wp_log/WP-1.7.md`, two stale "proposed" wordings in `docs/architecture.md`, `docs/storage.md` |

### Public API

```python
# sivin.config
SivinConfig(paths, time, registry, offsite_log, ingest, storage, quality, alignment, analytics)
    # resolved on every construction; SivinConfig() == SivinConfig.default() == complete defaults
PathsConfig(data_dir, derived_dir, quarantine_dir, site_dir, sensors_file, output_dir)
TimeConfig(source_timezone, display_timezone, expected_interval_s)
IngestConfig(portal: PortalSettings, parsers: ParserSettings, validation: ValidationSettings,
             quarantine_mode: QuarantineMode, file_patterns)
AnalyticsConfig(min_daily_coverage, min_season_coverage, exclude_mask, auxiliary_exclude_mask,
                indices: dict[index_id, params])
load_config(path) -> SivinConfig; ConfigError; describe(ValidationError) -> str
sivin.config.shared: SharedValue, SharedValues.from_time(time).apply(model, raw, loc, problems)
sivin.config.registered: RegisteredSettings (ABC: location, keyed, models(), resolve());
    CheckSettingsResolution, StrategyParamsResolution, IndexParamsResolution, ParamPreset,
    PARAM_PRESETS, default_resolutions()
sivin.config.resolver: ConfigResolver().resolve(model, data)
sivin.config.schema: ConfigSchema().json_schema()/.text(); ConfigReference().rows()/.markdown()

# sivin.app
Workspace.open(config_file=None, start=None) -> Workspace   # .data_dir, .events_dir, ...
ServiceFactory(workspace, drivers=None, credentials=None, clock=None)
    .catalog(), .sensors_check(), .store(), .ingest_service(dry_run), .quality_service(dry_run),
    .indices_service(dry_run), .fetch_service(headed, download_dir), .run_service(dry_run,
    skip_fetch, headed), .run_recorder(), .export_paths(files, from_dir), .portal_settings(...)
Outcome (OK=0, PARTIAL_FAILURE=1, USAGE_ERROR=2, SETUP_ERROR=3); SetupError; UnknownIndexError
SensorCatalog, SensorCatalogLoader, SensorsCheck, SensorsCheckReport
IngestService(reader, store, registry, quarantine, dry_run).ingest(paths) -> IngestReport
    ExportReader, Quarantine, FileOutcome, DirectoryExports, export_files()
QualityService(store, pipeline, registry, events, dry_run).run(sensors, start, end) / .checked()
    EventsWriter, QualityReport, SensorQuality
IndicesService(quality, contexts, selection, directory).run(season, sensors, index_ids, checked)
    SeasonWindow, IndexContextFactory, IndexSelection, IndicesReport
FetchService(settings, credentials, drivers).fetch(sensors) -> FetchReport; PortalExports
RunService(source, ingest, quality, indices, recorder, clock, dry_run).run(season, sensors)
    RunRecorder, RunReport, ExportSource (Protocol)
DotEnvLoader(root).load(); JsonFileWriter; TimeBounds.parse(start, end, timezone)

# sivin.storage
ExportSourceIds().of(name) / .shorten(series) / .is_identifier(text)
MeasurementStore(..., source_ids=None)
# sivin.quality.pipeline
ValueSetAside (Protocol); QualityResult.values_set_aside
```

CLI: [docs/cli.md](../cli.md); configuration: [docs/configuration.md](../configuration.md).

## How it was verified

All commands in `/home/user/wt/wp-1.7` (venv by `uv`, Python 3.12, ruff 0.16, mypy 2.4).

- `make lint` → `All checks passed!`, all files formatted.
- `make type` → `Success: no issues found in 157 source files`.
- `make test` → `1671 passed`.
- `make cov` → total **99.88 %** (threshold 85 %). New and changed code: `sivin/app/*` 100 %
  (every module), `sivin/config/*` 100 %, `storage/source.py` 100 %, `storage/store.py`
  100 %, `quality/pipeline.py` 100 %, `alignment/{grid,strategies}.py` 100 %,
  `analytics/ripening/durations.py` 100 %, `analytics/disease/powdery_mildew.py` 100 %,
  `analytics/disease/botrytis.py` 98 % (lines 367–368, see *What did not work*);
  `sivin/cli/*` 95–100 % (exempt).
- The new half-row tests (`qc = 0`, one variable missing) fail on the base commit (7 failures,
  checked with `git stash` of `src/`) and pass now.
- `sivin sensors check` in the worktree on the committed registry and off-site log:
  `Sensor registry: 4 sensor(s), 4 active.` / `Off-site log: 1 period(s).`, exit 0.
- `load_config(config/sivin.yaml) == SivinConfig()` (test). `docs/configuration.md` equals
  the generated reference (test).
- `import sivin.cli` does not load pandas (subprocess test).
- End-to-end (`tests/e2e/test_pipeline.py`, through typer's `CliRunner`): fetch with the fake
  browser, ingest of the real export and two synthetic exports (store files, short ids,
  run record with full names), QC (all 300 rows of 77799986 `PRE_DEPLOYMENT`, `off_site`
  event 2025-07-30T08:00Z – 2026-03-01T21:30Z from the log), indices JSON shape, repeated
  ingest adds nothing; `sivin run` continues past a device the portal does not list (exit 1)
  and exits 0 when everything succeeds.

## What did not work / what was not verified

- **The real portal was not contacted** (no network, no credentials). `sivin fetch` and
  `sivin run` are tested only with the WP-1.3 fake browser.
- Only the trimmed real export of one sensor (77799986, entirely off site) exists; indices on
  real vineyard data were not computed. All index values in the tests come from synthetic data.
- `docs/configuration.md` describes the resolution; the derived defaults that are *computed*
  from the interval (spike/step `max_interval_s`, duration caps, `max_gap_s`) do not follow a
  changed `time.expected_interval_s` (documented there).
- `botrytis.py` lines 367–368 (a wetness period without valid temperature) are unreachable
  now: a period consists of complete rows only. The guard stays because
  `WetnessPeriod.mean_temp_c` is typed optional (WP-2.3 API).
- The CI workflow did not run (nothing pushed).

## Deviations

1. **Files outside the literal Files scope**, required by task 1 of the brief ("remove the
   remaining 1825 s mentions listed in WP-0.2's hand-off note"): `quality/checks/{sampling,
   spike,step}.py`, `quality/{contrast,regime}.py`, `alignment/{config,grid,aligner}.py`,
   `analytics/disease/sampling.py`, `analytics/ripening/params.py`, `docs/quality-control.md`,
   `docs/indices/{bedd,botrytis_broome,cool_night,dew_point,frost,gdd_winkler,gst,heat_hours,
   huglin,powdery_mildew_gt,vpd}.md`, and their tests. In `docs/quality-control.md` I also
   corrected the stale `missing` default (`any` since WP-0.2) and documented the pipeline
   set-aside and wiring. `alignment/grid.py` `usable_span` got the same row-validity fix as
   `strategies.py` (listed by WP-0.2, not by the brief). `.env.example`: one comment.
2. **Behaviour changes of defaults** (1825 → 1830 s base): aligner tolerance 932.5 → 935 s,
   `max_gap_s` 2737.5 → 2745 s, sample-duration caps 4562.5 → 4575 s, nominal durations
   1825 → 1830 s, spike `min_interval_s` 1825 → 1830 s, spike/step `max_interval_s`
   5475 → 5490 s. Test expectations were recomputed by hand.
3. **`sivin.config` now imports the subsystems** (and pandas), reversing the WP-0.1 decision
   that the configuration module is light; the configuration has to compose the subsystem
   models. `sivin --version` stays light because the CLI imports the application layer only
   when a command runs (test kept, now for `sivin.cli`).
4. **Shared values are matched by field name** (`expected_interval_s`, `nominal_interval_s`,
   `source_timezone`, `display_timezone`) instead of a list of paths, so a new subsystem with
   such a field is covered automatically; a contradicting explicit value is an error, an equal
   one is accepted.
5. **`gsr.preset`** is handled in the configuration layer (`ParamPreset`), not in
   `GsrParams` (out of scope); the resolved configuration shows the expanded `targets`.
6. **Global `--config`** replaces the `config show --config` option of WP-0.1; an invalid
   configuration exits with 3 (was 1).
7. **Source identifier**: a bare `YYYYMMDD_HHMMSS` (the synthetic WP-1.9 legacy store
   fixture) is read as an export time too; any other name becomes `h` + 12 hex digits of the
   SHA-256 of the file name. Old full names are shortened when read; a file is rewritten with
   identifiers only when its data change.
8. **Derived files** (`events/<id>.json`, `indices/<season>.json`) carry no run time, so they
   are byte-stable; times are ISO 8601 UTC (not Unix seconds as in the site contract — the
   mapping is WP-3.2's).
9. **Exit codes**: 0 ok, 1 partial failure, 2 usage (typer), 3 setup error. `sivin run` treats
   a failed login / missing credentials as a failed step (exit 1) and continues with the stored
   data, as WP-4.1 requires; `sivin fetch` alone exits 3.
10. **`sivin indices`** QCs each sensor's whole record and cuts the season window (the same
    flags as `sivin qc`); the window is the previous calendar year plus the season year, so
    `winter_freeze` has its previous autumn. `sivin run` reuses the QC results of its `qc`
    step.
11. **Additional options**: `sivin run --skip-fetch` (ingest the download directory instead of
    the portal), `sivin run --season` (default: current year), `sivin config schema --markdown`.

## Out of scope

- `src/sivin/core/defaults.py`: `LEGACY_SAMPLING_INTERVAL_S` is no longer used anywhere;
  remove it (core contract owner).
- Docstrings that still say "proposed configuration section": `ingest/parsers/columns.py`
  (`ColumnAliases`, `ParserSettings`), `ingest/validation.py` (`ValidationSettings`),
  `registry/settings.py`, `registry/offsite/settings.py`; and `docs/data-format.md:247,296,302`,
  `docs/ingest.md:167` (also says "export the variables first" — `sivin` now reads `.env`).
- `docs/web.md:191` mentions the 1825 s step of the web fixture (web, WP-3.x).
- WP-1.2 proposal: build `ingest.parsers.legacy_sheet_sensors` from the registry (4-digit
  suffix → serial); not done, the legacy workbook needs the mapping in the YAML.
- WP-3.2: read measurements through `QualityService.checked` (QC before export), map the
  derived events (ISO times, `t_end`) to the site contract and decide which WP-1.9 event types
  go to the site.
- The registry placements carry placeholder deployment dates (Q3); they are passed to the
  detector as known deployments, which has no effect on flags in the default advisory mode.
- Generic `Registry[T]` in core (raised by WP-0.1, 1.4, 1.5, 1.6): the config layer now talks
  to four registries with different method names (`ids()`/`names()`, `get`).

## Open questions for the owner

1. Exit codes 0/1/2/3 (above): fine for the scheduled workflow (WP-4.1)?
2. Rejected exports are **copied** to `data/quarantine/` by default (`ingest.quarantine_mode`);
   should `sivin run` move them out of the download directory instead?
3. Should the defaults derived from the interval (duration caps, `max_gap_s`, spike/step
   `max_interval_s`) follow `time.expected_interval_s` automatically (a contract change in the
   subsystems), or stay separate parameters as now?
4. Is the format of `data/derived/events/<id>.json` and `data/derived/indices/<season>.json`
   (docs/storage.md, *Derived data*) acceptable as the input of WP-3.2?
5. Q4 (cultivar per sensor) would let `gsr.preset` be chosen per sensor from the registry
   `variety`; today one preset applies to all sensors.

## Review

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
