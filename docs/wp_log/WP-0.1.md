# WP-0.1 — Foundation

## Summary

Package skeleton `sivin` (src layout, Python ≥ 3.12) with tooling (`pyproject.toml`, `Makefile`,
pre-commit, CI workflow, targeted `.gitignore`) and the shared contracts every later
workpackage builds on: `SensorId`, `QcFlag`, `MeasurementSeries`, `LocalTimeConverter`,
`DailyWeather`, `MonthDay`/`Season`, the `ClimateIndex` extension point with `IndexResult` and
`IndexRegistry`, the configuration models (`SivinConfig`), `ProjectPaths`, logging setup and the
CLI skeleton (`sivin --version`, `sivin config show`). The legacy `requirements.txt` is deleted;
legacy scripts and YAML files are unchanged and excluded from ruff and mypy.
`docs/architecture.md` condenses MIGRATION_PLAN §2.

**Round 2** addressed the review (round 1): fall-back resolution per transition, per-variable
daily aggregation, no silent duplicate UTC instants, stricter validation (`DailyWeather`,
`IndexContext`, `SensorId`, `MeasurementSeries`, config), `params_model` check, light config
imports via `sivin.core.defaults`, bounded dev tools and a `.gitignore` test. Details per
finding are in the *Status* column of the review table.

**Round 3** (converter only, review round 2): only the clock-jump rule yields resolved
fall-back rows (spacing guesses are `unresolved`), the input order contract "source order,
oldest first" is validated (`ValueError`), equal consecutive wall-clock values are duplicates
rather than a jump, `from_records` rejects `NaT` before the duplicate reduction, and
`IndexContext` rejects a `bool` mask and latitudes outside -90..90.

## Changed files

- Tooling: `pyproject.toml`, `Makefile`, `.pre-commit-config.yaml`, `.gitignore`,
  `.github/workflows/ci.yml`, `requirements.txt` (deleted).
- Configuration: `config/sivin.yaml`.
- Package: `src/sivin/{__init__,cli,config,paths,logging_setup}.py`,
  `src/sivin/core/{__init__,ids,flags,schema,timeutil,daily,season,defaults}.py`,
  `src/sivin/analytics/{__init__,base}.py`,
  `src/sivin/{registry,ingest,storage,quality,alignment}/__init__.py` (docstring only).
- Tests: `tests/conftest.py`, `tests/core/test_{ids,flags,schema,timeutil,daily,season}.py`,
  `tests/analytics/test_base.py`, `tests/test_{config,paths,cli,gitignore}.py`.
- Docs: `docs/architecture.md`, `docs/wp_log/WP-0.1.md`.

## Public API for later workpackages

```python
# sivin.core.ids
@dataclass(frozen=True, slots=True, order=True)
class SensorId:
    serial: str                                   # exactly 8 digits
    @classmethod
    def parse(cls, text: str) -> SensorId         # all §2.4 spellings + file paths
    legacy_suffix: str                            # property, last 4 digits
    def __str__(self) -> str                      # the serial

# sivin.core.flags
class QcFlag(enum.IntFlag): OK, MISSING, OUT_OF_RANGE, SPIKE, STEP, STUCK, PRE_DEPLOYMENT,
    NEIGHBOR_OUTLIER, TIMESTAMP_SUSPECT, MANUAL_EXCLUDE, DEFAULT_EXCLUDE (=311); all_bits() -> int
def is_excluded(flags: int, mask: int) -> bool
def excluded(flags: ArrayLike, mask: int) -> NDArray[np.bool_]

# sivin.core.schema
class Column(StrEnum): SENSOR_ID, TIMESTAMP, TEMP, RH, QC, SOURCE
class SchemaError(ValueError)
class MeasurementSeries:
    def __init__(self, sensor_id: SensorId, frame: pd.DataFrame)          # strict validation
    @classmethod from_records(sensor_id, timestamps_utc, temp_c, rh_pct, qc=None, source=None)
    @classmethod empty(sensor_id)
    sensor_id, frame (copy), timestamps (copy), is_empty, __len__
    between(start, end), with_flags(flags), valid_mask(exclude_mask) -> pd.Series[bool],
    to_frame() -> pd.DataFrame   # with leading sensor_id column

# sivin.core.timeutil
@dataclass(frozen=True) class ConversionResult:
    timestamps_utc: pd.Series; suspect: pd.Series; unresolved: pd.Series
class LocalTimeConverter:
    def __init__(self, timezone: str); timezone: str
    to_utc(local_naive: pd.Series) -> ConversionResult
    local_dates(utc: pd.Series) -> pd.Series           # datetime.date values
    day_bounds_utc(day: date) -> tuple[pd.Timestamp, pd.Timestamp]   # half-open [start, end)
    day_length_s(day: date) -> float

# sivin.core.daily
class DailyWeather:
    def __init__(self, sensor_id: SensorId, frame: pd.DataFrame, timezone: str)
    @classmethod from_series(series, timezone, expected_interval_s, exclude_mask)
    sensor_id, timezone, frame (copy), dates, __len__
    complete_days(min_coverage) -> DailyWeather; between(start_date, end_date) -> DailyWeather
    # columns temp_min, temp_mean, temp_max, rh_min, rh_mean, rh_max, temp_n_samples,
    # rh_n_samples, temp_coverage, rh_coverage, n_samples (= temp), coverage (= temp)

# sivin.core.season
@dataclass(frozen=True, slots=True, order=True) class MonthDay: month, day; in_year(year)
@dataclass(frozen=True, slots=True) class Season: start, end
    vegetation(), huglin(), month(m); dates(year) -> (date, date); n_days(year); contains(d)

# sivin.analytics.base
@dataclass(frozen=True, slots=True) class IndexContext: sensor_id, year, daily, series,
    latitude_deg, elevation_m, timezone, min_daily_coverage, min_season_coverage, exclude_mask
    # all required; consistency of sensor_id/timezone with daily/series is checked
@dataclass(frozen=True) class IndexResult: index_id, sensor_id, year, value, unit, coverage,
    complete, classification=None, daily=None, details={}, estimated=False
class IndexParams(BaseModel)                       # frozen, extra="forbid"
class ClimateIndex[P: IndexParams](ABC):
    index_id: ClassVar[str]; unit: ClassVar[str]
    params_model: ClassVar[type[IndexParams]]      # required; checked at registration
    def __init__(self, params: P | None = None); params: P
    @abstractmethod compute(self, ctx: IndexContext) -> IndexResult
    _season_days(self, ctx, season) -> SeasonDays  # complete days + coverage + complete
class IndexRegistry: register (class decorator; also register("id")), create(index_id, params),
    get(index_id), ids(), __contains__, __len__
index_registry: IndexRegistry

# sivin.core.defaults (no pandas)
DEFAULT_TIMEZONE, LEGACY_SAMPLING_INTERVAL_S, DEFAULT_MIN_DAILY_COVERAGE,
DEFAULT_MIN_SEASON_COVERAGE
# sivin.core/__init__ re-exports nothing: import from the submodules.

# sivin.config / sivin.paths / sivin.logging_setup
SivinConfig(paths: PathsConfig, time: TimeConfig, analytics: AnalyticsConfig); .default()
load_config(path: Path) -> SivinConfig            # raises ConfigError naming key paths
ProjectPaths(root); .discover(start=None); .resolve(relative)
setup_logging(level="INFO")
```

