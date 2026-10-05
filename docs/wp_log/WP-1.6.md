# WP-1.6 — Pairing sensors in time (alignment)

## Summary

New package content `sivin.alignment` puts N ≥ 1 sensors on a common UTC time grid
(MIGRATION_PLAN §2.7, second meaning). `TimeGrid` is a frozen, epoch-anchored regular grid
(default step 1800 s); `GridPolicy` derives it from the usable data spans with a registered
`SpanRule` (`union` or `overlap`). `AlignmentStrategy` is an ABC with a registry and two
implementations, `NearestWithinTolerance` (default tolerance half the step, inclusive, ties to
the earlier sample, offsets reported) and `LinearInterpolation` (time-weighted, `max_gap_s`,
never extrapolates); both are vectorised with `numpy.searchsorted` and see only samples that are
neither QC-excluded nor `NaN`, per variable. `SensorAligner` returns an immutable `AlignedPanel`
with a `time x sensor` table per variable (`temp_c`, `rh_pct`), a validity mask, offsets,
`pairwise_differences` and `complete_rows`. `AlignmentConfig` is the proposed config section.
`docs/alignment.md` documents the method, formulas, parameters and recommended use.

## Changed files

- `src/sivin/alignment/__init__.py` (re-exports), `registry.py` (`ClassRegistry`), `grid.py`
  (`TimeGrid`, `GridPolicy`, `SpanRule`, `UnionSpan`, `OverlapSpan`, `span_registry`,
  `usable_span`, `epoch_ns`), `strategies.py` (`SampleSet`, `AlignedValues`, `StrategyParams`,
  `AlignmentStrategy`, `NearestParams`, `NearestWithinTolerance`, `LinearParams`,
  `LinearInterpolation`, `strategy_registry`), `panel.py` (`AlignedPanel`), `aligner.py`
  (`SensorAligner`, `ALIGNED_VARIABLES`), `config.py` (`AlignmentConfig`).
- `tests/alignment/conftest.py`, `test_grid.py`, `test_strategies.py`, `test_aligner.py`,
  `test_panel_config_registry.py`.
- `docs/alignment.md`, `docs/wp_log/WP-1.6.md`.

## Public API

```python
# sivin.alignment
TimeGrid(start, end, step_s=1800.0)            # frozen; times, times_ns, step, len
TimeGrid.from_series(series, policy, exclude_mask) -> TimeGrid | None
GridPolicy(step_s=1800.0, span=UnionSpan())   # frozen; grid_for(spans) -> TimeGrid | None
SpanRule (ABC, rule_id, bounds(spans, step)); UnionSpan "union"; OverlapSpan "overlap"
AlignmentStrategy[P] (ABC, strategy_id, params_model, provides_offsets, align(samples, grid),
                      from_params(mapping))
NearestWithinTolerance "nearest_within_tolerance" (NearestParams.tolerance_s: float | None)
LinearInterpolation "linear_interpolation" (LinearParams.max_gap_s = 2737.5)
SampleSet.from_series(series, variable, exclude_mask); AlignedValues(grid_values, valid, offset_s)
strategy_registry, span_registry (ClassRegistry: register, get, ids, in, len)
SensorAligner(strategy, grid_policy=None, exclude_mask=QcFlag.DEFAULT_EXCLUDE)
    .align(series, grid=None) -> AlignedPanel; .grid_for(series); .from_config(cfg, mask)
AlignedPanel: variable(name), validity(name), offsets_s(name) -> DataFrame | None,
    pairwise_differences(name), complete_rows(name), sensors, variables, times,
    strategy_id, is_empty, len
AlignmentConfig(strategy, params, grid_step_s, span)   # frozen, extra="forbid"
```

## How it was verified

All commands in `/home/user/wt/wp-1.6`:

