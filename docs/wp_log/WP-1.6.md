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

Verdict: _pending_ (round 1)

| Severity | File:line | Finding | Status |
|---|---|---|---|