## How it was verified

Round 3 (same venv):

- `make lint` → `All checks passed!`, `32 files already formatted`.
- `make type` → `Success: no issues found in 20 source files`.
- `make test` → `190 passed`.
- `make cov` → `TOTAL 843 0 186 0 100%`, `Total coverage: 100.00%`.
- Reviewer probe `r2/fb_min.py` (73 phases × every drop of ≤ 3 of 12 samples):
  `patterns with silent wrong rows, by #dropped: {}` (was 8 / 482 for 2 / 3 drops).
  `r2/fb_order.py`: input sorted by local time is converted with the repeated hour flagged
  `unresolved`. Newest-first input raises `ValueError` ("oldest first").
- New regression tests: the `01:58:20 / 02:29:35 / 03:00:00` case, newest-first input
  raising, a duplicated row in the repeated hour, `NaT` rejected before duplicate handling in
  `from_records`, `bool` mask and out-of-range latitude in `IndexContext`.

Round 2 (all commands in `/home/user/wt/wp-0.1`, same venv; ruff 0.16.10, mypy 2.4.0):

- `make lint` → `All checks passed!`, `32 files already formatted`.
- `make type` → `Success: no issues found in 20 source files`.
- `make test` → `181 passed`.
- `make cov` → `TOTAL 825 0 178 0 100%`, `Required test coverage of 85% reached. Total
  coverage: 100.00%`.
- The reviewer's probes in `/tmp/claude-0/review-0.1/` re-run: `tz_probe.py` and
  `tz_probe2.py` give correct, strictly increasing UTC for all fall-back phase offsets, for every
  single missing sample (1800 s and 1825 s) and for `NaT` in the repeated hour. The only wrong
  instant left is the 2026 group of the multi-year probe, which has a single sample with equal
  evidence for both offsets; it is now flagged `unresolved` and no longer affects 2025. The
  spring collision rows come back as `NaT` + `unresolved`, and `from_records` keeps all 15 rows
  of the multi-year probe (it dropped 2 before). `daily_probe.py` gives `temp_max = 30.0` with
  RH missing. `idx_probe.py` now stops at `IndexContext(...)` because the three thresholds are
  required. `ms_probe.py` stops at the `±inf` value with `SchemaError`, and `ids_probe.py`
  rejects the Arabic-Indic serial. All three are intended changes.
- `.gitignore`: `tests/test_gitignore.py` asserts with `git check-ignore --no-index` that
  `web/public/data/manifest.json`, `web/src/data/DataClient.ts`,
  `docs/wp_log/img/WP-3.1-desktop.png`, fixtures, `sensors/sensors.geojson` and
  `config/sivin.yaml` are versioned and that `/data/`, `/site/`, `/vystupy/`, root exports,
  `.env`, `.venv/`, `web/node_modules/` and `web/dist/` are ignored (skipped without git).
- `sivin.cli` import does not load pandas (`tests/test_config.py`, subprocess check).

Round 1, with a venv created by
`uv venv --seed --python 3.12 .venv && uv pip install -e ".[dev,ingest,viz]"`
(pandas 3.0.6, numpy 2.5.3, pydantic 2.13.5, typer 0.27.2, ruff 0.16.10, mypy 2.4.0).

- `make lint` → `All checks passed!`, `30 files already formatted`.
- `make type` → `Success: no issues found in 19 source files` (mypy `--strict`, pydantic plugin).
- `make test` → `132 passed`.
- `make cov` → `TOTAL 710 0 122 0 100%`, `Required test coverage of 85% reached. Total
  coverage: 100.00%` (branch coverage on; `cli.py` included and also at 100 %).
- Clean install check: `python3.12 -m venv <scratch>/cleanvenv && pip install -e ".[dev]"`
  (plain pip, not uv) → exit 0; `make lint type test PY=<scratch>/cleanvenv/bin/python` →
  green, 132 passed; `sivin --version` → `sivin 0.1.0`. This is the same invocation CI uses
  (`make ... PY=python`).
- `pre-commit run --files <all files of this WP>` → all hooks passed after
  `trailing-whitespace` stripped trailing spaces inherited from the old `.gitignore` template.
- `.gitignore` checked with `git check-ignore --no-index` on sample paths: `tests/fixtures/**`
  (csv, xlsx, png, log), `docs/img/*.png`, `config/*.png`, `src/**/data/*.csv` and
  `web/src/lib/*` are tracked; `/data/`, `/site/`, root `*.csv`/`*.xlsx`, `.env`, `.venv/`,
  `web/node_modules/`, `web/dist/` are ignored.
- The 2026 Europe/Prague transitions (2026-03-29 01:00 UTC, 2026-10-25 01:00 UTC) are computed
  with `zoneinfo` inside `tests/core/test_timeutil.py`, not taken from the brief.
- `git diff 61e059f --stat` on the legacy scripts and YAML files: no changes.

## What did not work / what was not verified

- **The CI workflow has not run on GitHub** (nothing was pushed). Its steps were reproduced
  locally (clean venv, `pip install -e ".[dev]"`, `make lint type test PY=...`).
- `make install` itself was not run (the venv was created with uv as instructed); its pip
  command was exercised in the clean-install check above.
- The source time zone of the provider's exports is still an assumption
  (`time.source_timezone: Europe/Prague`, owner question Q2). `LocalTimeConverter` is tested on
  synthetic timestamps only; no real export was available.