- `make lint` → ruff check: all checks passed; ruff format --check: all files formatted.
- `make type` → `mypy --strict`: no issues found in 26 source files.
- `make test` → 273 passed (92 of them in `tests/alignment`).
- `make cov` → 273 passed, total coverage 100 %; every `src/sivin/alignment/*.py` module at
  100 % statements and branches (486 statements, 74 branches).
- Acceptance tests with hand-computed expectations: three synthetic sensors with offsets
  0 / −300 / +880 s and periods 1825 / 1790 / 1820 s on a 0–7200 s grid, for both strategies
  (values, offsets, validity) and their pairwise differences; tolerance boundary (900 s valid,
  900 s + 1 ns invalid); tie → earlier sample; 1825 s sampling on an 1800 s grid loses exactly
  grid point 36 of 0–73 with nearest and it is filled by interpolation; gap longer than
  `max_gap_s` stays empty, equal gap is bridged; no extrapolation; excluded (SPIKE) and `NaN`
  samples skipped per variable, informative STEP not; both 2026 Europe/Prague DST transitions;
  single sensor; empty series next to data; only empty series → empty panel; 12 sensors without
  code change; duplicate / missing input rejected.
- A synthetic year (17 280 samples at 1825 s) × 30 sensors aligns by linear interpolation in
  about 0.3 s in this sandbox (one pytest run; the test asserts shape and validity only).

## What did not work / what was not verified

- No real export was available: the defaults `max_gap_s = 2737.5 s` and `tolerance_s = step/2`
  are project choices marked [to be verified] and not tuned on real data. The claimed drift
  pattern (≈1825 s, unsynchronised clocks) is taken from the legacy configs, not measured here.
- Run time and memory were not benchmarked beyond the single timing above.
- `NEIGHBOR_OUTLIER` detection that would consume the panel is not part of this WP.

## Deviations

- `AlignedPanel` is an immutable `__slots__` class (no setters, every accessor returns a copy)
  rather than a `@dataclass(frozen=True)`: dataclass field equality over `DataFrame`s is not
  meaningful and the public fields would expose mutable frames.
- The grid span is derived from *usable* rows (not excluded by the mask, at least one variable
  not `NaN`), not from all rows, so e.g. office records flagged `PRE_DEPLOYMENT` do not widen a
  union grid. Series without usable rows do not empty an `overlap` grid.
- With the default inclusive tolerance of half the step, a sample exactly half-way between two
  grid points serves both (documented and tested).
- Sensor columns are ordered by sensor id, not by input order, for deterministic output.
- A generic `ClassRegistry` lives in `sivin.alignment.registry` (the shared `IndexRegistry` is
  specific to `ClimateIndex`).

## Out of scope

- `epoch_ns` (tz-aware times → int64 ns) in `sivin/alignment/grid.py` is generally useful; it
  could move to `sivin/core/timeutil.py` (WP-0.1 contract owner) later.
- `ClassRegistry` duplicates the shape of `sivin.analytics.base.IndexRegistry`; a shared generic
  registry in `sivin.core` could serve QC checks, parsers, strategies and indices alike.
- Neighbour QC (`NEIGHBOR_OUTLIER`) should use `NearestWithinTolerance` + `OverlapSpan` and
  `AlignedPanel.pairwise_differences` (WP-1.5 follow-up).

## Open questions for the owner

1. Integration (WP-1.7): add `alignment: AlignmentConfig` to `SivinConfig` (section
   `alignment` in `config/sivin.yaml`, keys `strategy`, `params`, `grid_step_s`, `span`) and
   build the aligner with `SensorAligner.from_config(cfg.alignment, cfg.analytics.exclude_mask)`.
   Proposed CLI: `sivin align [--sensor ID ...] [--from/--to ISO] [--strategy ...] --out FILE`
   writing the wide table of each variable (CSV) for inspection. Agree?
2. Default strategy: `nearest_within_tolerance` (measured values only) was chosen as the safer
   default; spatial analysis would rather use `linear_interpolation`. Should the default differ
   per consumer (QC vs. WP-2.4), i.e. one config subsection per consumer?
