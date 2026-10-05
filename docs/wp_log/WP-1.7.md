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

## Round 2 (changes after review round 1)

Orchestrator decisions on review round 1 (all findings fixed, see the Status column):

- **Secrets in logs (major 1):** `sivin.logging_setup` caps `selenium`, `urllib3` and `WDM` at
  WARNING regardless of `--log-level`, and adds `SecretRedactor` to the root handler
  (current values of `SIVIN_PASSWORD`, `SIVIN_USER` → `***` in message and traceback).
  `tests/test_logging_setup.py` drives Selenium's `RemoteConnection.execute(SEND_KEYS…)` at
  DEBUG and checks the password never reaches the output.
- **Quarantine errors (major 2):** `IngestService` catches `OSError` while reading (rule
  `file-readable`) and quarantining; the file fails with `quarantine failed: …`, the run goes
  on (exit 1).
- **Derived files never lose content (major 3):** `IndicesWriter.update` merges per (sensor,
  index) into `indices/<season>.json`; `EventsWriter` writes only the selected sensors and
  always over the whole record (`qc --from/--to` restrict the summary only, `restricted()`);
  failures keep the previous entry with `status: "failed"`, `error`, `computed_at` of the
  last success (`null` if none); nothing is written without data. Every entry now has
  `status` and `computed_at`, so successful runs rewrite the files they computed (the
  round-1 byte stability of derived files is given up for the last-success time).
- **`run --dry-run` (major 4):** implies `--skip-fetch`; `Note: fetch skipped in dry-run.`;
  tested with a driver factory that must never be called and an unchanged tree hash.
- **Exit code 4** `DATA_SOURCE_UNAVAILABLE` for missing credentials / failed login / portal
  unreachable (`SourceUnavailableError`); `run` ends with 4 after processing stored data.
- **Interval-derived defaults (OQ3):** `sivin.config.derived` lists the fields that are
  multiples of the interval (`SamplingParams`/`SampleDurationParams.max_sample_duration_s`
  2.5×, `LinearParams.max_gap_s` 1.5×, spike `min_interval_s` 1×, spike/step
  `max_interval_s` 3×, precip-counter `max_interval_s` 1.5×); they follow
  `time.expected_interval_s` unless set. New factor constants `MAX_NEIGHBOUR_INTERVAL_FACTOR`
  (spike), `MAX_JUMP_INTERVAL_FACTOR` (step), `MAX_SAMPLE_DURATION_FACTOR` (ripening params).
  Defaults at 1830 s are unchanged.
- **Minors/nits:** dropped parser flags logged at DEBUG; empty store messages; unknown
  `check_settings` at its key path; quarantine collision suffix and default `move`; DST
  gap/fold bounds rejected.
- **WP-1.2 finding (scope extended to `ingest/validation.py`):** cause: `_share_severity`
  makes a share above the limit an ERROR only when more than `min_error_rows` (3) rows are
  affected, so 1 of 7 unreadable timestamps (14.3 %) stayed a WARNING. `timestamps-parseable`
  no longer applies `min_error_rows`: any share above the limit is an ERROR. Regression test
  with the reviewer's truncated file (`test_truncated_export_is_rejected`). The WP-1.2 test
  "footer row in a short file is a warning" became an ERROR test (same file, now rejected);
  `docs/data-format.md` (*Short files*) updated accordingly — outside the listed scope, one
  paragraph, to keep the doc true.

Gates after round 2 (in `/home/user/wt/wp-1.7`): `make lint` → all checks passed;
`make type` → `Success: no issues found in 158 source files`; `make test` → **1702 passed**;
`make cov` → total 99.89 %; `sivin/app/*`, `sivin/config/*`, `logging_setup.py`,
`storage/store.py`, `ingest/validation.py` 100 % (`sivin/cli` 95–100 %, exempt).

Open questions 2 (quarantine mode) and 3 (derived defaults) are answered by the orchestrator;
1 (exit codes) is extended by code 4.

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer agent; base `0efaaaf`, head `3540a2f`.

### Gates (run by the reviewer in `/home/user/wt/wp-1.7`)

- `make lint` → `All checks passed!`; `make type` → `Success: no issues found in 157 source files`;
  `make test` → `1671 passed`.
- `make cov` → `1671 passed`, total 99.88 % (threshold 85 %); `sivin/app/*`, `sivin/config/*`,
  `storage/source.py`, `storage/store.py`, `quality/pipeline.py` 100 %, `analytics/disease/botrytis.py` 98 %.