- pre-commit was not run on the legacy files (they are excluded on purpose).
- No real measurement data were used anywhere; all test values are synthetic and hand-computed.

## Decisions and deviations from the brief

1. **pandas ≥ 3.0.** pandas 3 changes defaults that matter for the contract (timestamps parse
   to `datetime64[us]`, strings default to the `str` dtype, copy-on-write). Supporting both 2.x
   and 3.x would double the dtype handling, so the lower bound is 3.0 (installed: 3.0.6). The
   constructor of `MeasurementSeries` therefore rejects `datetime64[us, UTC]`; `from_records`
   normalises to `ns` as required by plan §2.5.
2. **Every ambiguous fall-back time is marked suspect**, also when its offset was resolved.
   Plan WP-1.2 says "ambiguous → `TIMESTAMP_SUSPECT`"; the brief only asked to mark the cases
   where inference fails. Resolution rule (round 3; pandas' `ambiguous="infer"` is no longer
   used): the input must be in source order, oldest first (validated: decreasing unambiguous
   rows raise `ValueError`); ambiguous rows are grouped per local date, so every transition is
   resolved on its own; (a) exactly one backward jump of the wall clock (`NaT` skipped, a
   sample *strictly* earlier than its predecessor) is the switch point, and is the **only**
   rule that marks rows resolved; (b) without a jump, the split that maximises the smallest
   step between consecutive UTC instants (including the nearest unambiguous neighbours) is
   used as a best guess if it is strictly increasing and unique, (c) otherwise standard time;
   both (b) and (c) flag the group in `ConversionResult.unresolved` with a warning. Equal
   consecutive wall-clock values are duplicates, not a jump: both copies get the same instant
   and become `NaT` + `unresolved` by the collision rule. Callers drop `NaT` rows before
   `from_records`, which rejects `NaT` before reducing duplicates.
3. **Nonexistent spring-forward times** are read with the UTC offset in force before the
   transition (PEP 495 `fold=0`), i.e. shifted forward by the length of the gap
   (02:15 → 03:15 CEST = 01:15 UTC). pandas' `nonexistent="shift_forward"` would collapse all of
   them to 03:00. **No silent duplicates** (round 2): any suspect row whose UTC instant equals
   another row's is returned as `NaT` and flagged `unresolved` (warning logged); duplicates
   between two ordinary rows come from the source and are left to `InputValidator`. Samples in
   the gap usually mean the configured source zone is wrong (Q2). Non-colliding shifted samples
   can still be later than a genuine 03:00 sample that follows them; `from_records` sorts.
4. **Additions to the briefed API** (only additions): `IndexContext.min_daily_coverage`,
   `.min_season_coverage`, `.exclude_mask` (required since round 2, so a context factory must
   pass the configuration values; `__post_init__` checks that `sensor_id`/`timezone` match the
   carried `daily`/`series` and that the thresholds are valid); `ConversionResult.unresolved`;
   `DailyWeather` columns `temp_n_samples`, `rh_n_samples`, `temp_coverage`, `rh_coverage`;
   `sivin.core.defaults`; `AnalyticsConfig.min_season_coverage`
   (default 0.9, project default to be tuned) to decide `IndexResult.complete`; `SeasonDays`
   (return type of the protected helper); `IndexParams` base model; `IndexRegistry.get`/`__len__`;
   `QcFlag.all_bits()`; `excluded()` (vectorised `is_excluded`); `LocalTimeConverter.timezone`
   and `.day_length_s()`; `DailyWeather.timezone`/`.dates`; `Season.n_days()`;
   `MonthDay.in_year()`; `ProjectRootNotFoundError`; `ConfigError`.
5. **Index parameters**: the parameter model is the class variable `params_model` and the class
   is generic, `ClimateIndex[P]`, so `self.params` is precisely typed under mypy `--strict`.
   A nested class named `Params` cannot be used as the generic argument of its own outer class.
   Since round 2 `params_model` has no default: registration and instantiation fail with a
   clear `TypeError` when it is missing (`IndexParams` itself for an index without parameters).
6. **Registry decorator**: the key is always the class's `index_id` (brief), but the form shown
   in plan §1.2, `@index_registry.register("huglin")`, is accepted too and must match it.
7. **`DailyWeather` aggregates temperature and humidity independently** (round 2, was: both
   required). A value is valid when present and its row is not excluded by the mask; each
   variable has its own count and coverage (`temp_n_samples`/`temp_coverage`,
   `rh_n_samples`/`rh_coverage`). `n_samples` and `coverage` equal the temperature columns,
   because nearly all indices are temperature-based; `coverage` is the site-contract column and
   the one `complete_days()` uses. All days from the first to the last sample are rows; days
   without valid values have zero counts and coverage and `NaN` aggregates. Means are
   arithmetic sample means. The constructor validates dtypes, non-negative counts, coverage
   within 0-1 and the equality of the alias columns.
8. **`MeasurementSeries`** accepts a `sensor_id` column in its constructor only if every row
   equals the series' id (then drops it), so `to_frame()` output round-trips. `from_records`
   does not set `MISSING` for `NaN` values; that is left to QC (WP-1.5). Duplicate timestamps
   with different values are reduced to the last row with a warning (documented); reconciling
   conflicts belongs to WP-1.2/WP-1.4. Round 2: `±inf` is rejected, column labels are plain
   `str`, unparsable timestamp `Series` raise `SchemaError`.
9. **`.gitignore`**: besides the briefed rules, `lib/`/`lib64/` (Python template) are anchored to
   the root so that `web/src/lib/` is not ignored, root-level images/videos (legacy outputs)
   are ignored, and `!/tests/fixtures/**` re-includes fixtures matched by any global rule.
10. **Tests outside the plan's Files list**: `tests/analytics/test_base.py` and
    `tests/test_{config,paths,cli}.py` (plan lists only `tests/core/**`; the brief allows them).
11. CI also runs on pushes to `main` (brief) in addition to `wp/**`, `claude/**` and PRs (plan).
12. **Round 2 tooling:** `ruff>=0.16,<0.17` (matches the pre-commit pin v0.16.10) and
    `mypy>=2.4,<3`. pytest keeps warnings as errors, except `DeprecationWarning` /
    `PendingDeprecationWarning` raised inside third-party packages (runtime deps have no upper
    bound, so these would make CI depend on upstream releases); deprecations attributed to
    `sivin` code still fail.
