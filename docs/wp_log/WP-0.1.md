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