### What the reviewer ran (operator view, temporary project outside the repo)

Temporary project `/tmp/claude-0/review-1.7/proj` (own `pyproject.toml`, copy of the committed
`config/sivin.yaml`, `sensors/sensors.geojson`, `sensors/offsite_log.yaml`), the **full real export**
of 77799986 (3520 rows) and SYNTHETIC portal-layout exports of 77678271 and 77680921
(2025-01-01 – 2026-03-01, 1830 s, 77680921 with every 13th humidity blank) and of the
unregistered 99999999. The portal URL was pointed at `127.0.0.1:9`; the real portal was not
contacted. Results:

- `sensors check` → exit 0, readable counts. `ingest --dry-run --from-dir` → exit 1 (unregistered
  sensor), **tree hash unchanged**. `ingest` → 3 files imported, 99999999 copied to
  `data/quarantine/` with `.report.json`, run record with full names, store `source` =
  `20260301T223842` etc.; second `ingest` → `+0 new`, raw files byte-identical (idempotent).
- `qc` → 77799986: all 3520 rows `PRE_DEPLOYMENT`, `off_site` event 2025-07-30T08:00Z –
  2026-03-01T21:30Z (= log 10:00 CEST / 22:30 CET); 77680921: `MISSING 1544` (= ceil(20060/13)).
- `indices --season 2025/2026` → exit 2 (`--season` takes a year; `2025` is the season of
  calendar 2025); `indices --season 2025` → exit 0, 17 indices × 3 sensors, file written.
- `run --skip-fetch` (with and without `--season`) → exit 0; `config show` / `config schema` → exit 0,
  valid YAML / JSON.
- Config errors (unknown key, typo in a check / strategy / index parameter, unknown preset,
  unknown index, bad zone, negative interval, a subsystem interval or zone contradicting `time`,
  `ingest.portal.password` in YAML, non-mapping, invalid YAML, missing `--config`) → exit 3,
  each with its key path. `time.expected_interval_s: 600` reaches parsers, sampling check, aligner
  and every index `sampling.nominal_interval_s`; the derived caps stay (documented, OQ3).
- Overlapping off-site log → `sensors check` exit 1, `qc`/`indices`/`run`/`ingest` exit 3, message
  names entries and lines. Outside a project → exit 3. Bad `--log-level`, `--sensor`, `--from`,
  `--index`, missing file → exit 2.
- Empty data dir: `qc` exit 0 (prints nothing), `indices`/`run --skip-fetch` exit 0 and write an
  indices file without sensors, `ingest` → "No export files to ingest." exit 0.
- Malformed store file → that sensor fails (exit 1), the others are processed; ingest of that
  sensor fails without touching the file.
- Random bytes as `.csv`/`.xlsx`, empty file, zip-signature junk → rejected with readable reasons.
- No credentials → `fetch` exit 3, `run` continues with stored data, exit 1, `FAILED fetch: ...`.
  `.env` never overrides an already-set variable (checked with `SIVIN_USER` set in the shell).
- Index results vs. base: indices of 77678271 and 77680921 (season 2025, store data, `MISSING`
  set on half rows) computed with the base source and with this branch → only `dew_point` of
  77678271 differs, 11.4801935 → 11.4801930 °C (last-sample weight 1825 → 1830 s). No unexpected change.
- Row validity (`qc = 0`, every second row without humidity or without temperature): frost,
  heat_hours, dew_point, vpd, powdery_mildew_gt get no day/hour from half rows; `SampleSet` keeps
  72 of 144 samples; Broome wetness periods end at every half row (72 one-sample periods of a
  3-day wet spell) — consistent with the whole-row rule and with flagged data.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | src/sivin/cli/main.py:71 (with `logging_setup.setup_logging`) | `--log-level DEBUG` turns on Selenium's `remote_connection` debug logger, which logs every WebDriver command body. The login `send_keys` body is `{'text': '<password>', 'value': [...]}` (below Selenium's 100-character trim), so a real `sivin fetch`/`sivin run --log-level DEBUG` writes `SIVIN_PASSWORD` (and user name) in clear text to the log. Reproduced with Selenium 4.50 `RemoteConnection.execute(SEND_KEYS_TO_ELEMENT, ...)` after `setup_logging("DEBUG")`: `POST .../element/e/value {'text': 'pwSENTINEL2', ...}`. Fix: in the CLI logging setup cap `selenium` and `urllib3` loggers at `INFO`/`WARNING` regardless of `--log-level` (or add a filter that drops `selenium.webdriver.remote.remote_connection` records), plus a test that a DEBUG fetch with the fake driver / a direct `RemoteConnection` call never logs the secret. | fixed: `setup_logging` pins `selenium`, `urllib3`, `WDM` to WARNING whatever `--log-level`; `SecretRedactor` on the root handler replaces the current `SIVIN_PASSWORD`/`SIVIN_USER` values by `***` in message and traceback; tests with `RemoteConnection.execute(SEND_KEYS_TO_ELEMENT)` at DEBUG (with and without the cap); documented in `docs/cli.md` |