13. **`SensorId`** accepts ASCII digits only and the browser copy suffix
    (`... (1).xlsx`). `sivin.core` re-exports nothing any more, so `sivin.config` (and
    `sivin --version`) do not import pandas.

## Out of scope

- `README.md` still documents `pip install -r requirements.txt` and "Python 3.8+"; to be
  rewritten in WP-5.2.
- `CLAUDE.md` (line 30) and `CONTRIBUTING.md` (line 14) still say that before WP-0.1 only
  `requirements.txt` exists; the remark becomes obsolete after the merge.
- WP-1.4 / WP-4.1: the briefed `/data/` rule also matches `data/raw/...` on the `data` branch;
  that branch needs its own `.gitignore` or `git add -f`.
- WP-1.2: parsers must pass rows to `LocalTimeConverter.to_utc` in source order, oldest
  first (reverse a newest-first export, never sort by local time), and drop/report `NaT`
  rows before `from_records`.
- WP-1.2 / WP-1.4: store readers and parsers must build series through `from_records`
  (pandas 3 reads `datetime64[us]`), and resolve conflicting duplicate timestamps before it.
- Proposal: QualityCheck (WP-1.5) and ExportParser (WP-1.2) registries will repeat the
  `IndexRegistry` logic. A small generic `Registry[T]` in `sivin.core` could serve all three;
  not done here to keep the briefed API.

## Open questions for the owner

1. Q2 (plan §0.6) still decides `time.source_timezone`; the default `Europe/Prague` is an
   assumption.
2. `analytics.min_daily_coverage = 0.9` and `analytics.min_season_coverage = 0.9` are project
   defaults without literature backing; confirm or tune once real data are in.
3. Should resolved (inferred) ambiguous times really carry `TIMESTAMP_SUSPECT` (decision 2), or
   only those that could not be inferred?
4. Is requiring pandas ≥ 3.0 acceptable (decision 1)?
5. `qc` is one bit field per row (frozen contract §2.5), so an RH-only QC finding also
   excludes that row's temperature. Should the contract get per-variable flags before WP-1.5?
   (Raised by the reviewer.)
6. (Answered in round 3: groups without a single clock jump are always `unresolved`; the
   spacing heuristic only chooses the guessed value.)

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent Claude reviewer subagent (did not write this code). Probe scripts were run
outside the repository; nothing in the worktree except this file was changed.

### Gates observed by the reviewer

- `make lint` → `All checks passed!`, `30 files already formatted`.
- `make type` → `Success: no issues found in 19 source files` (mypy strict, pydantic plugin). No
  `type: ignore` or `noqa` in `src/`; `Any` only at the YAML boundary (`config.py`) and in
  `ClimateIndex[Any]` / `Mapping[str, Any]` of the registry (justified).
- `make test` → `132 passed`.
- `make cov` → `TOTAL 710 0 122 0 100%`, threshold 85 % reached.
- CI simulation: `git archive HEAD` into a scratch dir, fresh `python3.12 -m venv`, plain
  `pip install -e ".[dev]"`, `make lint type test PY=python` → green, 132 passed;
  `sivin --version` → `sivin 0.1.0`.
- Scope: `git diff claude/funny-sagan-jge9is...HEAD --stat` touches only WP-0.1 Files scope plus
  the worker's own tests (allowed by §0.3/2); legacy scripts and YAML files unchanged.
- `.gitignore` (`git check-ignore --no-index -v`): ignored: `data/raw/x/2026.csv`, `vystupy/grafy/a.png`,
  `data.xlsx`, `site/data/manifest.json`, `.env`, `chrome_driver.env`, root `MeteoData_*.csv`;
  tracked: `tests/fixtures/exports/a.xlsx`, `tests/fixtures/a.log`, `web/src/lib/x.ts`,
  `docs/img/a.png`, `src/sivin/lib/x.py`, `sensors/sensors.geojson`, `config/sivin.yaml`.
- `config/sivin.yaml` loads to exactly `SivinConfig.default()`; unknown keys are rejected with the
  key path (`analytics.min_cov: Extra inputs are not permitted`).
- Europe/Prague 2025/2026 transitions re-derived with `zoneinfo`: 2025-03-30 01:00 UTC,
  2025-10-26 01:00 UTC, 2026-03-29 01:00 UTC, 2026-10-25 01:00 UTC.

