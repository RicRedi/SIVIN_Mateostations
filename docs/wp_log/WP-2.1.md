# WP-2.1 — Thermal and phenology indices

## Summary

Seven indices of MIGRATION_PLAN §3.1 are implemented as registered `ClimateIndex` subclasses
in `sivin.analytics.thermal`: `gdd_winkler`, `huglin`, `gst`, `bedd`, `budburst`, `gfv`,
`gsr`. Each has a frozen parameter model (every field described with unit and origin of the
default) and a `docs/indices/<id>.md` page. Shared building blocks: registered daily-mean
definitions (`minmax` = (T_max + T_min)/2, `sample_mean`), `IntervalClassification` for the
Winkler, Huglin and GST classes, pure formulas, and `ThermalTimeModel` for the thermal-time sum
used by GDD and the three phenology models. `gdd_winkler` and `huglin` agree with the legacy
`vineyard_analyst.py` formulas on synthetic data (parity tests). Values that I could not check
against the source are configurable and marked `[to be verified]`.

## Changed files

- `src/sivin/analytics/thermal/__init__.py`: re-exports; importing it registers the indices.
- `src/sivin/analytics/thermal/daily_mean.py`: `DailyMeanDefinition` ABC, `DailyMeanRegistry`,
  `MinMaxMean`, `SampleMean`, `daily_mean_registry`.
- `src/sivin/analytics/thermal/classification.py`: `ClassBound`, `IntervalClassification`.
- `src/sivin/analytics/thermal/formulas.py`: `degree_days`, `huglin_daily`, `dtr_adjustment`,
  `bedd_daily`, `fahrenheit_to_celsius_degree_days`.
- `src/sivin/analytics/thermal/thermal_time.py`: `ThermalTimeModel`, `ThermalTimeCurve`.
- `src/sivin/analytics/thermal/base.py`: `ThermalParams` (validated `daily_mean`),
  `ThermalIndex` (daily means, uniform `IndexResult` building).
- `src/sivin/analytics/thermal/{gdd,huglin,gst,bedd,phenology}.py`: the indices.
- `tests/analytics/thermal/`: `conftest.py` (synthetic daily data and contexts),
  `test_formulas.py`, `test_building_blocks.py`, `test_gdd_huglin.py`, `test_gst_bedd.py`,
  `test_phenology.py`.
- `docs/indices/{gdd_winkler,huglin,gst,bedd,budburst,gfv,gsr}.md`, `docs/wp_log/WP-2.1.md`.

### Public API

```python
# sivin.analytics.thermal (all registered in sivin.analytics.base.index_registry)
GddWinklerIndex(GddWinklerParams)   # "gdd_winkler", °C·d, Winkler region, cumulative daily
HuglinIndex(HuglinParams)           # "huglin", °C·d, class, cumulative daily, details["k"]
GstIndex(GstParams)                 # "gst", °C, Jones group, daily means
BeddIndex(BeddParams)               # "bedd", °C·d, cumulative daily
BudburstIndex(BudburstParams)       # "budburst", DOY, estimated=True, needs f_star_c_d
GfvIndex(GfvParams)                 # "gfv", DOY of véraison; flowering/véraison in details
GsrIndex(GsrParams)                 # "gsr", DOY of last target; needs targets
ThermalTimePhenologyIndex[P]        # ABC: subclasses implement stages()
PhenologyStage(label, f_star_c_d)
ThermalTimeModel(base_temp_c).accumulate(mean_temp_c) -> ThermalTimeCurve
ThermalTimeCurve.cumulative_c_d, .total_c_d, .date_reached(f_star_c_d) -> date | None
IntervalClassification(bounds=(ClassBound(label, upper), ...), top_label).classify(value)
DailyMeanDefinition (ABC), MinMaxMean, SampleMean, daily_mean_registry
HuglinParams.coefficient(latitude_deg) -> float | None; LatitudeBand
```

Result conventions: a value is `None` with `details["status"]` when the period has no complete
day, Huglin has no K, a phenology model is not configured or its last stage is not reached.
Classes are assigned only when the season is `complete`. `details["n_days"]` is always the
number of complete days used.

## How it was verified

All commands in `/home/user/wt/wp-2.1` with `.venv` (Python 3.12, ruff 0.16.10, mypy 2.4.0):

- `make lint` → `All checks passed!`, `49 files already formatted`.
- `make type` → `Success: no issues found in 31 source files`.
- `make test` → `244 passed` (63 of them in `tests/analytics/thermal/`).
- `make cov` → `TOTAL 1295 0 220 0 100%`, `Required test coverage of 85% reached. Total
  coverage: 100.00%`; every module of `sivin.analytics.thermal` at 100 % (line and branch).
- Hand-computed examples (commented in the tests) for every index and formula; Winkler bound
  conversion checked arithmetically (2500/3000/3500/4000 °F·d × 5/9 = 1388.9/1666.7/1944.4/
  2222.2 °C·d).