3. Is 1.5 × 1825 s an acceptable default `max_gap_s`, or should interpolation bridge a single
   missing sample (≈ 2 × 1825 s plus margin)?

No contract from §2 or WP-0.1 needed changing.

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer agent. Throwaway scripts in `/tmp/claude-0/review-1.6/`
(not committed).

### Gates observed

- `make lint` → ruff check passed, `ruff format --check`: 43 files already formatted.
- `make type` → `mypy --strict`: Success, no issues in 26 source files. No `type: ignore` /
  `noqa` in `src/sivin/alignment`.
- `make test` → 273 passed.
- `make cov` → 273 passed; every `src/sivin/alignment/*.py` module 100 % statements and
  branches (486 statements, 74 branches); total 100 %.
- Scope: only `src/sivin/alignment/**`, `tests/alignment/**`, `docs/alignment.md`,
  `docs/wp_log/WP-1.6.md` changed against `bcde7d9`; no shared file touched.

### Measurements (synthetic, deterministic seeds)

Synthetic year, 30 sensors, period 1825 s ± 0.5 s, random start phase, whole-second
timestamps, union grid at 1800 s; coverage measured on interior rows:

| Strategy / parameter | coverage per sensor | `complete_rows` share | pairs valid | max offset |
|---|---|---|---|---|
| nearest, τ = 900 s (default) | 0.9868 (≈ 72/73) | **0.674** | 0.974 | 900 s |
| nearest, τ = 912.5 s (= 1825/2) | 0.9999 | 0.998 | 0.9997 | 912 s |
| nearest, τ = 930 s | 1.0000 | 1.000 | 0.9999 | 916 s |
| linear, `max_gap_s` 2737.5 s | 1.0000 | 1.000 | 0.9998 | — |

Run time and memory (tracemalloc around `align`): 30 sensors × 17 280 samples: 0.25 s, peak
40 MB, panel 18 MB; 100 sensors: 0.79 s, peak 134 MB, panel 60 MB. `align` itself is fine.
`pairwise_differences("temp_c")`: 30 sensors → 7.4 M rows, 2.3 s, **965 MB**;
100 sensors → 84.5 M rows, 40 s, **11 GB**.