Verified as correct: `SensorId.parse` on all three §2.4 spellings, double space, tabs, POSIX and
Windows paths, upper-case extension, export name without label; `to_utc` on regular 1825 s data
across the 2026 fall-back for 7 different phase offsets (all correct, strictly increasing, 4
suspect), 1800 s and 3600 s sampling; `DailyWeather` on 23 h / 25 h days (coverage 1.0 with 23 /
25 hourly samples), local-midnight assignment in summer and winter, all-excluded and all-NaN
days, `STEP`/`NEIGHBOR_OUTLIER`/`TIMESTAMP_SUSPECT` not excluding; `MeasurementSeries`
immutability (input arrays, `.frame`, `.timestamps`, constructor input — no leaks), `with_flags`
OR semantics and rejection of negative / unknown / huge bits, `between` inclusive and rejecting
naive bounds and `NaT`, `to_frame()` round trip; `_season_days` coverage (163/183 = 0.8907 for a
20-day gap in the Huglin period, hand-computed).

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `src/sivin/core/timeutil.py:110-119` | Ambiguous-time fallback is global: if pandas cannot infer **one** fall-back cluster, **every** ambiguous time of the whole input is read as standard time. Reproduced: (a) input spanning 2025 (complete repeated hour, 1800 s) and 2026 (one sample in the repeated hour) → the correctly inferable 2025 rows `02:00`/`02:30` CEST map to the same UTC instants as the CET rows (2 exact duplicates, result not monotonic); `MeasurementSeries.from_records` then silently drops 2 real samples (warning only). (b) single year, 1825 s sampling, one sample missing inside the repeated hour → 1–2 samples silently 3600 s late while the output stays monotonic, so no later check can see it. (c) one `NaT` inside the repeated hour has the same effect. Fix: resolve each transition cluster separately (group ambiguous runs by local date); within a cluster use the backward jump of the wall clock as the switch point; when a cluster has no jump, pick the offset that keeps UTC strictly increasing w.r.t. the neighbouring unambiguous samples; never return duplicate UTC instants silently (raise or report). Add tests for (a)–(c) and for 1825 s data with a missing sample. | fixed: per-date groups, clock-jump switch point, spacing rule, `unresolved` mask, no silent duplicates; tests for multi-year, missing sample, NaT |
| major | `src/sivin/core/daily.py:128-130` | A sample counts only if **both** `temp_c` and `rh_pct` are present (deviation 7), so a missing RH value discards a valid temperature. Reproduced: `temp_c=[1, 30]`, `rh_pct=[50, NaN]` → `temp_max = 1.0` instead of 30.0, `n_samples = 1`. Most indices of §3.1/§3.2 use temperature only; an RH channel failure would make them lose whole days and `complete` flags. Fix: aggregate each variable over its own valid (not excluded, not NaN) samples; define `n_samples`/`coverage` explicitly (e.g. on temperature, which all thermal indices use, or add `n_samples_rh`/`coverage_rh` while keeping `coverage` for the site contract) and document it; add a hand-computed test. Related owner question: `qc` is one bit field per row (frozen contract §2.5), so an RH-only QC finding also excludes the temperature — worth raising before WP-1.5. | fixed: T and RH aggregated independently; `temp_/rh_n_samples`, `temp_/rh_coverage`, `coverage` = temperature; test added |
| minor | `src/sivin/core/timeutil.py:121-123` | Nonexistent spring-forward times read with `fold=0` can collide with genuine post-gap samples: local `02:00, 02:15, 03:00, 03:15` on 2026-03-29 → UTC `01:00, 01:15, 01:00, 01:15` (duplicates; `from_records` then drops two). The docstring says spacing is preserved but not that duplicates can occur. Suggest: report non-monotonic / duplicate output in `ConversionResult` (or raise), and document that samples inside the gap mean the source zone assumption (Q2) is probably wrong. | fixed: colliding suspect rows become `NaT` + `unresolved`, documented; test added |
| minor | `src/sivin/core/schema.py:164-171` | `from_records` resolves duplicate timestamps with **different** values by keeping the last row, with only a log warning (reproduced: two rows at the same instant with 1.0 and 2.0 → 2.0 kept). This hides both the DST bugs above and real conflicts that §2.7 assigns to `InputValidator`. Suggest: drop only fully identical rows; raise `SchemaError` (or return the conflicts) for conflicting duplicates and leave the policy to WP-1.2/WP-1.4. | accepted: keep last + warning, now documented; conflict resolution belongs to WP-1.2/WP-1.4 |
| minor | `src/sivin/core/ids.py:21,27` | `\d` matches any Unicode digit: `SensorId("٧٧٦٧٨٢٧١")` is accepted and `parse` returns a non-ASCII serial. Use `[0-9]` or `re.ASCII` (also for `name.isdigit()` at line 101). | fixed: ASCII `[0-9]` only, also for the legacy check; tests added |
| minor | `src/sivin/core/ids.py:23-33` | Browser-renamed downloads are rejected: `MeteoData_8615620 77678271 (VUT)_20260301_223857 (1).xlsx` → `ValueError`. Chrome appends ` (1)` when the legacy `chrome_driver.py` downloads into the same folder twice. Suggest accepting an optional ` \(\d+\)` before the extension (with a test), or documenting that callers strip it. | fixed: optional ` (n)` browser suffix accepted; tests added |
| minor | `src/sivin/core/daily.py:219-230` | The public `DailyWeather` constructor validates only column names and index: string columns, `coverage = 5.0` and negative `n_samples` are accepted (reproduced). Validate dtypes (`float64`, `int64`), `0 <= coverage <= 1`, `n_samples >= 0`. | fixed: dtypes, counts >= 0, coverage 0-1, alias equality validated; tests added |
| minor | `src/sivin/analytics/base.py:56-92` | `IndexContext` repeats `sensor_id` and `timezone` that `daily`/`series` already carry and does not check consistency (reproduced: context with sensor `11111111`, zone `UTC` and Prague daily data of `77678271` is accepted). Its defaults `0.9/0.9/311` duplicate the config defaults, so a factory that forgets to pass the configuration silently ignores `config/sivin.yaml`. Suggest: `__post_init__` consistency checks and no defaults for the three config-driven fields (or derive `sensor_id`/`timezone` from `daily`). | fixed: thresholds required, `__post_init__` checks sensor/timezone/thresholds/mask; tests added |
| minor | `src/sivin/analytics/base.py:208` | `params_model` defaults to the empty `IndexParams`; a subclass that forgets to set it registers fine and `create("y", {"base": 5})` fails with a confusing "extra inputs not permitted". Make `_add` require that `params_model` is overridden (a proper subclass of `IndexParams`). | fixed: no default; `TypeError` at registration and instantiation; test added |
| minor | `src/sivin/config.py:17` | Layering inversion: the configuration module imports `sivin.analytics.base` (and through it pandas, `daily`, `schema`) only for two constants, so `sivin --version` / `config show` import the whole analytics stack. Move `DEFAULT_MIN_*` to `config.py` (or `sivin.core`) and let analytics depend on them, not the reverse. | fixed: constants in `sivin.core.defaults`, `sivin.core` re-exports nothing; test that `sivin.cli` does not load pandas |
| minor | `pyproject.toml:31-32,89` | Dev tools are unbounded (`ruff>=0.6`, `mypy>=1.11`) while pre-commit pins ruff `v0.16.10`, and `filterwarnings = ["error"]` turns any new deprecation into a failure; with no lock file CI can turn red on a new release without a code change, and local pre-commit and CI may disagree. Suggest bounding ruff/mypy to the tested series (e.g. `ruff>=0.16,<0.17`, `mypy>=2.4,<3`) to match pre-commit. pandas `>=3.0`: see deviations. | fixed: `ruff>=0.16,<0.17`, `mypy>=2.4,<3`; third-party deprecations no longer errors (decision 12) |
| minor | `.gitignore:213` | `/data/` (briefed rule) also ignores `data/raw/...` on the `data` branch, which is where §2.5 puts the store. WP-1.4 / WP-4.1 must `git add -f` or the `data` branch needs its own `.gitignore`. Not a defect of this WP; note it in the WP-1.4 brief. | accepted: note for WP-1.4/WP-4.1 (data branch will use its own ignore rules or `git add -f`) |
| nit | `src/sivin/config.py:114` | `exclude_mask: true` is accepted as `1` (pydantic lax mode). Use `StrictInt`. | fixed: `StrictInt`; test with `true` added |
| nit | `src/sivin/core/schema.py:376` | `±inf` is accepted as a temperature/RH value; the contract only knows `NaN` = missing. Reject or convert to `NaN`. | fixed: `±inf` rejected with `SchemaError`; tests added |
| nit | `src/sivin/core/schema.py:395-398` | A `Series` of strings with mixed UTC offsets raises pandas' bare `ValueError` instead of `SchemaError`, unlike the list path. | fixed: wrapped in `SchemaError`; test added |
| nit | `src/sivin/core/schema.py:151-162` | Frames built by `from_records` carry `Column` enum members as column labels, frames passed to the constructor keep plain `str` labels; harmless (StrEnum) but inconsistent — normalise labels to `str` in `_validated_copy`. | fixed: labels normalised to `str` (also `to_frame`); test added |

