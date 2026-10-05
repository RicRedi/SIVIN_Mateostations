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

## Changed files

- Tooling: `pyproject.toml`, `Makefile`, `.pre-commit-config.yaml`, `.gitignore`,
  `.github/workflows/ci.yml`, `requirements.txt` (deleted).
- Configuration: `config/sivin.yaml`.
- Package: `src/sivin/{__init__,cli,config,paths,logging_setup}.py`,
  `src/sivin/core/{__init__,ids,flags,schema,timeutil,daily,season}.py`,
  `src/sivin/analytics/{__init__,base}.py`,
  `src/sivin/{registry,ingest,storage,quality,alignment}/__init__.py` (docstring only).
- Tests: `tests/conftest.py`, `tests/core/test_{ids,flags,schema,timeutil,daily,season}.py`,
  `tests/analytics/test_base.py`, `tests/test_{config,paths,cli}.py`.
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
@dataclass(frozen=True) class ConversionResult: timestamps_utc: pd.Series; suspect: pd.Series
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
    # columns temp_min, temp_mean, temp_max, rh_min, rh_mean, rh_max, n_samples, coverage

# sivin.core.season
@dataclass(frozen=True, slots=True, order=True) class MonthDay: month, day; in_year(year)
@dataclass(frozen=True, slots=True) class Season: start, end
    vegetation(), huglin(), month(m); dates(year) -> (date, date); n_days(year); contains(d)

# sivin.analytics.base
@dataclass(frozen=True, slots=True) class IndexContext: sensor_id, year, daily, series,
    latitude_deg, elevation_m, timezone, min_daily_coverage=0.9, min_season_coverage=0.9,
    exclude_mask=311
@dataclass(frozen=True) class IndexResult: index_id, sensor_id, year, value, unit, coverage,
    complete, classification=None, daily=None, details={}, estimated=False
class IndexParams(BaseModel)                       # frozen, extra="forbid"
class ClimateIndex[P: IndexParams](ABC):
    index_id: ClassVar[str]; unit: ClassVar[str]; params_model: ClassVar[type[IndexParams]]
    def __init__(self, params: P | None = None); params: P
    @abstractmethod compute(self, ctx: IndexContext) -> IndexResult
    _season_days(self, ctx, season) -> SeasonDays  # complete days + coverage + complete
class IndexRegistry: register (class decorator; also register("id")), create(index_id, params),
    get(index_id), ids(), __contains__, __len__
index_registry: IndexRegistry

