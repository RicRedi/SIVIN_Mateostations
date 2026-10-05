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

**Round 2** addressed the round-1 review following the orchestrator's decisions:
- `gfv` ships no critical sums. It is "not configured" until both are set; 1282/2528 °C·d are
  listed in `gfv.md` only as unverified candidates.
- Every result carries `n_missing_days`. `gdd_winkler` and `huglin` are classified only when
  `n_missing_days <= max_missing_days` (default 0). The low bias of sums with missing days is
  documented.
- The phenology models return `value = None` with status "accumulation start not covered"
  when more than `max_missing_days_at_start` (default 0) days are missing at the start. They
  give `details["date"]` beside the DOY.
- Huglin K bands are upper-inclusive.
- BEDD has a `cap_order` parameter.
- The docs were corrected (Huglin legacy differences, GST scheme and wording, leap-year DOY).
- `wp/0.1-foundation` (8f354c0) was merged.

## Changed files

- `src/sivin/analytics/thermal/__init__.py`: re-exports; importing it registers the indices.
- `src/sivin/analytics/thermal/daily_mean.py`: `DailyMeanDefinition` ABC, `DailyMeanRegistry`,
  `MinMaxMean`, `SampleMean`, `daily_mean_registry`.
- `src/sivin/analytics/thermal/classification.py`: `ClassBound`, `IntervalClassification`.
- `src/sivin/analytics/thermal/formulas.py`: `degree_days`, `huglin_daily`, `dtr_adjustment`,
  `bedd_daily`, `bedd_daily_cap_before_adjustment`, `fahrenheit_to_celsius_degree_days`.