Hand checks that passed: interpolation across a SPIKE-excluded sample is not bridged at the
default `max_gap_s` (neighbours 3650 s apart) and is bridged with time weight when `max_gap_s`
= 4000 s (10 + 10 · 1800/3650 = 14.93 °C, verified); a `NaN` temperature leaves `rh_pct` of the
same row usable (per-variable independence verified); nearest skips the excluded sample and
does not substitute a neighbour 925 s away; an all-excluded sensor yields an all-`NaN` column
and an empty pairwise frame; overlap grid ignores a sensor without usable data (as documented).

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | src/sivin/alignment/strategies.py:290, config.py:34, docs/alignment.md:63,119 | Default `nearest_within_tolerance` with τ = Δ/2 = 900 s leaves one empty grid point per ~73 for every sensor sampling at 1825 s (periodic gap every ~18 h). Per sensor that is only 1.4 %, but the gaps fall at different times per sensor, so `complete_rows` keeps only 67 % of the year for 30 sensors (measured), and union-span charts (recommended in the doc) show a broken line every 18 h. The maximum distance from a grid point to the nearest sample of an uninterrupted 1825 s record is 912.5 s, so Δ/2 is structurally too small for the actual sampling. Fix: make the default tolerance derive from the sampling interval, e.g. `max(Δ, LEGACY_SAMPLING_INTERVAL_S)/2` plus a named jitter margin (≈ 930 s gave 100 % coverage, max offset 916 s), marked [to be verified]; keep τ = Δ/2 available as a "never reuse a sample" option; update docs, worked-example test and `NearestParams` description. Alternatively make `linear_interpolation` the config default and state that nearest is for QC only. | open |
| major | src/sivin/alignment/panel.py:205-243 | `pairwise_differences` materialises every pair × every grid point with per-row Python-string labels: 30 sensors × 1 year → 7.4 M rows, 965 MB, 2.3 s; 100 sensors → 11 GB, 40 s. This contradicts brief point 4 ("memory-efficient for a year … × tens of sensors"), and neighbour QC needs only neighbour pairs. Fix: use a categorical dtype (or the sensor index as small int) for `sensor_a`/`sensor_b`, and accept an optional `pairs` argument (iterable of `(SensorId, SensorId)`) so consumers can restrict to neighbours; add a size test. | open |
| minor | src/sivin/alignment/registry.py:18 | `ClassRegistry` is a sixth near-identical registry in the code base (`IndexRegistry` in core analytics; sibling branches add `ParserRegistry`, `ValidationRuleRegistry`, `NamedRegistry[T]`, `CheckRegistry`). Acceptable inside this WP because `core` is out of scope and the worker flagged it, but the owner should schedule one generic registry in `sivin.core` (this `ClassRegistry` is a good candidate) and migrate the others. | open |
| minor | src/sivin/alignment/strategies.py:93, grid.py:262 | `SampleSet.from_series` / `usable_span` go through `series.frame`, which copies the whole frame, and `TimeGrid.times_ns`/`__len__` rebuild the `date_range` on every call (2·N+ times per `align`). Not a problem at the measured size; cache the grid times (e.g. `functools.cached_property` is not usable with slots, so compute once in `align`) and use `series.timestamps`/column accessors if available. | open |
| nit | src/sivin/alignment/grid.py:70,223 | A step below 1 ns (e.g. `step_s=1e-10`) passes validation and fails later in pandas with `ZeroDivisionError`; a non-integer-nanosecond step is silently rounded. Require `step_s >= 1` (or a whole number of seconds) with a clear error. | open |
| nit | src/sivin/alignment/config.py:41 | `params: dict[str, float \| None]` is a mutable dict inside a frozen model and hard-codes that every strategy parameter is a float; a future non-numeric parameter would need a contract change. Consider `Mapping[str, Any]` validated by the strategy's model (already done in `_valid_params`) or a discriminated union of the params models. | open |
| nit | src/sivin/alignment/strategies.py:176,273,354 | `params_model` is typed `type[StrategyParams]`, not tied to `P`, so `__init__`/`from_params` need `cast`; a mismatch between the generic argument and `params_model` would not be caught by mypy. Acceptable, but a one-line class-creation check (`__init_subclass__`) would make it safe. | open |

### Deviations assessment

- Immutable `__slots__` `AlignedPanel` instead of a frozen dataclass: agreed; frames are copied
  on access, equality over frames would be meaningless.
- Grid span from usable rows only: agreed and sensible (PRE_DEPLOYMENT office records must not
  widen a union grid); documented.
- Inclusive tolerance, a sample exactly half-way serves both grid points: acceptable. With
  whole-second timestamps and exactly 1825 s it happens only for sensors whose phase is a
  multiple of 25 s, and there it is precisely what avoids the empty point; the offset table
  exposes it. Since the recommended larger tolerance (major finding 1) reuses samples routinely
  anyway (there are 240 fewer samples than grid points per year), this should simply be stated
  as "a sample may serve two grid points" in the docs.
- Columns ordered by sensor id: agreed (deterministic).
- Own `ClassRegistry`: acceptable within scope; see minor finding.

Acceptance criteria of MIGRATION_PLAN §4 WP-1.6 (three drifting sensors with hand-computed
expectations for both strategies, gap longer than the limit stays empty, N sensors without code
change, QC-excluded values not paired) are met and tested; the changes requested concern the
usefulness of the default tolerance and the memory of `pairwise_differences`.