# sivin.config / sivin.paths / sivin.logging_setup
SivinConfig(paths: PathsConfig, time: TimeConfig, analytics: AnalyticsConfig); .default()
load_config(path: Path) -> SivinConfig            # raises ConfigError naming key paths
ProjectPaths(root); .discover(start=None); .resolve(relative)
setup_logging(level="INFO")
```

## How it was verified

All commands in `/home/user/wt/wp-0.1` with a venv created by
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
2. **Every ambiguous fall-back time is marked suspect**, also when its offset was inferred from
   the sample order. Plan WP-1.2 says "ambiguous → `TIMESTAMP_SUSPECT`"; the brief only asked to
   mark the cases where inference fails. If inference fails, all ambiguous times of that input
   are read as standard time (deterministic, logged as a warning).
3. **Nonexistent spring-forward times** are read with the UTC offset in force before the
   transition (PEP 495 `fold=0`), i.e. shifted forward by the length of the gap
   (02:15 → 03:15 CEST = 01:15 UTC). pandas' `nonexistent="shift_forward"` would collapse all of
   them to 03:00 and create duplicates. Consequence: such samples can be later in UTC than a
   genuine 03:00 sample that follows them; `from_records` sorts, and the rows are suspect.
4. **Additions to the briefed API** (only additions): `IndexContext.min_daily_coverage`,
   `.min_season_coverage`, `.exclude_mask` (with defaults); `AnalyticsConfig.min_season_coverage`
   (default 0.9, project default to be tuned) to decide `IndexResult.complete`; `SeasonDays`
   (return type of the protected helper); `IndexParams` base model; `IndexRegistry.get`/`__len__`;
   `QcFlag.all_bits()`; `excluded()` (vectorised `is_excluded`); `LocalTimeConverter.timezone`
   and `.day_length_s()`; `DailyWeather.timezone`/`.dates`; `Season.n_days()`;
   `MonthDay.in_year()`; `ProjectRootNotFoundError`; `ConfigError`.
5. **Index parameters**: the parameter model is the class variable `params_model` and the class
   is generic, `ClimateIndex[P]`, so `self.params` is precisely typed under mypy `--strict`.
   A nested class named `Params` cannot be used as the generic argument of its own outer class.
6. **Registry decorator**: the key is always the class's `index_id` (brief), but the form shown
   in plan §1.2, `@index_registry.register("huglin")`, is accepted too and must match it.
7. **`DailyWeather` valid sample** = not excluded by the mask **and** both `temp_c` and `rh_pct`
   present. All days from the first to the last sample are rows; days without valid samples
   have `n_samples = 0`, `coverage = 0`, `NaN` aggregates. Means are arithmetic sample means.
8. **`MeasurementSeries`** accepts a `sensor_id` column in its constructor only if every row
   equals the series' id (then drops it), so `to_frame()` output round-trips. `from_records`
   does not set `MISSING` for `NaN` values; that is left to QC (WP-1.5).
9. **`.gitignore`**: besides the briefed rules, `lib/`/`lib64/` (Python template) are anchored to
   the root so that `web/src/lib/` is not ignored, root-level images/videos (legacy outputs)
   are ignored, and `!/tests/fixtures/**` re-includes fixtures matched by any global rule.
10. **Tests outside the plan's Files list**: `tests/analytics/test_base.py` and
    `tests/test_{config,paths,cli}.py` (plan lists only `tests/core/**`; the brief allows them).
11. CI also runs on pushes to `main` (brief) in addition to `wp/**`, `claude/**` and PRs (plan).

## Out of scope

- `README.md` still documents `pip install -r requirements.txt` and "Python 3.8+"; to be
  rewritten in WP-5.2.
- `CLAUDE.md` (line 30) and `CONTRIBUTING.md` (line 14) still say that before WP-0.1 only
  `requirements.txt` exists; the remark becomes obsolete after the merge.
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
| major | `src/sivin/core/timeutil.py:110-119` | Ambiguous-time fallback is global: if pandas cannot infer **one** fall-back cluster, **every** ambiguous time of the whole input is read as standard time. Reproduced: (a) input spanning 2025 (complete repeated hour, 1800 s) and 2026 (one sample in the repeated hour) → the correctly inferable 2025 rows `02:00`/`02:30` CEST map to the same UTC instants as the CET rows (2 exact duplicates, result not monotonic); `MeasurementSeries.from_records` then silently drops 2 real samples (warning only). (b) single year, 1825 s sampling, one sample missing inside the repeated hour → 1–2 samples silently 3600 s late while the output stays monotonic, so no later check can see it. (c) one `NaT` inside the repeated hour has the same effect. Fix: resolve each transition cluster separately (group ambiguous runs by local date); within a cluster use the backward jump of the wall clock as the switch point; when a cluster has no jump, pick the offset that keeps UTC strictly increasing w.r.t. the neighbouring unambiguous samples; never return duplicate UTC instants silently (raise or report). Add tests for (a)–(c) and for 1825 s data with a missing sample. | open |
| major | `src/sivin/core/daily.py:128-130` | A sample counts only if **both** `temp_c` and `rh_pct` are present (deviation 7), so a missing RH value discards a valid temperature. Reproduced: `temp_c=[1, 30]`, `rh_pct=[50, NaN]` → `temp_max = 1.0` instead of 30.0, `n_samples = 1`. Most indices of §3.1/§3.2 use temperature only; an RH channel failure would make them lose whole days and `complete` flags. Fix: aggregate each variable over its own valid (not excluded, not NaN) samples; define `n_samples`/`coverage` explicitly (e.g. on temperature, which all thermal indices use, or add `n_samples_rh`/`coverage_rh` while keeping `coverage` for the site contract) and document it; add a hand-computed test. Related owner question: `qc` is one bit field per row (frozen contract §2.5), so an RH-only QC finding also excludes the temperature — worth raising before WP-1.5. | open |
| minor | `src/sivin/core/timeutil.py:121-123` | Nonexistent spring-forward times read with `fold=0` can collide with genuine post-gap samples: local `02:00, 02:15, 03:00, 03:15` on 2026-03-29 → UTC `01:00, 01:15, 01:00, 01:15` (duplicates; `from_records` then drops two). The docstring says spacing is preserved but not that duplicates can occur. Suggest: report non-monotonic / duplicate output in `ConversionResult` (or raise), and document that samples inside the gap mean the source zone assumption (Q2) is probably wrong. | open |
| minor | `src/sivin/core/schema.py:164-171` | `from_records` resolves duplicate timestamps with **different** values by keeping the last row, with only a log warning (reproduced: two rows at the same instant with 1.0 and 2.0 → 2.0 kept). This hides both the DST bugs above and real conflicts that §2.7 assigns to `InputValidator`. Suggest: drop only fully identical rows; raise `SchemaError` (or return the conflicts) for conflicting duplicates and leave the policy to WP-1.2/WP-1.4. | open |
| minor | `src/sivin/core/ids.py:21,27` | `\d` matches any Unicode digit: `SensorId("٧٧٦٧٨٢٧١")` is accepted and `parse` returns a non-ASCII serial. Use `[0-9]` or `re.ASCII` (also for `name.isdigit()` at line 101). | open |
| minor | `src/sivin/core/ids.py:23-33` | Browser-renamed downloads are rejected: `MeteoData_8615620 77678271 (VUT)_20260301_223857 (1).xlsx` → `ValueError`. Chrome appends ` (1)` when the legacy `chrome_driver.py` downloads into the same folder twice. Suggest accepting an optional ` \(\d+\)` before the extension (with a test), or documenting that callers strip it. | open |
| minor | `src/sivin/core/daily.py:219-230` | The public `DailyWeather` constructor validates only column names and index: string columns, `coverage = 5.0` and negative `n_samples` are accepted (reproduced). Validate dtypes (`float64`, `int64`), `0 <= coverage <= 1`, `n_samples >= 0`. | open |
| minor | `src/sivin/analytics/base.py:56-92` | `IndexContext` repeats `sensor_id` and `timezone` that `daily`/`series` already carry and does not check consistency (reproduced: context with sensor `11111111`, zone `UTC` and Prague daily data of `77678271` is accepted). Its defaults `0.9/0.9/311` duplicate the config defaults, so a factory that forgets to pass the configuration silently ignores `config/sivin.yaml`. Suggest: `__post_init__` consistency checks and no defaults for the three config-driven fields (or derive `sensor_id`/`timezone` from `daily`). | open |
| minor | `src/sivin/analytics/base.py:208` | `params_model` defaults to the empty `IndexParams`; a subclass that forgets to set it registers fine and `create("y", {"base": 5})` fails with a confusing "extra inputs not permitted". Make `_add` require that `params_model` is overridden (a proper subclass of `IndexParams`). | open |
| minor | `src/sivin/config.py:17` | Layering inversion: the configuration module imports `sivin.analytics.base` (and through it pandas, `daily`, `schema`) only for two constants, so `sivin --version` / `config show` import the whole analytics stack. Move `DEFAULT_MIN_*` to `config.py` (or `sivin.core`) and let analytics depend on them, not the reverse. | open |
| minor | `pyproject.toml:31-32,89` | Dev tools are unbounded (`ruff>=0.6`, `mypy>=1.11`) while pre-commit pins ruff `v0.16.10`, and `filterwarnings = ["error"]` turns any new deprecation into a failure; with no lock file CI can turn red on a new release without a code change, and local pre-commit and CI may disagree. Suggest bounding ruff/mypy to the tested series (e.g. `ruff>=0.16,<0.17`, `mypy>=2.4,<3`) to match pre-commit. pandas `>=3.0`: see deviations. | open |
| minor | `.gitignore:213` | `/data/` (briefed rule) also ignores `data/raw/...` on the `data` branch, which is where §2.5 puts the store. WP-1.4 / WP-4.1 must `git add -f` or the `data` branch needs its own `.gitignore`. Not a defect of this WP; note it in the WP-1.4 brief. | open |
| nit | `src/sivin/config.py:114` | `exclude_mask: true` is accepted as `1` (pydantic lax mode). Use `StrictInt`. | open |
| nit | `src/sivin/core/schema.py:376` | `±inf` is accepted as a temperature/RH value; the contract only knows `NaN` = missing. Reject or convert to `NaN`. | open |
| nit | `src/sivin/core/schema.py:395-398` | A `Series` of strings with mixed UTC offsets raises pandas' bare `ValueError` instead of `SchemaError`, unlike the list path. | open |
| nit | `src/sivin/core/schema.py:151-162` | Frames built by `from_records` carry `Column` enum members as column labels, frames passed to the constructor keep plain `str` labels; harmless (StrEnum) but inconsistent — normalise labels to `str` in `_validated_copy`. | open |

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