- `src/sivin/analytics/thermal/thermal_time.py`: `ThermalTimeModel`, `ThermalTimeCurve`.
- `src/sivin/analytics/thermal/base.py`: `ThermalParams` (validated `daily_mean`),
  `ClassifiedSumParams` (`max_missing_days`, `sum_class`), `missing_days`, `ThermalIndex`
  (daily means, uniform `IndexResult` building incl. `n_missing_days`).
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
GfvIndex(GfvParams)                 # "gfv", DOY of véraison; needs both F*; stages in details
GsrIndex(GsrParams)                 # "gsr", DOY of last target; needs targets
ThermalTimePhenologyIndex[P]        # ABC: subclasses implement stages()
PhenologyStage(label, f_star_c_d)
ThermalTimeModel(base_temp_c).accumulate(mean_temp_c) -> ThermalTimeCurve
ThermalTimeCurve.cumulative_c_d, .total_c_d, .date_reached(f_star_c_d) -> date | None
IntervalClassification(bounds=(ClassBound(label, upper), ...), top_label).classify(value)
DailyMeanDefinition (ABC), MinMaxMean, SampleMean, daily_mean_registry
HuglinParams.coefficient(latitude_deg) -> float | None; LatitudeBand
```

Result conventions:
- A value is `None` with `details["status"]` when:
  - the period has no complete day;
  - Huglin has no K;
  - a phenology model is not configured;
  - its accumulation start is not covered;
  - its last stage is not reached.
- `details["n_days"]` (complete days used) and `details["n_missing_days"]` (incomplete days of
  the evaluated period) are always present.
- Sum classes (`gdd_winkler`, `huglin`) are assigned only when the season is `complete` and
  `n_missing_days <= max_missing_days`. GST is classified when `complete`.
- Phenology results also have `details["date"]` (ISO local date of the value) and
  `details["n_missing_days_at_start"]`.

## How it was verified

Round 2, after merging `wp/0.1-foundation` (8f354c0), same venv:

- `make lint` → `All checks passed!`, `49 files already formatted`.
- `make type` → `Success: no issues found in 31 source files`.
- `make test` → `267 passed` (77 of them in `tests/analytics/thermal/`).
- `make cov` → `TOTAL 1361 0 236 0 100%`, `Required test coverage of 85% reached. Total
  coverage: 100.00%`. Every module of `sivin.analytics.thermal` is at 100 % line and branch
  coverage.
- New tests:
  - The reviewer's gap probe as a test (`test_reviewer_probe_gap_is_not_classified`): a
    synthetic 2025 year with a May 1–19 gap gives `n_missing_days = 19`, coverage 195/214,
    `complete = True`, no region, and a lower sum than without the gap.
  - `max_missing_days` gating for GDD and Huglin (hand-computed: 211 × 8 = 1688 °C·d;
    182 × 11.66 = 2122.12 °C·d).
  - Late deployment (data from June 1: 92 days missing at the start → `None`; tolerated → the
    flowering date is computed by hand).
  - Leap year: DOY 271 vs. 270 for the same date.
  - BEDD `before_adjustment` (hand-computed 28.0 °C·d).
  - Upper-inclusive K bands.
  - GFV not configured by default.

Round 1, all commands in `/home/user/wt/wp-2.1` with `.venv` (Python 3.12, ruff 0.16.10, mypy 2.4.0):

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
    et al. (2011). Since round 2 they are no longer defaults, only candidates in `gfv.md`.
  - Whether Gladstones caps before or after the DTR adjustment (`cap_order`; the default is
    after).
  - The finer GST scheme of Jones et al. (2010), with hot 19–21 °C and very hot 21–24 °C.
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
- **`complete` still follows the plan's coverage rule** (≥ `min_season_coverage`) and therefore
  does not mean unbiased for sums. Classification of sums additionally requires
  `n_missing_days <= max_missing_days` (orchestrator decision, round 2).
- **Phenology coverage** is measured from the period start to the predicted (last) stage, not
  over the whole period, so a season with an early stage is complete without data until
  October 31.
- Huglin K outside the table or without latitude → `value = None` instead of guessing K = 1.

## Out of scope

- **Gap filling** (e.g. interpolating daily T_min/T_max over short gaps and marking the result
  `estimated`) would remove the low bias of sums with missing days. It is not done in this WP
  and is a future option.
- **Huglin K interpolation** (linear between 1.02 at 40° and 1.06 at 50°, ≈ 1.056 at 48.88° N)
  is used by some authors. It is not implemented; `k_override` can emulate it per sensor.
- **`exclude_mask` consistency** (reviewer nit): the thermal indices use only `ctx.daily`, and
  nothing checks that `ctx.daily` was built with `ctx.exclude_mask`. A reviewer probe with
  flagged 60 °C spikes gave GDD 1394 with the mask and 3351 without it. The check belongs in
  `sivin.analytics.base.IndexContext` or in the factory that builds contexts (core /
  integration WP).
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

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer session, 2026-10-05. Reviewed `git diff bcde7d9...HEAD` (4 commits).

### Gates observed

- `make lint`: `All checks passed!`, `49 files already formatted`.
- `make type`: `Success: no issues found in 31 source files`.
- `make test`: `244 passed`.
- `make cov`: `TOTAL 1295 0 220 0 100%`, every module of `sivin.analytics.thermal` at 100 % line and branch.
- Scope: every changed file is in `src/sivin/analytics/thermal/**`, `tests/analytics/thermal/**`,
  `docs/indices/{gdd_winkler,huglin,gst,bedd,budburst,gfv,gsr}.md` or this note. No shared file touched.
  No `type: ignore`, `Any`, `noqa` or `print` in the package or its tests.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `src/sivin/analytics/thermal/phenology.py:262-268`, `:451-462`, `:474` | GFV general-model critical sums 1282 / 2528 °C·d are shipped as active defaults. The `[to be verified]` marker exists only in docstrings and docs. Results carry no runtime marker (`estimated=False`, no detail), so the site would publish flowering and véraison dates from unverified constants. | fixed (round 2): `gfv` F* fields default to `None`, both or neither; default result is "not configured". 1282/2528 are only unverified candidates in `gfv.md`. Test `test_gfv_not_configured_by_default`. |
| major | `gdd.py:104`, `huglin.py:303`, `phenology.py:367` (design shared with `bedd.py`) | Sum-type indices skip incomplete days (they contribute 0), but they are still `complete=True` and get a class when coverage ≥ 0.9. Up to 10 % of the heat sum can be missing while the result is labelled complete and classified. Phenology dates are delayed by the same mechanism. | fixed (round 2): `n_missing_days` in all details; `gdd_winkler`/`huglin` classify only if `n_missing_days <= max_missing_days` (default 0); `complete` unchanged per plan; bias documented in all sum/phenology pages; gap filling under Out of scope. Probe added as `test_reviewer_probe_gap_is_not_classified`. |
| minor | `phenology.py:363-369` | Phenology returns a date `value` even when days at the start of accumulation are missing, for example a sensor deployed after March 1. The sum then lacks the spring, so the predicted date is systematically late, and only `complete=False` signals it. | fixed (round 2): `max_missing_days_at_start` (default 0); otherwise `value=None`, status "accumulation start not covered". Test `test_late_deployment_start_not_covered`. |
| minor | `docs/indices/huglin.md:66-70` | The note says package values are "about 1 % higher than legacy". That explains only the K change. The default daily mean also changed (`minmax` vs. the legacy sample mean), and that can move HI by tens of °C·d per season in either direction. | fixed (round 2): `huglin.md` now lists both legacy differences (K 1.05→1.06 ≈ +0.95 %, daily mean `sample_mean`→`minmax`, tens of °C·d either way) and how to reproduce legacy. |
| minor | `gst.py:17-26`, `docs/indices/gst.md` | Jones et al. (2010), which is cited on the page, splits the hot range into hot 19–21 °C and very hot 21–24 °C. As far as I know this is a 7-class scheme: too cool < 13, cool, intermediate, warm, hot, very hot, too hot > 24. The shipped 6 classes follow Jones (2006). Say which scheme is used, and make the Jones (2010) split available or mention it. Not certain, so verify. | fixed (round 2): `gst.md` states that the 6-class scheme of Jones (2006) is used and mentions the finer Jones et al. (2010) split [to be verified]; classes unchanged. |
| nit | `docs/indices/gst.md:22-24` | "averaging the daily values directly gives the same mean" is not exact. A mean of 7 monthly means weights 30-day and 31-day months equally per month, so it differs from the daily mean, by hundredths of a °C. Say "nearly the same". | fixed (round 2): wording changed to "nearly the same" with the reason. |
| nit | `huglin.py:170`, `huglin.md` band table | The band table as it is commonly reproduced from Huglin (1978) reads 40°01'–42° → 1.02, …, 48°01'–50° → 1.06, i.e. lower-exclusive and upper-inclusive. The code uses `[min, max)`. This only matters at exact integer latitudes and has no effect at 48.88° N. Both are fine while marked `[to be verified]`. Mention that some authors interpolate K linearly between 1.02 (40°) and 1.06 (50°), which gives ≈ 1.056 at 48.88° N. | fixed (round 2): bands upper-inclusive `(min, max]`; interpolation (≈ 1.056 at 48.88° N) mentioned and listed under Out of scope. |
| nit | `phenology.py:385-386` | The value is a DOY. In leap years every date after February is +1 DOY, so comparing DOY values across years has a 1-day artefact. The ISO dates in `details` are unaffected. Document it or add the date offset from the period start. | fixed (round 2): leap-year shift documented in all phenology pages and the class docstring; `details["date"]` added; test `test_gfv_leap_year_shifts_doy_not_date`. |
| nit | `bedd.py` / `bedd.md` | The documented consequence that a day with T_mean ≤ 10 °C and DTR > 13 °C contributes > 0 follows from the cap-after-adjustment form. Gladstones' own monthly formulation caps the mean at 19 °C before the adjustment. Consider making the order a parameter (`cap_before_adjustment`) since both variants circulate. | fixed (round 2): `cap_order` parameter (`after_adjustment` default, `before_adjustment`), documented in `bedd.md`; tests in `test_formulas.py` and `test_gst_bedd.py`. |
| nit | out of scope (`sivin.analytics.base.IndexContext`) | The thermal indices use `ctx.daily` only. Nothing checks that `ctx.daily` was built with `ctx.exclude_mask`. A probe with spikes (60 °C, flagged `SPIKE`) gave GDD 1394 with the mask and 3351 without it. This is a contract matter for the integration WP, not a defect of this WP. | deferred: recorded under Out of scope (belongs to `IndexContext` / context factory). |

#### Details and suggested fixes

1. **GFV F\* defaults (major).** I recall 1282 °C·d (flowering) and 2528 °C·d (véraison) being reported for the general GFV model of
   Parker et al. (2011), but I **cannot confirm them with certainty**. I can confirm the model structure: Spring Warming,
   T_base = 0 °C, t0 = DOY 60 (March 1), Parker et al. (2011). Values that may be wrong should not drive published dates
   silently. **Decision: unset by default.** Make `flowering_f_star_c_d` and `veraison_f_star_c_d` `float | None = None`, so
   that without them the result is `status: "not configured"` like `gsr` and `budburst`. Keep 1282 / 2528 in `gfv.md` as
   "candidate values from Parker et al. (2011) to be verified by the owner". If the owner prefers them active, set
   `estimated=True` for `gfv`, add `details["parameter_status"] = "unverified"` and log a warning once per compute.
   *Input → behaviour:* default `GfvIndex().compute(ctx)` on a synthetic year → `value=229.0, complete=True,
   estimated=False`, with no sign that the constants are unverified.
2. **Biased sums labelled complete (major).** *Probe:* a synthetic 2025 series at 1825 s steps, with May 1–19 removed
   (coverage 0.911) → `gdd_winkler = 1304 °C·d, complete=True, region_i`. The same series without the gap gives
   1394 °C·d, region II. GFV véraison moves from 08-17 to 08-31; there it was `complete=False` (0.897) only because of
   the window, and an 18-day gap would be "complete". For a mean (`gst`) skipping days is harmless. For a sum or a
   threshold date it is not. Suggested fix, smallest first:
   - (a) Add `n_missing_days` (period days without a complete day, up to the evaluation date) to `details` for every
     sum index.
   - (b) Classify a sum index only when there are no missing days, or when the missing heat is bounded, e.g. classify
     both "sum as observed" and "sum + missing_days × max daily contribution". Assign the class only if both fall in
     the same class.
   - (c) Optionally fill short gaps by interpolating daily Tmin/Tmax and mark the result `estimated`.
   The owner should choose. At the very least, the docs must state that "complete" does not mean unbiased for sums.
3. **Late-deployment phenology (minor).** *Probe:* the same series starting June 1 → `gfv value=285` (true 229),
   `complete=False`. Suggest `value=None` with `status: "accumulation start not covered"` when the first complete day is
   later than the period start plus a small tolerance.

### Science check (reviewer's knowledge; "certain" only where stated)

- **Winkler conversion:** correct. 2500/3000/3500/4000 °F·d × 5/9 = 1388.9/1666.7/1944.4/2222.2 °C·d, with no offset because these are sums
  of temperature differences. Base 50 °F = 10 °C and April 1–October 31 are correct. Inclusive upper bounds match the original
  "≤ 2500, 2501–3000, …". Hand-computed check of `test_gdd_full_season_region`: 8 °C·d × 214 = 1712 → region III. Correct.
- **Huglin formula, period and classes:** correct and consistent with Tonietto & Carbonneau (2004). The formula is
  Σ K·((T−10)+(Tx−10))/2 over April 1–September 30. The classes are HI-3 ≤ 1500 < HI-2 ≤ 1800 < HI-1 ≤ 2100 < HI+1 ≤ 2400 < HI+2 ≤ 3000 < HI+3, and the
  inclusive upper bounds are right. The English name of HI+1 is "warm temperate". T is the daily mean air temperature of station climatology. The paper
  does not prescribe sub-daily sampling, so `minmax` as the default is defensible and correctly marked.
- **Huglin K:** "K from 1.02 to 1.06 between 40° and 50°" is the statement of Tonietto & Carbonneau (2004). The 2° band table
  agrees with how it is usually reproduced from Huglin (1978), so **K = 1.06 at 48.88° N is consistent with that table**, and
  legacy 1.05 is the 46–48° value. Not certain at band edges (see nit). Keeping it `[to be verified]` is right.
- **GST:** April–October mean, and the bounds 13/15/17/19/24 °C of Jones (2006), match my knowledge. See the minor finding on the
  Jones et al. (2010) split.
- **BEDD:** the base 10 °C, the 19 °C cap (9 °C·d), the DTR band 10–13 °C and the factor 0.25 match the form quoted from Gladstones (1992) in the
  literature, summed over April–October. I am not certain whether Gladstones caps before or after the DTR and day-length adjustment, because both
  variants circulate. The worker marks all of it `[to be verified]`, which is appropriate. The day-length coefficient is off by default, which is correct, since no values
  are certain.
- **GSR:** T_base 0 °C and start DOY 91 (April 1) match Parker et al. (2020). No cultivar values are shipped. Correct.
- **Budburst:** no F\* is claimed and `estimated=True`. García de Cortázar-Atauri et al. (2009) is cited only as background. Correct.
- **References:** every citation in `docs/indices/*.md` matches the real publication as far as I know: authors, title, venue,
  volume and pages. That covers Amerine & Winkler 1944 (Hilgardia 15(6) 493–675), Huglin 1978 (C. R. Acad. Agric. Fr. 64, 1117–1126), Tonietto &
  Carbonneau 2004 (AFM 124, 81–97), Jones 2006 (Geoscience Canada Reprint Series 9; pages flagged), Jones et al. 2010 (AJEV 61(3)
  313–326), Gladstones 1992 (Winetitles), Parker et al. 2011 (AJGWR 17, 206–216), 2013 (AFM 180, 249–264), 2020 (AFM 285–286,
  107902), García de Cortázar-Atauri et al. 2009 (IJB 53, 317–326) and Winkler et al. 1974. **No DOI is given anywhere; nothing is invented.**
  I am not certain that Jones et al. (2010) reproduces the BEDD formula, but it is cited only as "for example" next to a
  `[to be verified]`.

### Tests recomputed by hand

- `test_huglin_hand_computed`: (2+6)/2·1.06 = 4.24; (−2+2)/2 = 0; (7+12)/2·1.06 = 10.07; Σ = 14.31. Correct.
- `test_gfv_both_stages_reached`: 12 °C·d/d; ⌈1282/12⌉ = 107 → March 1 + 106 d = June 15 = DOY 166; ⌈2528/12⌉ = 211 →
  September 27 = DOY 270. Correct.
- `test_bedd_hand_computed`: 2−0.5 = 1.5; max(0, −0.5) = 0; 7; min(9, 14+1.75) = 9; 8+0.75 = 8.75; Σ = 26.25. Correct.
- `test_gst_hand_computed`: 79/5 = 15.8. Correct. Huglin full season: 11·1.06·183 = 2133.78 → warm temperate. Correct.
- Legacy parity re-implementations match `vineyard_analyst.calculate_gdd` / `calculate_huglin_index` line by line.

### Other probes

The probes are in `/tmp/claude-0/review-2.1/probe.py` (synthetic data, not committed).

- **Full leap year 2024 and common year 2025:** every index ran with coverage 1.0, including the DST transition days.
- **GFV and GSR start dates in leap years:** both start on March 1 and April 1 as defined.
- **QC exclusion:** with flagged spikes and the default mask the indices are unchanged within noise. See the out-of-scope nit.

### Deviations assessment

- **No `SampleDurations`:** accepted. No WP-2.1 index is hour-based.
- **Huglin K = 1.06 by lookup, `k_override` for legacy 1.05:** accepted and well documented. The owner should decide (open question 3).
- **Huglin default `minmax` vs. legacy sample mean:** accepted, but fix the "about 1 %" wording (minor).
- **Fixed periods, complete days only (legacy differences):** accepted in principle. See major finding 2 for the
  consequence on sums.
- **Phenology value as DOY:** accepted, with ISO dates in `details`. See the leap-year nit.
- **Phenology coverage from the period start to the predicted stage:** sensible. It is the window the prediction actually
  depends on, and it avoids calling an August véraison incomplete in a running season. It inherits major finding 2 (skipped
  days delay the date) and the minor late-deployment case.
- **Huglin without K → `None`:** accepted. Better than silently using K = 1.