### Deviations assessment

1. **pandas ≥ 3.0** — agree. Verified that a clean pip install resolves (pandas 3.0.6,
   pandas-stubs 3.0.5) and that the ns contract is enforced. Risk is low for a Python ≥ 3.12-only
   project; the cost is that every reader of `datetime64[us]` data (CSV store, parsers) must go
   through `from_records` — say so in the WP-1.2/WP-1.4 briefs.
2. **All ambiguous times suspect** — agree; `TIMESTAMP_SUSPECT` does not exclude by default, so
   it costs nothing and is honest. The fallback behaviour itself is a major finding above.
3. **Nonexistent times with `fold=0`** — agree it is better than collapsing to 03:00, but it can
   still create duplicates (minor finding).
4. **API additions** — agree, all are small and useful; see the minor finding on `IndexContext`
   defaults duplicating the configuration.
5. **Generic `ClimateIndex[P]` + `params_model`** — agree; precise typing under mypy strict is
   worth it. Add the `params_model` registration check.
6. **Both decorator forms** — agree.
7. **Valid sample = not excluded and both T and RH present** — disagree (major finding).
8. **`sensor_id` column accepted if equal; no `MISSING` from `from_records`** — agree.
9. **`.gitignore` details** — agree; verified with `git check-ignore`.
10. **Tests outside the Files list** — agree (§0.3/2 allows the worker's own tests).
11. **CI also on `main`** — agree.

### Tests

Tests compare with hand-computed values (aggregates, coverage on 23/24/25 h days, transition
instants derived from `zoneinfo`) and are not tautological. Missing: fall-back with a missing
sample or `NaT` in the repeated hour, multi-year input, the spring-forward collision, a sample
with valid temperature but missing RH, the browser ` (1)` file name.

### Round 2

Verdict: CHANGES_REQUESTED (round 2)

Reviewer: independent Claude reviewer subagent (did not write this code). Reviewed commits
`a0199fb..bcde7d9`. Probe scripts were run outside the repository
(`/tmp/claude-0/review-0.1/` round 1, `/tmp/claude-0/review-0.1/r2/` round 2); nothing in the
worktree except this file was changed.

#### Gates observed by the reviewer

- `make lint` → `All checks passed!`, `32 files already formatted`.
- `make type` → `Success: no issues found in 20 source files`. Still no `type: ignore`/`noqa` in
  `src/`; `Any` only at the YAML boundary and in the registry (unchanged, justified).
- `make test` → `181 passed`.
- `make cov` → `TOTAL 825 0 178 0 100%`, threshold 85 % reached.
- Scope: round 2 touches only WP-0.1 files (`docs/`, `pyproject.toml`, `src/sivin/{config,core/*,analytics/base}.py`,
  own tests, new `tests/test_gitignore.py`).

#### Round 1 findings re-verified

All six round 1 probe scripts were re-run unchanged (adapted only where the API now requires the
thresholds).

- **major timeutil (fixed — partly, see R2-1/R2-2):** (a) 2025 + 2026 input: the 2025 rows are now
  correct and unique; the single 2026 sample is flagged `unresolved` (warning). (b) 1825 s and
  1800 s data with **one** missing sample in the repeated hour, every position and 7 phases:
  all correct. Exhaustive check over 73 phases × every drop of ≤ 1 sample (876 patterns): 0 wrong.
  (c) `NaT` inside the repeated hour: correct, `NaT` stays `NaT`. Multi-year 2021-09 → 2026-12
  (5 fall-backs), 1825 s ± 20 s jitter, 30 random runs without gaps: 0 wrong, 0 unresolved.
  With gaps the spacing rule fails silently (R2-1).
- **major daily (fixed):** `temp_c=[1, 30]`, `rh_pct=[50, NaN]` → `temp_max = 30.0`; per-variable
  counts/coverage present; `coverage == temp_coverage` enforced by the constructor.
- **minor spring-forward collision (fixed):** `02:00, 02:15, 03:00, 03:15` → the two colliding
  suspect rows are `NaT` + `unresolved`, warning logged.
- **minor ids Unicode digits / ` (1)` suffix (fixed):** `٧٧٦٧٨٢٧١` rejected by `parse` and the
  constructor; `..._223857 (1).xlsx` → `77678271`.
- **minor `DailyWeather` validation (fixed):** wrong columns, `coverage = 5.0`, float counts and a
  diverging alias column are rejected.
- **minor `IndexContext` (fixed):** other sensor, other zone (also the alias `Europe/Bratislava`),
  `NaN`/`1.5` thresholds, negative / unknown mask bits are rejected (see R2-5 for leftovers).
- **minor `params_model` (fixed):** missing `params_model` → clear `TypeError` at `register` and
  at instantiation.
- **minor config layering (fixed):** `import sivin.config, sivin.cli` does not load pandas;
  `sivin.core.flags` alone neither.
- **minor dev-tool bounds (fixed):** `ruff>=0.16,<0.17`, `mypy>=2.4,<3`. The new
  `filterwarnings` keeps deprecations attributed to `sivin` as errors — reasonable.
- **nits (fixed):** `exclude_mask: true` rejected (`StrictInt`); `±inf` → `SchemaError`; mixed
  offsets in a `Series` → `SchemaError`; column labels are `str` in `frame` and `to_frame()`.

#### Accepted items

- **`from_records` keeps the last duplicate with a warning — agree.** Since round 2, duplicates
  created by the DST handling become `NaT` in `to_utc` instead of reaching `from_records`, so the
  remaining duplicates come from the source (overlapping exports), which plan §2.7 assigns to
  `InputValidator`/the store. The behaviour is now documented in the docstring. Condition: the
  WP-1.2 and WP-1.4 briefs must say that conflicting duplicates are reconciled *before*
  `from_records`. See R2-4 for an interaction with `NaT`.
- **`/data/` ignore rule — agree.** It is the briefed rule; the effect on the `data` branch is a
  WP-1.4/WP-4.1 concern and is recorded under *Out of scope*. `tests/test_gitignore.py` pins the
  rules (19 cases, pass).

#### Findings (round 2)

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `src/sivin/core/timeutil.py:303-336` (rule 2 of `switch_point`) | **R2-1. The spacing heuristic resolves fall-back groups silently wrong, and contradicts the documented contract.** The class docstring (l. 59-61) and `ConversionResult.unresolved` say a group *without exactly one clock jump* is read as standard time and marked `unresolved`; the code instead applies rule 2 (max of the smallest step) and returns `unresolved=False`. Reproduced on 2026-10-25, 1825 s sampling: local `01:58:20, 02:29:35, 03:00:00` (two samples missing, i.e. a ~1 h gap) → `02:29:35` returned as `00:29:35 UTC` (summer) instead of `01:29:35 UTC`, `suspect=True, unresolved=False`, output monotonic, so no later check can see it (the scores differ by only 50 s: 31:15 vs 30:25 min). Second case: `02:01:40` (summer) and `02:32:55` (standard) with neighbours on both sides → both read as summer, one sample 1 h early. Exhaustive count (73 phases × all drops of ≤ 3 of 12 samples): 0/876 wrong with one drop, **8/4818** with two, **482/16056** with three; multi-year random loss 5 % / 20 % / 50 %: 1 / 20 / 54 silently wrong rows over 30 runs × 5 years. This is the same failure class as round 1 major (b), only needing a longer gap. A margin on the score does not fix it (0.5 × 1825 s margin still leaves 146/16056). Verified that the clock-jump rule alone (rule 1) is never wrong on chronological input (0 silent in all patterns). Impact is limited (one or two samples per transition, still `suspect`, local date unchanged so daily aggregates are unaffected), but it breaks sub-daily alignment and the meaning of `unresolved`. Fix: keep the rule-2 guess if wanted, but **mark those rows `unresolved`** (and log), and align the class and `ConversionResult` docstrings and `docs/architecture.md`; add the two examples above as tests. This also answers open question 6. | fixed: only the clock-jump rule resolves; spacing and fallback guesses are `unresolved`; docstrings and architecture aligned; both examples covered (`r2/fb_min.py`: 0 silent wrong) |
| major | `src/sivin/core/timeutil.py:54,104,309` | **R2-2. Input order is assumed but not checked; newest-first or locally sorted input is resolved silently wrong.** "Recorded order" is ambiguous for an export listed newest first (format not verified, Q1/Q2; the legacy `one_variable_plot.py:57` and `two_variable_plot.py:42` sort after reading, so ascending order is not guaranteed). Reproduced: complete 1825 s data across 2026-10-25 reversed (phase 1625 s) → one "backward jump" is found in the reversed sequence and the split is inverted: `02:29:35` → `00:29:35 UTC` (true `01:29:35`), `02:28:45` → `01:28:45` (true `00:28:45`), all `unresolved=False`. 20 of 365 phases wrong with complete data; with ≤ 2 dropped samples 1851/5767 patterns silently wrong for reversed input and 1395/5767 for input sorted by local wall-clock time (the natural thing a parser might do). Fix: document "chronological recorded order, oldest first; do not sort before conversion" and validate it: the non-`NaT`, non-ambiguous rows must be strictly increasing (wall clock or UTC); otherwise raise `ValueError` (or reverse a fully descending input explicitly). Add tests for reversed and sorted input. **API impact:** `to_utc` gains a documented `ValueError`; WP-1.2 parsers must pass rows oldest-first. | fixed: contract "source order, oldest first" documented (class docstring, architecture.md) and validated with `ValueError`; tests for newest-first input |
| minor | `src/sivin/core/timeutil.py:309` | **R2-3.** An exactly repeated wall-clock value (`<=`) counts as a clock jump. A duplicated export row inside the repeated hour (complete 1825 s data, row `02:31:15` twice) → two "jumps" → the whole group (5 rows) is read as standard time and `unresolved`, and both copies of the duplicate become `NaT` (the sample is lost although its first copy was unambiguous). Combined with a missing pass it can resolve silently wrong (only "jump" is the duplicate). Suggest: treat equal consecutive wall-clock values as a duplicate, not a jump (`<`), and leave duplicates to the collision check / `InputValidator`; add a test. | fixed: strict `<`; equal consecutive values are duplicates (same instant, then `NaT` + `unresolved` by the collision rule), documented; test added |
| minor | `src/sivin/core/schema.py:167` + `timeutil.py` `ConversionResult` | **R2-4.** `to_utc` now returns `NaT` rows, and `from_records` rejects `NaT` with `SchemaError` — correct — but first logs `dropped 1 row(s) with a duplicate timestamp` because several `NaT` count as duplicates of each other. Nothing in `ConversionResult` tells the caller to drop the `NaT` rows before building the series. Suggest: check for `NaT` before the duplicate reduction in `from_records`, and state in `ConversionResult.timestamps_utc` that callers drop (and report) `NaT` rows; mention it in the WP-1.2 brief. | fixed: `from_records` rejects `NaT` before duplicate handling; `to_utc`, `ConversionResult` and `from_records` docstrings tell callers to drop `NaT`/handle `unresolved`; test added |
| nit | `src/sivin/analytics/base.py:84,89` | **R2-5.** `IndexContext` accepts `exclude_mask=True` (bool, unlike `AnalyticsConfig` which is `StrictInt`) and any `latitude_deg` (e.g. `200.0`); Huglin's latitude coefficient will rely on it. Suggest `-90 <= latitude_deg <= 90` and rejecting `bool`. | fixed: `bool` mask and latitude outside -90..90 rejected; tests added |
| nit | `src/sivin/config.py:17-22` | **R2-6.** `DEFAULT_TIMEZONE` and `LEGACY_SAMPLING_INTERVAL_S` moved to `sivin.core.defaults`; `from sivin.config import DEFAULT_TIMEZONE` still runs but fails mypy strict (`does not explicitly export attribute`). All parallel worktrees branch from `bcde7d9`, so nobody depends on the old location; noting it only so the hand-off API (which lists `sivin.core.defaults`) stays the single source. | accepted: no compatibility shim; nobody depends on the old location, `sivin.core.defaults` is the single source |

#### Round 2 design changes (part c)

- **`DailyWeather` per-variable columns:** correct and hand-checkable; no regression found
  (23 h / 25 h days, all-excluded and all-`NaN` days, RH-only days give `temp_coverage = 0`
  and valid `rh_*`). The `n_samples`/`coverage` aliases duplicate the temperature columns, but
  the constructor enforces equality and the site contract (§2.6) only needs `coverage`, so this
  is acceptable. `complete_days()` filters on temperature coverage only; an RH-based index
  (WP-2.x disease models) has to filter on `rh_coverage` itself — worth a sentence in those
  briefs, not a defect.
- **Required `IndexContext` thresholds:** good; forgetting the configuration is now a
  `TypeError` instead of a silent default. Consistency checks work (see re-verification).
- **`sivin.core.defaults`:** right layering (config → core.defaults ← analytics), light import
  verified. The values are labelled as project defaults, not literature.
- **Empty `sivin.core.__init__`:** acceptable and documented in the module docstring,
  `docs/architecture.md` and the hand-off API; it is the only way to keep `sivin.config` free of
  pandas without lazy imports.

#### API concerns for the parallel workpackages

1. R2-1 changes only the *values* of `ConversionResult.unresolved` (more rows `True`), no signature.
2. R2-2 adds a `ValueError` to `LocalTimeConverter.to_utc` for non-chronological input. WP-1.2
   (parsers) must pass rows in chronological order, oldest first, and must not sort by local time
   before the conversion; reverse a newest-first export first.
3. R2-4: callers of `to_utc` (WP-1.2) must drop `NaT` rows before `from_records`.
4. No change is requested to `DailyWeather`, `IndexContext`, `ClimateIndex`, `IndexRegistry`,
   `MeasurementSeries` or `sivin.core.defaults`.

### Round 3

Verdict: APPROVE (round 3)

Reviewer: independent Claude reviewer subagent. Reviewed commits `0a92b2b..7609437`
(`a818150`, `7609437`). All round 2 probes plus a new probe (`/tmp/claude-0/review-0.1/r2/r3_order.py`)
were run outside the repository; only this file was changed.

#### Gates observed by the reviewer

- `make lint` → `All checks passed!`, `32 files already formatted`.
- `make type` → `Success: no issues found in 20 source files`.
- `make test` → `190 passed`.
- `make cov` → `TOTAL 843 0 186 0 100%`, threshold 85 % reached.
- Scope: only `src/sivin/core/{timeutil,schema}.py`, `src/sivin/analytics/base.py`, own tests,
  `docs/architecture.md` and this file changed.

#### Round 2 statuses verified

- **R2-1 (fixed — verified).** `r2/fb_min.py` (73 phases × all drops of ≤ 3 of 12 samples,
  21 823 patterns): 0 silently wrong rows (round 2: 490 patterns). `r2/fb_fuzz.py`: multi-year
  2021–2026 at 1825 s ± 20 s, random loss 5/20/50 %: the 1/20/54 wrong rows are now all
  `unresolved` (0 silent). Without gaps still 0 wrong, 0 unresolved. Exhaustive drops around the
  2024/2025/2026 fall-backs: 0 silent. Docstrings (class, `ConversionResult.unresolved`,
  `switch_point`) and `docs/architecture.md` now describe the code; the two round 2 examples are
  tests.
- **R2-2 (fixed — verified).** Reversed input: `ValueError` in all 5 767 patterns (≤ 2 drops,
  73 phases). Input sorted by local time: never silently wrong, all 5 767 patterns `unresolved`.
  A newest-first excerpt with only one unambiguous row escapes the order check but is fully
  `unresolved` (not silent).
- **R2-3 (fixed — verified).** Duplicated export row `02:31:15` in complete 1825 s data: the
  other 4 ambiguous rows are now resolved correctly; both copies become `NaT` + `unresolved`, as
  documented.
- **R2-4 (fixed — verified).** `from_records` with `NaT` raises
  `SchemaError: Timestamps must not be missing (NaT); drop the rows that ... to_utc() returns as NaT first.`
  without the misleading duplicate warning; caller guidance is in all three docstrings.
- **R2-5 (fixed — verified).** `exclude_mask=True`, `latitude_deg=200.0` (and `NaN`) rejected.
- **R2-6 (accepted) — agree.** No worktree depends on the old location.
- Round 1 probes (`ctx.py`, `misc.py`, `nat_chain.py`) show no regressions.

#### Findings (round 3)

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | `src/sivin/core/timeutil.py` `_check_order` | **R3-1.** Any single backward step among the ordinary rows makes `to_utc` raise for the **whole** input, and the message suggests reversing a newest-first export. Reproduced: (a) a device clock corrected back by 30 s on 2026-07-01 → `ValueError`; (b) two overlapping exports concatenated oldest-first each → `ValueError`. Raising is safe, since nothing is silently wrong, but drifting clocks with resyncs are expected in this domain, so one correction would block a multi-year file. No change to `to_utc` is required. WP-1.2's `InputValidator` must detect backward steps and overlaps **before** conversion (drop, split or quarantine), and the `ValueError` message could say "not in chronological order" without assuming a reversed export. | open |
| nit | `src/sivin/core/timeutil.py` `switch_point` | **R3-2.** A backward clock correction that falls **inside** the repeated hour, while the standard-time pass is missing, is taken as the switch point. Local `02:20, 02:50, 02:20:30` (true UTC `00:20, 00:50, 00:20:30`) → the third row returned as `01:20:30`, `unresolved=False`. The same step outside the DST hour raises (R3-1), so the treatment is inconsistent, but it needs a clock correction in that one hour plus a gap. Document it; no fix needed now. | open |

#### API concerns

None. Round 3 adds no signatures. `to_utc` now documents a `ValueError` for non-chronological
input (as requested in round 2). For WP-1.2: pass rows oldest-first without sorting, validate
monotonicity and overlaps before `to_utc` (R3-1), and drop `NaT` rows before `from_records`.