| major | src/sivin/app/ingest.py:132-137, 304 | `Quarantine.put` is not guarded: if the rejected file cannot be copied/moved (unreadable, removed meanwhile, quarantine dir not writable, disk full) the `OSError` escapes `IngestService.ingest`, so `sivin ingest` and `sivin run` abort with a traceback before QC, indices and the run record. The parser already turns the unreadable file into a `file-readable` rejection; only the quarantine step crashes. Reproduced by patching `Path.read_bytes`/`shutil.copyfile` to raise `PermissionError` for one file: `CRASH PermissionError`. Contradicts the class docstring "one bad file never stops it" and WP-4.1's "continue past failures". Fix: catch `OSError` in `_one` around `put` (and around `_reader.read` for safety), record `failure="rejected: ...; quarantine failed: ..."`, still write the report JSON if possible; test it. | fixed: `OSError` of reading (rule `file-readable`) and of quarantining is caught, logged at ERROR, recorded as `rejected: …; quarantine failed: …` (run record, exit 1), next file processed; tests |
| major | src/sivin/app/indices.py:400-401; src/sivin/app/quality.py:307 | Selection options silently overwrite the derived files (the WP-3.2 input) with partial content. `sivin indices --season 2025 --sensor 77678271 --index huglin` replaced `indices/2025.json` (3 sensors × 17 indices) by one sensor × one index; `sivin run --sensor X` does the same; a sensor that fails or has no data in a run disappears from the file. `sivin qc --sensor 77799986 --from 2026-02-01 --to 2026-02-02` replaced `events/77799986.json` (3520 samples, 6 events) by 94 samples and 1 event. Not documented in `docs/cli.md`/`docs/storage.md`. Fix (owner's choice): merge per sensor/index into the existing file, or write derived files only for unrestricted runs (restricted runs report only, like `--dry-run`), or at least document it and keep failed sensors' previous entries; add tests. | fixed: indices file merged in place per (sensor, index) (`IndicesWriter.update`); events written only for selected sensors and always over the whole record (`--from/--to` restrict only the printed summary); failed sensor/index keeps its previous entry + `status: failed`, `error`, `computed_at` of the last success; nothing written without data; `docs/cli.md`, `docs/storage.md`; tests |
| major | src/sivin/app/factory.py:302-310; src/sivin/app/run.py:217 | `sivin run --dry-run` (without `--skip-fetch`) logs into the portal and downloads every export into `data/downloads/`, then prints "Dry run: nothing was written." (`--help`: "Compute and report, but write nothing."). Reproduced with the WP-1.3 fake driver: three new files in `data/downloads` after `run --dry-run`. A later plain `sivin ingest` then ingests them. Fix: make `--dry-run` imply `--skip-fetch` (or fetch into a temporary directory that is removed), document it, test with a tree hash. | fixed: `--dry-run` implies `--skip-fetch`, prints `Note: fetch skipped in dry-run.`; CLI test: driver factory never called, project tree hash unchanged |
| minor | src/sivin/app/ingest.py:324 (with storage/store.py:148) | Every ingest of a normal export logs WARNINGs "QC flags are not stored in raw files and were dropped: MISSING on 1544 row(s), TIMESTAMP_SUSPECT on 2 row(s)", because the parser's flags reach `store.append`. In the daily job this is noise that hides real warnings. Fix: `IngestService` passes the series with `qc` cleared (the flags are recomputed by QC), or logs at INFO. | fixed: DEBUG when only `MISSING`/`TIMESTAMP_SUSPECT` are dropped, INFO with counts when other flags are; test; `docs/storage.md` |
| minor | src/sivin/cli/commands/report.py:47; src/sivin/app/indices.py:400 | Empty store: `sivin qc` prints nothing and exits 0; `sivin indices`/`run --skip-fetch` exit 0 and write an indices file with `"sensors": {}` over any earlier one. For an unattended job (e.g. the `data` branch not checked out) "OK" with an empty result is misleading. Fix: print "No stored data." and do not write the indices file when no sensor has data (or treat it as a failure in `run`). | fixed: `No stored data.` / `No stored data for this season; nothing written.`, exit 0, no file written; tests |
| minor | src/sivin/app/run.py:217-219; docs/cli.md (Exit codes) | Missing credentials / failed login in `sivin run` is exit 1, the same as one rejected file or one failed device, so WP-4.1 cannot tell "portal permanently broken / secrets missing" from a routine partial failure without parsing text. Owner question OQ1; suggest a distinct code or a machine-readable run summary (e.g. step outcomes in the run record) for the job summary. | fixed: new exit code 4 `DATA_SOURCE_UNAVAILABLE` (`SourceUnavailableError`): `fetch` and `run` (which still processes the stored data); table in `docs/cli.md` |
| minor | src/sivin/config/shared.py:124-131; docs/configuration.md | Derived defaults do not follow `time.expected_interval_s` (documented, OQ3). Consequence not documented: with `time.expected_interval_s` ≥ 4575 s the configuration fails with six errors at `analytics.indices.*.sampling` ("max_sample_duration_s must not be shorter than nominal_interval_s") that do not mention `time.expected_interval_s`. Fix: either derive the caps from the shared interval or name `time.expected_interval_s` in the message / docs. | fixed (OQ3 answered yes): duration caps, `max_gap_s`, spike/step/precip-counter intervals are factors of `time.expected_interval_s` unless set (`sivin.config.derived`); messages naming such a field add the interval and the rule; reference shows `= 2.5 x time.expected_interval_s`; tests |
| nit | src/sivin/quality/pipeline.py:111 | An unknown key under `quality.check_settings` is reported at `quality` ("check_settings given for checks that are not enabled: ['nonexist']"), not at `quality.check_settings.nonexist` like every other config error. | fixed: reported at `quality.check_settings.<name>` (unknown check / not enabled); test |
| nit | src/sivin/app/ingest.py:131-137 | A rejected file with the same name as an earlier quarantined one silently overwrites it and its report; with `quarantine_mode: copy` and `run --skip-fetch`, a bad file in the download directory is re-rejected (exit 1) on every run until removed by hand (relates to OQ2). | fixed: collision → `<stem>_<YYYYMMDDTHHMMSSZ>[_n]<suffix>`, nothing overwritten; default `quarantine_mode: move` (answers OQ2); tests, docs |
| nit | src/sivin/app/period.py (`_instant`) | `--from/--to` local times in the DST gap or fold are accepted silently with `fold=0`; the parsers reject/flag such times. Low impact. | fixed: rejected (exit 2) with a request for an explicit offset; tests |

### Deviations assessment

1. **Files outside the literal scope (1825 s cleanup):** demanded by the brief (WP-0.2 list). Reviewed
   `5d0c20d`: mechanical (constant swap `LEGACY_SAMPLING_INTERVAL_S` → `DEFAULT_SAMPLING_INTERVAL_S`,
   prose, recomputed test values); the `grid.py` `usable_span` row-validity change is correct and
   in the spirit of task 5. Accepted.
2. **Default changes (935 s, 2745 s, 4575 s, 5490 s, spike `min_interval_s` 1830 s):** consistent
   (½·1830+20, 1.5·1830, 2.5·1830, 3·1830) and documented in the field descriptions,
   `docs/alignment.md`, `docs/quality-control.md`, `docs/indices/*`. Base-vs-head comparison on
   store data changed only `dew_point` by 4.5e-7 °C. Accepted.
3. **`sivin.config` imports the subsystems and pandas:** acceptable — composing the subsystem
   models requires it, and `sivin --version`/`--help` stay light via lazy imports in `cli/state.py`
   (subprocess test). The owner should know the WP-0.1 decision is reversed.
4. **Shared values by field name:** works (verified with 600 s, conflicts reported with key paths).
   Risk: a future field called `expected_interval_s` with another meaning would be overwritten
   silently; acceptable with the docstring warning. `offsite_log.timezone` is deliberately not shared.
5. **`gsr.preset` in the config layer:** fine; unknown preset fails with its key path.
6. **Global `--config`, exit 3 for invalid config:** fine, documented.
7. **Source identifiers:** verified. Old full names read back shortened; a file is rewritten only
   when its data change. Two exports collide on one id only if their export times are equal to the
   second (or a 48-bit hash collides); `source` is provenance only — the conflict policy uses import
   order, not `source` (`storage/conflicts.py:172-196`) — so a collision cannot change data, it only
   makes the provenance ambiguous between files that the run log lists in full anyway.
8. **ISO times in derived files:** fine for WP-3.2 (mapping is its job); see the major on partial
   overwrites before WP-3.2 relies on them.
9. **Exit codes 0/1/2/3:** consistent across commands (verified); see minor on run/fetch failures.
10. **Indices QC over the whole record, previous year loaded:** correct; `--season` is a calendar year,
    so the season of 2025 is `--season 2025` (a value like `2025/2026` is a usage error, exit 2).
11. **Extra options:** fine.

### Readiness for WP-4.1 / WP-3.2

- Portal down / no secrets: `run` keeps the stored data, runs QC and indices, records `fetch: ...`,
  exit 1 — good. A crash in quarantine (major 2) or an invalid off-site log (exit 3, by plan §2.8)
  stops the whole run including fetch/ingest.
- Restartable: yes — ingest is idempotent, derived files are rewritten atomically, the store is
  never left half-written per file (atomic writes; a mid-run failure leaves complete partition
  files). Each re-run downloads the exports again; old downloads accumulate in `data/downloads`
  (WP-4.1 should decide whether to keep them on the `data` branch).
- Do not enable `--log-level DEBUG` in the workflow until major 1 is fixed.
- WP-3.2: the derived formats are documented and byte-stable; fix major 3 first, and note that
  disease indices return a numeric value (e.g. `0`) with `coverage 0.00` for an all-off-site
  sensor — the site must use `complete` (out of scope here, WP-2.3 semantics).

### Out of scope (seen during review)

- WP-1.2: a truncated export with 1 of 7 timestamps unreadable (14.3 %, "limit 5.0 %") is only a
  WARNING and the file is accepted (`timestamps-parseable`).

### Round 2

Verdict: CHANGES_REQUESTED (round 2)

Reviewer: independent reviewer agent; head `06914ff` (fixes `759443e`, `9140889`, `1c26216`).

Gates (run by the reviewer): `make lint` → `All checks passed!`; `make type` → `Success: no
issues found in 158 source files`; `make test` → `1702 passed`; `make cov` → `1702 passed`,
total 99.89 % (`sivin/app/*`, `sivin/config/*`, `logging_setup.py`, `storage/store.py`,
`ingest/validation.py` 100 %).

Re-run of the operator project (`/tmp/claude-0/review-1.7/proj2`, same real and SYNTHETIC
exports, portal URL `127.0.0.1:9`) and of the round-1 probes:

- `ingest` → 3 imported, 99999999 **moved** to quarantine; second `ingest` → `+0 new`. `qc`,
  `indices --season 2025`, `run --skip-fetch` exit 0/1 as before; the off-site flags of 77799986 are unchanged.
- **Dry run:** a tree hash (`find -print0 | sha256sum`) before and after `qc --dry-run`, `indices
  --dry-run`, `run --dry-run`, `run --skip-fetch --dry-run` and `ingest --dry-run`, with a rejectable
  file in `data/downloads`, shows **no change**. `run --dry-run` with the fake portal: no
  download, tree unchanged, "Note: fetch skipped in dry-run".
- **Portal down:** without credentials `fetch` → 4 and `run` → 4. `run` still ingests nothing new,
  runs QC and the indices, records `fetch: ...` and prints `DATA_SOURCE_UNAVAILABLE`. With credentials
  and no browser/portal, `run` → 4. A Selenium `WebDriverException` during login → 4.
- **Merge in place:** a corrupt store file of 77680921 → `indices`/`qc` exit 1; the file keeps all
  3 sensors × 17 indices. The failed entries keep their previous values with `status: failed`,
  `error` and the old `computed_at`, and the events file keeps its content with `status: failed`.
  `indices --sensor 77678271 --index huglin` leaves 17/17/17 entries.
  `qc --from/--to` restricts only the summary; the events file still has 3520 samples and 6 events.
- **Quarantine failure** (patched `read_bytes`/`move`/`copy` raising `PermissionError`): the file
  fails with `rejected: ...; quarantine failed: ...`, the next (good) file is imported, outcome 1. A name
  collision gets the `_<UTC time>` suffix; nothing is overwritten.
- **Interval-derived defaults:** at 1830 s `config show` is identical to round 1 (apart from
  `quarantine_mode`). At 600 s: duration caps 1500, linear `max_gap_s` 900, spike `min/max` 600/1800,
  precip counter 900. At 5000 s it loads. An explicit value is kept. The error message names
  `time.expected_interval_s`. `config show` output reloads to the same config.
- **Secrets in logs:** with `--log-level DEBUG` and the fake portal (whose `send_keys` logs on
  Selenium's wire logger), neither the user name nor the password appears in the output. The
  round-1 `RemoteConnection` reproduction is now a test.
- **WP-1.2 timestamp rule:** the real export (trailing `;` line) still passes, with 3520 rows.
  Daily-sized portal exports (48 rows + `;`, 48 rows + `;;;;;`) pass, and 2 rows + `;` passes.
  48 rows + a text footer is 1/49 = 2 %, a WARNING. Only a *text* footer in a file of
  fewer than 20 rows is now rejected; the portal does not write one. Not harmful.
  Truncation of the last line of a long export stays a WARNING (share below 5 %), which is
  harmless because the rows before it are complete.

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | src/sivin/app/fetch.py:121-125; src/sivin/cli/common.py:50-52; src/sivin/app/run.py (record failures) | Redaction covers only `logging` records. A credential that appears in the **message of an exception** reaches unredacted (a) standard error (`Error: Portal session failed: ...` via `typer.echo`, and `FAILED fetch: ...`) and (b) the run record `data/runs/<date>.jsonl`, which WP-4.1 commits to the public `data` branch. Reproduced with the WP-1.3 fake portal: the password element's `send_keys` raises `WebDriverException(f"... cannot type {text!r} ...")`. `sivin fetch` (exit 4) prints the password, and `sivin run` prints it and writes it into the run record. The first `send_keys` does the same with the user name. Chromedriver errors are not known to echo typed text, so the likelihood is low, but the plan forbids printing or committing credentials and the round-2 brief explicitly covers exceptions raised from Selenium. Fix: redact the message of `SourceUnavailableError` with the credentials `FetchService` holds (or a shared `redact()` from `logging_setup`), so it is safe in stderr, the run record and derived JSON; add a test with the raising fake element. | open |
| minor | src/sivin/logging_setup.py:79-81 | `SecretRedactor` replaces every occurrence of `SIVIN_USER`/`SIVIN_PASSWORD`, without a minimum length. With `SIVIN_USER=u SIVIN_PASSWORD=e` every log line is mangled (`Load***d 4 s***nsors from /tmp/cla***d***-0/...`). A real user name that is a common word (e.g. `vut`, `sivin`) would mangle paths and messages and reveal the value by its pattern. Suggest skipping values shorter than ~4 characters (and documenting it), or redacting the user name only inside credential-bearing contexts. | open |
| nit | src/sivin/app/indices.py / app/quality.py (`error` fields) | `error` texts in the derived JSON (a WP-3.2 input, published) contain absolute runner paths, e.g. `/home/runner/.../data/raw/77680921/2025.csv:17233: ...`. Consider making paths relative to the project root. | open |
| nit | src/sivin/app/indices.py (`IndicesWriter.update`) | Merged entries are never pruned: a sensor removed from the store or the registry, or an index removed from the registry, stays in `indices/<season>.json` with its last values and `status: ok`. Only deleting the file clears it. Document it, or drop sensors/indices that are no longer registered. | open |
| nit | docs/cli.md:108 | With the new default `quarantine_mode: move`, `sivin ingest ~/somewhere/file.csv` moves the user's own file into `data/quarantine/` when it is rejected. This is documented for downloads; one sentence for explicit FILE arguments would avoid surprise. | open |

Round-1 findings: all four majors, the four minors and the three nits are verified **fixed** as described in their
Status column. Major 1 is fixed for log records only; the remaining exception-message path is the new major above.

Assessment of the round-2 deviations:

- **Exit code 4:** good for WP-4.1. `run` ends with 4 even when other steps also failed, because 4
  is the highest code; the job summary should still list the other failures.
- **Merging derived files in place, with `status`/`computed_at`:** behaves as described. Giving up
  byte stability means one data-branch diff per day, which is acceptable with the daily commit.
- **Default `move`:** fine for unattended runs.
- **Interval-derived defaults:** consistent; the defaults at 1830 s are unchanged.
- **WP-1.2 `min_error_rows` reversal for `timestamps-parseable`:** not harmful for real portal files (see above).