- Legacy parity: ten synthetic local days (seeded, 1825 s sampling) → `gdd_winkler` equals the
  legacy `calculate_gdd` formula and `huglin` (with `daily_mean: sample_mean`,
  `k_override: 1.05`) equals the legacy `calculate_huglin_index` formula (`rel=1e-12`). The
  legacy functions are re-implemented in the test because importing `vineyard_analyst.py` runs
  its pipeline.

## What did not work / what was not verified

- No real sensor data were used; all numbers in tests are synthetic.
- Literature values not checked against the sources (no access), all configurable and marked
  `[to be verified]` in code and docs:
  - Huglin K table by 2° band (1.02–1.06 for 40–50°): the range is what I know from Tonietto &
    Carbonneau (2004), the band edges are not verified.
  - GST class bounds 13/15/17/19/24 °C (Jones, 2006) and their inclusive/exclusive handling.
  - All BEDD constants (cap 9 °C·d, DTR band 10–13 °C, factor 0.25, order of operations, floor
    at 0) and the day-length coefficient (not shipped, default 1.0 = off).
  - GFV general-model critical sums 1282 °C·d (flowering) and 2528 °C·d (véraison) of Parker
    et al. (2011).
  - Budburst base temperature 5 °C (project default); no critical sum is shipped.
  - Whether Huglin (1978) / Tonietto & Carbonneau (2004) mean $(T_{max}+T_{min})/2$ or another
    daily mean.
  - The English name of Huglin class HI+1 ("warm temperate" vs. the label `temperate_warm`).
- No DOI is given; every reference is marked `[DOI not verified]`; the Jones (2006) page range is
  marked as to be verified.
- Phenology outputs are not calibrated against local BBCH observations (none exist yet).

## Deviations

- **No `SampleDurations` class.** The common rules ask for one reusable duration class for
  hour-based metrics; none of the WP-2.1 indices is hour-based (all use daily aggregates), so it
  is not built here to avoid unused code. WP-2.2/2.3 own the hour-based metrics.
- **Huglin K lookup gives 1.06 at our sensors (~48.88° N)** while legacy used 1.05; values are
  ~0.95 % higher than legacy. `k_override: 1.05` reproduces legacy numbers.
- **Huglin daily mean default `minmax`**, whereas legacy Huglin used the sample mean (legacy GDD
  used min/max). Parity is tested with `sample_mean`.
- **Legacy period semantics not reproduced:** legacy GDD summed over the whole selected period
  and both legacy indices used incomplete days; here the period is fixed per index and only
  complete days count. Parity holds on complete in-season data.
- **Phenology value** is a day of year (unit `"DOY"`); for `gfv` it is the véraison date, for
  `gsr` the last configured target; all stage dates are in `details`.
- **Phenology coverage** is measured from the period start to the predicted (last) stage, not
  over the whole period, so a season with an early stage is complete without data until
  October 31.
- Huglin K outside the table or without latitude → `value = None` instead of guessing K = 1.

## Out of scope

- `SampleDurations`-style duration logic will exist in WP-2.2/2.3 packages; when two copies exist
  they should move to `sivin.core` (proposal for the integration WP).
- `daily_mean_registry` (min/max vs. sample mean) could be useful to WP-2.2 (`dtr_ripening`,
  `cool_night` use only min/max, so probably not needed); if another package needs it, move it
  to `sivin.analytics` or `sivin.core.daily`.
- `IndexResult.daily` for phenology is the cumulative thermal sum; the site contract
  (§2.6, `indices/<season>.json`) has no field for curves or stage dates yet — the
  `SiteBuilder` WP needs to decide how to publish `daily` and `details`.

## Open questions for the owner

1. **Configuration (proposal for WP-1.7/WP-3.2):** a section `analytics.indices` mapping index
   id → parameter mapping, passed to `index_registry.create(index_id, params)`, e.g.
   ```yaml
   analytics:
     indices:
       huglin: {k_override: 1.05}       # optional, default = latitude lookup (1.06 here)
       gfv: {}                          # general model defaults
       gsr: {targets: []}               # needs cultivar values
       budburst: {f_star_c_d: null}     # needs local calibration
   ```
   Cultivar-dependent models (`gsr`, later `gfv` per cultivar) need **per-sensor parameters**
   (variety from the registry, Q4); the config contract has no place for that yet.
2. **CLI (proposal):** `sivin indices compute --season 2026 [--index huglin ...]` writing the
   results used by the `SiteBuilder`.
3. Huglin K: keep the latitude lookup (1.06 for our sensors) or fix K = 1.05 as before?
4. Please verify against the papers: Huglin K bands, GST bounds, BEDD constants, GFV F* values
   (1282 / 2528 °C·d), and supply GSR critical sums for the cultivars of the sensors.
5. Contract proposal: `IndexContext` has no notion of the sensor's cultivar; GSR/GFV per
   cultivar would need it (e.g. `variety: str | None` from the registry).

## Review

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
