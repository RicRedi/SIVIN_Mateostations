# WP-1.5 — Quality control and transition detection

## Summary

Package `sivin.quality` implements quality control of one sensor's `MeasurementSeries` and the
detection of office-to-vineyard deployments and service retrievals (plan §2.7). Six checks
(`missing`, `range`, `spike`, `step`, `persistence`, `sampling`) are `QualityCheck` subclasses
registered in `check_registry`, each with a frozen pydantic settings model. `DeploymentDetector`
finds change points in level and variance with a Gaussian likelihood ratio on prefix sums and
greedy binary segmentation, labels the segments indoor/outdoor with transparent rules
(`RegimeClassifier`), refines the regime boundaries, reconciles them with known deployment
times and marks indoor samples `PRE_DEPLOYMENT`. `QualityPipeline` runs screening checks →
detection → deployed checks per outdoor stretch and returns the flagged series, events and flag
counts. The method, parameters and limitations are in `docs/quality-control.md`. Everything was
verified on synthetic data only.

## Changed files

- `src/sivin/quality/__init__.py` (re-exports), `events.py`, `samples.py`, `changepoint.py`,
  `regime.py`, `segmentation.py`, `timeline.py`, `deployment.py`, `pipeline.py`
- `src/sivin/quality/checks/{__init__,base,missing,range_check,spike,step,persistence,sampling}.py`
- `tests/quality/synthetic.py` (seeded synthetic generator), `tests/quality/test_*.py`
  (5 test modules)
- `docs/quality-control.md`, `docs/wp_log/WP-1.5.md`

### Public API

```python
# sivin.quality.events
class EventKind(StrEnum): DEPLOYMENT, RETRIEVAL, STEP, GAP, IRREGULAR_SAMPLING,
    NON_POSITIVE_INTERVAL, DEPLOYMENT_MISMATCH
class Severity(StrEnum): INFO, WARNING;  class EventSource(StrEnum): DETECTED, REGISTRY
@dataclass(frozen=True, slots=True) class QualityEvent: kind, t_utc, detail, severity=INFO,
    source=DETECTED, confidence=None, end_utc=None, origin=""
@dataclass(frozen=True, slots=True) class DeploymentEvent(QualityEvent)  # kind in
    {deployment, retrieval, step}, confidence required; .type

# sivin.quality.checks
class CheckSettings(BaseModel)                    # frozen, extra="forbid"
@dataclass(frozen=True) class CheckOutcome: flags (int32, read-only), events;
    from_mask(mask, flag, events=()), count(flag)
class QualityCheck[S: CheckSettings](ABC): check_id, settings_model; __init__(settings=None);
    settings; check(series) -> CheckOutcome
class CheckRegistry: register (decorator), create(check_id, settings), get, ids, in, len
check_registry  # missing, persistence, range, sampling, spike, step
MissingValueCheck/Settings (+MissingRule), RangeCheck/Settings, SpikeCheck/Settings,
StepCheck/Settings, PersistenceCheck/Settings, SamplingCheck/Settings, classify_intervals()

# sivin.quality.deployment
class DeploymentSettings(BaseModel): change_points: ChangePointSettings, regime: RegimeSettings,
    known_tolerance_s, ignore_mask
class DeploymentDetector: __init__(settings=None, segmenter=None);
    detect(series, known_deployments=()) -> DeploymentResult
@dataclass(frozen=True) class DeploymentResult: events, pre_deployment, segments;
    transitions, outcome() -> CheckOutcome, deployed_ranges() -> ((start, stop), ...)

# sivin.quality.pipeline
class QualityPipelineSettings(BaseModel): screening_checks, deployed_checks, check_settings,
    detect_deployment, deployment
class QualityPipeline: __init__(screening, deployed, detector); from_settings(settings,
    registry=check_registry); run(series, known_deployments=()) -> QualityResult
@dataclass(frozen=True) class QualityResult: series, events, flag_counts, deployment
```

Building blocks with their own tests: `GaussianSegmentCost`, `BinarySegmentation`
(`changepoint.py`), `RegimeClassifier` (`regime.py`), `RegimeSegmenter` (`segmentation.py`),
`KnownDeploymentReconciler`, `DeploymentTimeline` (`timeline.py`), `SampleArrays` (`samples.py`).

## How it was verified

In `/home/user/wt/wp-1.5`:

- `make lint` → `All checks passed!`, `54 files already formatted`
- `make type` → `Success: no issues found in 36 source files`
- `make test` → `358 passed`
- `make cov` → `Total coverage: 99.95%` (whole package);
  `pytest --cov=sivin.quality --cov-branch tests/quality` → 1006 statements, 0 missed,
  1 partial branch, **99 %** for the code added by this WP.

Acceptance criteria (plan §4 WP-1.5 and the brief), all on synthetic data from
`tests/quality/synthetic.py` (seeded; irregular ~1825 s ± 20 s sampling; outdoor = seasonal
mean + diurnal sinusoid + AR(1) noise with anti-correlated RH; indoor ≈ 22 °C, RH ≈ 40 %):

| Criterion | Test | Result |
|---|---|---|
| office 3 days → outdoor 10 days: deployment within ±1 sample, all earlier samples `PRE_DEPLOYMENT` | `test_deployment.py::TestOfficeThenVineyard` (8 seeds × 4 season starts) | passes (the test asserts ±1; a manual run found offset 0 in all 32 cases) |
| 60 days outdoor → no deployment/retrieval (several seeds) | `TestNoTransition::test_sixty_outdoor_days_raise_no_false_alarm` (8 seeds × 4 seasons) | no event, no flag |
| outdoor → indoor (service) → outdoor → retrieval + deployment | `TestService` (8 seeds, plus a 5-phase case) | passes, both within ±1 sample |
| known deployment overrides detection; mismatch warns | `TestKnownDeployments` | passes |
| cold front (−8 °C in 2 h, stays outdoors) is not a transition | `TestNoTransition::test_cold_front_is_not_a_transition` (8 seeds) | passes |
| each check has positive and negative tests incl. irregular sampling | `test_checks.py` | passes |
| pipeline order (deployment jump is not a spike/step; indoor data not checked) | `test_pipeline.py::TestPipeline` | passes |

Additionally checked manually (not a committed test): one year of synthetic outdoor data after
4 office days (17 469 samples, 3 seeds) → exactly one deployment, no other flags, ~0.13 s per
pipeline run.

## What did not work / what was not verified

- **No real data.** Thresholds are project defaults and are not tuned; the detector and the
  checks were never run on a real export (Q1) and never compared with real deployment dates
  (Q3). The synthetic generator is my own model of the signals, not a fit to real data.
- The first implementation placed a retrieval about 10 h late when an earlier weather change
  point lay less than `min_segment_s` before it (the minimum segment duration blocked the exact
  split). Fixed by the boundary refinement step in `RegimeSegmenter`; covered by the service
  tests.
- Physical temperature limits (−50/60 °C), the climatological limits for South Moravia
  (−30/42 °C) and the assumed sensor resolutions (0.1 °C, 1 %) are not verified against the
  sensor data sheet or regional station records.
- Literature: the range/step/persistence methodology is attributed to Zahumenský (2004) as in
  the plan; no numeric threshold is quoted from it, because I could not check the guideline's
  tables here. DOIs are not given (no access to doi.org); all marked `[DOI not verified]`.

## Decisions and deviations from the brief

1. **Two check lists instead of one.** `QualityPipelineSettings` has `screening_checks` (whole
   series, before detection: `missing`, `sampling`, `range`) and `deployed_checks` (per outdoor
   stretch, after detection: `spike`, `step`, `persistence`). The brief asked for "a list of
   enabled checks" and "deployment detection first"; detection first would let a gross error
   (e.g. −999) fake a regime change, so missing/range/sampling run before it and the detector
   ignores `MISSING`/`OUT_OF_RANGE` rows. Indoor data are still never judged by outdoor
   expectations.
2. **`step` events come from `StepCheck`, not from the detector.** `DeploymentEvent` supports the
   `step` type, but the detector reports only `deployment`/`retrieval`; level shifts within a
   regime are found by `StepCheck` (`QualityEvent(kind=STEP)`), so a step is not reported twice.
3. **`MISSING` rule defaults to `all`** (row flagged only when both variables are `NaN`) because
   the `qc` field is shared by temperature and humidity; `rule: any` is available.
4. **Sampling:** intervals that are whole multiples of 1825 s (missed samples) are regular; only
   off-grid intervals get `TIMESTAMP_SUSPECT`. Gaps produce events but no flag (no sample is
   wrong). Non-positive intervals cannot occur in a valid `MeasurementSeries`; the rule is in
   `classify_intervals` and tested on raw arrays.
5. **Known deployments:** only deployments are overridden (the interface has no retrieval times);
   detected retrievals are kept, an unmatched detected deployment becomes a warning and is not
   applied, and with known times the sensor counts as indoors before the first one (rules in
   `docs/quality-control.md`).
6. **Binary segmentation** is greedy by gain with a BIC-like penalty and a cap
   (`max_change_points = 50`), followed by boundary refinement; PELT (Killick et al. 2012) is
   cited for the method family only.
7. Module `checks/range_check.py` instead of `checks/range.py` (avoids shadowing the builtin name
   in imports); `segmentation.py`, `changepoint.py`, `regime.py`, `timeline.py`, `samples.py`
   split from `deployment.py` to keep classes small (plan §1.2).

## Out of scope

- `src/sivin/core/flags.py` / plan §2.5: a single `qc` field per row means a humidity finding
  excludes the temperature of the row (already raised as open question 5 in WP-0.1). Proposal:
  per-variable flag columns (`qc_temp`, `qc_rh`) or a variable mask in a future contract change.
- `src/sivin/analytics/base.py` (`IndexRegistry`) and `checks/base.py` (`CheckRegistry`) repeat
  the same registry logic; the generic `Registry[T]` proposed in the WP-0.1 note would serve
  both (and `ExportParser` in WP-1.2).
- Integration (WP-1.7 / WP-3.2): add `quality: QualityPipelineSettings` to `SivinConfig`
  (proposed YAML in `docs/quality-control.md` → *Configuration*), pass
  `placement.from` of the registry (WP-1.1) as `known_deployments`, write `QualityResult.events`
  to `data/derived/events/<sensor_id>.json` and the site contract (`type`, `t`, `source`,
  `confidence`, `detail`), and log `deployment_mismatch` warnings into the run summary
  (`data/runs/*.jsonl`). Proposed CLI command: `sivin qc [--sensor ID] [--dry-run]` that runs
  the pipeline on the stored series and prints the flag counts and events.
- `SamplingSettings.expected_interval_s` defaults to `LEGACY_SAMPLING_INTERVAL_S`;
  once wired, it should be taken from `time.expected_interval_s` to keep one source.

## Open questions for the owner

1. **Q3:** known deployment dates and any service visits per sensor are needed to tune
   `known_tolerance_s`, the comfort band and the regime thresholds. Was any sensor brought back
   to the office after its first deployment?
2. Is a minimum detectable service stay of one day acceptable (`min_segment_s`), or are short
   visits (hours) common?
3. Climatological temperature limits for South Moravia: confirm or provide (default −30/42 °C),
   and the temperature/humidity resolution of the sensors (assumed 0.1 °C and 1 %).
4. Should a detected redeployment that is missing in the registry be applied (data accepted)
   instead of only warned about (data stay `PRE_DEPLOYMENT` until the next known deployment)?

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer agent, 2026-10-05, base `bcde7d9`, head `750ddbc`.

### Gates (run by the reviewer in `/home/user/wt/wp-1.5`)

- `make lint`: `All checks passed!`, `54 files already formatted`
- `make type`: `Success: no issues found in 36 source files`
- `make test`: `358 passed`
- `make cov`: `Total coverage: 99.95%`; `pytest --cov=sivin.quality --cov-branch tests/quality`:
  1006 statements, 0 missed, 1 partial branch (99 %), 177 passed.
- Scope: `git diff --stat bcde7d9...HEAD` touches only `src/sivin/quality/**`,
  `tests/quality/**`, `docs/quality-control.md` and this note. No shared file changed.

### How the review was done

I wrote my own SYNTHETIC generator outside the repo (`/tmp/claude-0/review-1.5/gen.py`). It does
not reuse `tests/quality/synthetic.py`, and it adds what that generator lacks:

- a seasonal mean (Jan ≈ −1.5 °C, Jul ≈ 20.5 °C) plus a daily AR(1) synoptic anomaly
  (σ 3.5 °C, φ 0.7);
- Markov day-to-day cloudiness that scales the daily range (clear: 8 °C in winter to 15 °C in
  summer; overcast: a quarter of that);
- daily mean RH that depends on season and cloudiness, with a diurnal RH cycle anti-correlated
  with temperature;
- optional episodes: fog/inversion (RH ≈ 99 %), heat wave (+6 °C), fronts (−7 to −10 °C over
  0.5–2 h), radiative frost nights;
- an office with a weekday heating cycle in Europe/Prague local time, thermal inertia, and
  variants (unheated, warm, humid, sunny window sill), plus a car phase;
- sampling at 1825 s with clock drift (2·10⁻⁴), jitter (σ 8 s) and values quantised to 0.1.

The whole pipeline ran with default settings. "Correct" means exactly the expected transitions,
each within ±1 sample of the truth. These numbers come from my model, not from real data.

### Detection rate (correct runs / seeds)

| Scenario | winter (5 Jan) | spring (1 Apr) | summer (1 Jul) | autumn (1 Oct) |
|---|---|---|---|---|
| office 6 h → outdoor 20 d (n=20) | 0/20 (no event) | 0/20 | 3/20 | 0/20 |
| office 1 d → outdoor 20 d (n=20) | 20/20 | 20/20 | **16/20** (4 extra retrieval+deployment) | 20/20 |
| office 3 d → outdoor 20 d (n=20) | 20/20 | 20/20 | 19/20 (one 17 samples late) | 20/20 |
| office 14 d → outdoor 20 d (n=20) | 20/20 | 20/20 | **17/20** | 20/20 |
| deploy hour 06/10/18/22 UTC, office 3 d (n=15 each) | 15/15 all | 15/15 all | **10–12/15** | 15/15 all |
| service 3 h (n=15) | 0/15 | 0/15 | 0/15 | 0/15 |
| service 12 h | 0/15 | 0/15 | 1/15 | 0/15 |
| service 1 d | 13/15 | 8/15 | 11/15 | 13/15 |
| service 2 d | 15/15 | 15/15 | 14/15 | 15/15 |
| service 5 d | 15/15 | 15/15 | 12/15 | 15/15 |
| gap −6 h/+0, 0/+6 h, ±12 h, −48 h, +48 h around the boundary | 15/15 each | 15/15 each | 12–13/15 | 15/15 each |
| car 1.5 h at 35 °C between office and vineyard | boundary at car start (−3 or −1 samples vs arrival) | −3 | −3, 2 wrong | −3 |
| car 1.5 h at 45 / 55 °C (rows `OUT_OF_RANGE`, skipped) | 0 offset | 0 | 0, 2 wrong | 0 |
| overcast winter deployment, daily range ≈ 2 °C (5 Jan, 1 Dec) | 15/15, 15/15 | | | |
| **overcast summer deployment, daily range ≈ 3.8 °C, RH median ≈ 72 %** | | | **0/15** (14/15 with extra retrieval/deployment pairs) | |

Office variants (office 3 d → outdoor 15 d, n=15):

| Office | Season | Correct | Outcome |
|---|---|---|---|
| cool 16 °C | spring | 15/15 | |
| humid 22 °C, RH 68 % | June | 15/15 | |
| warm 27 °C, RH 55 % | July | 12/15 | 3 × extra retrieval+deployment |
| **unheated 12 °C** | January | **0/15** | no event; the office rows are not flagged |
| **hot 30 °C** | July | **0/15** | no event (13/15) |
| **sunny window sill, daily range 6 °C** | April | **0/15** | no event |

Multi-year runs (office 3 d → outdoor, with a 3-day service in the last year, n=6):

| Length | Correct | Runtime per series (median) |
|---|---|---|
| 1 y (17 422 rows) | 6/6 | 0.14 s |
| 3 y (51 982 rows) | **4/6** | 0.37 s |
| 5 y (86 542 rows) | **2/6** (the service is missed) | 0.66 s |
| 5 y with `max_change_points=200` | 6/6 | 0.73 s |
| 5 y with `max_change_points=1000` | 3/6 (false retrieval/deployment pairs) | 1.26 s |

### False alarms (outdoor only, no transition in the data)

| Scenario | Runs | False transitions | Other flags per sensor-year (mean / max) |
|---|---|---|---|
| plain year, 365 d from 1 Jan | 30 seeds | 2 events in 1/30 seeds (June), 0.07 per sensor-year; up to 192 rows (1.1 %) `PRE_DEPLOYMENT` | SPIKE 0, STEP 0, STUCK 0, OUT_OF_RANGE 0, TIMESTAMP_SUSPECT 0 |
| year with fog (3 episodes, 2–5 d), heat wave (+6 °C, 10 d), 3 fronts, frost nights | 30 seeds | 4 events in 2/30 seeds (June, July, one inside the heat wave), 0.13 per sensor-year; up to 196 rows `PRE_DEPLOYMENT` | STEP 1.5 / 3 (all at the −10 °C/1 h front), STUCK 0.4 / 13 (temperature constant within 0.05 °C for ≥ 6 h in fog), OUT_OF_RANGE 0, SPIKE 0; frost nights and the −8 °C/2 h front not flagged |
| office 3 d → 20 d outdoor in Jun/Jul/Aug, mixed and overcast weather | 180 runs | 377 false transitions | — |

Confidence of transitions in the summer runs: true deployments have a 5th percentile of 0.09
(median 1.0); false ones a median of 0.09 and a 95th percentile of 0.31. A threshold of 0.5
would keep 65 % of the true transitions and 2 % of the false ones. Confidence carries
information, but it is not a probability.

### Mechanics verified

- `GaussianSegmentCost.cost` against a brute-force `m·Σ ln(var_ML + floor)` on 300 random inputs
  (n ≤ 24, 1–2 variables, some quantised to zero variance): largest relative error 3.8·10⁻¹³.
- `split_gains` equals C(a,b) − C(a,τ) − C(τ,b).
- With a negligible floor, G(τ) = 60.37791761331 and 2 ln Λ computed directly from the Gaussian
  log-likelihoods = 60.37791761334.
- The first split of binary segmentation equals the brute-force argmax.
- Numerical stability with a 10⁶ offset is fine: a segment far from the global mean is off by a
  relative 3·10⁻⁹.
- Edge cases run without error: empty series, 1 row, 5 rows, all `NaN`, all out of range,
  temperature only. A naive known time raises `ValueError`.
- Citations checked: Killick et al. 2012 (JASA 107(500) 1590–1598), Page 1954
  (Biometrika 41(1/2) 100–115), Schwarz 1978 (Ann. Stat. 6(2) 461–464) and Scott & Knott 1974
  (Biometrics 30(3) 507–512, the usual attribution of binary segmentation) are correct as far as
  I know. Zahumenský (2004) is cited for methodology only. No numeric threshold is attributed to
  WMO or Zahumenský; all numbers are marked as project defaults. Nothing was found that is
  presented as from a source that does not contain it.
- Readability: the regime rule (three linear ramps and a minimum) is transparent and documented
  with formulas in both the code and the docs. Classes are small and single-purpose; checks are
  extended through a registry. Engineering standards met.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `src/sivin/quality/regime.py:236-267` | False retrievals on cloudy summer days (absolute rules) | open |
| major | `src/sivin/quality/regime.py:191-213`, `segmentation.py:346` | Plan §2.7 step 2 (relative confirmation) not implemented, deviation not declared | open |
| major | `src/sivin/quality/deployment.py:68-76`, `changepoint.py:197` | Fixed change-point cap makes the result depend on series length | open |
| major | `src/sivin/quality/timeline.py:458-470`, `deployment.py:281` | Known deployments discard detected redeployments; outdoor data excluded permanently | open |
| minor | `src/sivin/quality/regime.py:213`, `deployment.py:340`, `docs/quality-control.md:266-271` | Confidence is an uncalibrated rule-score margin, not a probability | open |
| minor | `src/sivin/quality/timeline.py:463-468` | Every relocation produces a `deployment_mismatch` warning | open |
| minor | `src/sivin/quality/segmentation.py:355-368` | Transport (car) rows left as vineyard data | open |
| minor | `src/sivin/quality/deployment.py:347-356` | Event detail compares whole merged regimes, so the numbers can mislead | open |
| minor | `src/sivin/quality/checks/step.py:270-281` | A fast convective front is flagged `STEP` | open |
| minor | `src/sivin/quality/checks/persistence.py:404-417` | Long isothermal fog can be flagged `STUCK` | open |
| minor | `tests/quality/synthetic.py:36-45`, `tests/quality/test_deployment.py` | Test generator has no cloud or synoptic variability, so tests miss the M1–M3 failures | open |
| nit | `docs/quality-control.md:340-342` | Service visits shorter than a day go undetected and their rows count as vineyard data | open |

**M1. False retrievals on cloudy summer days (absolute rules).** A cloudy-but-dry summer day
(median 18–23 °C, daily spread 3.2–4.3 °C, RH median 69–72 %) scores S = 0.5–0.68 and is
labelled indoor. The result is a false retrieval/deployment pair, and 1–4 days of vineyard data
get `PRE_DEPLOYMENT`.

- Numbers: overcast-summer deployment 0/15 correct; summer correct rate 80–95 % against 100 % in
  the other seasons; 0.07–0.13 false transitions per sensor-year (see M3 for why this depends on
  series length).
- Fix: confirm a candidate indoor segment relative to its outdoor neighbours (see M2), for
  example a jump in level or RH at both boundaries, or the ratio of spreads.
- Also add a sub-daily variability feature: office hour-to-hour noise is about 0.1 °C, while
  outdoor noise is larger even under overcast.
- Optionally do not apply a transition below a configurable confidence and emit a warning
  instead.

**M2. Plan §2.7 step 2 (relative confirmation) not implemented; deviation not declared.**
§2.7 step 2 says the candidate is confirmed by the ratio of daily amplitude after/before *and*
the distance from the comfort band. The implementation labels each segment on absolute
thresholds only; the ratio appears only in the event text. This deviation is not listed among
the deviations.

- Effect: an unheated office (12 °C), a hot office (30 °C) or a window sill gives 0/15 detected
  deployments. The office rows then stay unflagged and enter the indices, which is the core
  owner requirement.
- Fix: implement the ratio rule from §2.7, for example accept a boundary when the
  spread ratio ≥ k and one side lies in or near the band. Alternatively, declare and justify the
  deviation and let the owner decide.

**M3. Fixed change-point cap makes the result depend on series length.**
`max_change_points = 50` does not depend on series length. Weather change points exhaust the
cap on long series.

- A 3-day service in the last year is found in 6/6 runs on 1 year, 4/6 on 3 years and 2/6 on
  5 years.
- Raising the cap to 1000 brings back the M1 false alarms (3/6).
- The store keeps full multi-year histories (§2.5), so results will change as data accumulate.
  The 1-year false-alarm rate is low partly because of this cap.
- Fix: scale the cap with duration (e.g. per 30 days), or run the detector on bounded windows or
  incrementally. Add a multi-year test.

**M4. Known deployments discard detected redeployments; outdoor data excluded permanently.**
A detected deployment that is not in the registry is discarded, while the detected retrieval
before it is kept.

- After a service visit that is missing from the registry (the normal case, since returning to
  the same placement adds no `placement.from`), 100 % of the later outdoor rows become
  `PRE_DEPLOYMENT`. This held for 2-day and 5-day visits in 15/15 runs per season, and for
  53–93 % of rows with a 1-day visit.
- If only a later relocation is known, earlier outdoor rows are lost: 947 of 1420 in my test.
- The worker documented this and raised it as owner question Q4, but the default destroys data.
- Fix: apply a detected deployment that closes a detected retrieval, and only warn. Or apply
  rule 6 ("indoor before the first known time") only up to the nearest detected deployment.
  The final choice is the owner's.

**Minor findings.**

- **Confidence is a rule-score margin.** It is min(|2S−1|) of the two regimes, not calibrated
  and not a probability. True summer deployments can get 0.04. Say so in the docs and the site
  contract.
- **Relocation warnings.** With known times for a relocation (office → A → car 1 h → B), each
  run gives a `deployment_mismatch` warning (15/15) because no indoor period precedes the second
  placement. That is noise in every run summary. Do not warn for a known time that follows an
  outdoor regime, or report it as information.
- **Car transport.** A 1.5 h car phase at 35 °C ends up in the vineyard stretch: the boundary is
  placed at the car start (−3 samples). §2.7 counts transport as `PRE_DEPLOYMENT`. Consider
  snapping the boundary to the start of the outdoor-like diurnal behaviour, or flagging a short
  transient.
- **Misleading event detail.** The detail compares the medians of whole merged regimes. A July
  false retrieval reads "step +15.0 °C" against a January–July outdoor median. Use windows next
  to the boundary (e.g. ±1 day).
- **Fast fronts flagged `STEP`.** A −10 °C/1 h front gets `STEP` (informative only, 1–3 rows per
  year). A −8 °C/2 h front and frost nights are not flagged. Acceptable but undocumented.
- **Fog flagged `STUCK`.** Temperature constant within 0.05 °C for ≥ 6 h in fog/inversion gets
  `STUCK` and is excluded (13 rows in 1 of 30 seeds; depends on my generator). Document it, or
  relax the rule when RH is saturated.
- **Weak test generator.** The worker's generator uses a constant 10 °C daily range and constant
  mean RH, with no cloud or synoptic variability. The 60-day false-alarm and season tests
  therefore never meet low-amplitude summer days. Add cloudiness to the generator.

**Nit.** Service visits shorter than `min_segment_s`: 0/15 for 3 h and 12 h visits. These rows
are counted as vineyard data. This is documented and raised as owner question Q2.

### Deviations assessment

1. **Screening checks before detection: accepted.** Excluding `MISSING`/`OUT_OF_RANGE` stops a
   sentinel from faking a regime (car at 45–55 °C: boundary exact). Range limits on indoor data
   do no harm. Residual risk: because `qc` is per row, an RH fault that flags whole rows
   `OUT_OF_RANGE` also hides temperature from the detector. That is the known contract
   limitation, already raised.
2. **`step` events from `StepCheck` only: accepted.**
3. **`MISSING` rule `all`: accepted** (shared `qc` field).
4. **Sampling (multiples of Δt₀ regular, gaps as events only): accepted.** Jittered and drifting
   sampling gave no `TIMESTAMP_SUSPECT` over 30 synthetic years.
5. **Known deployments override deployments only: not accepted as default** (finding M4).
6. **Greedy binary segmentation with BIC penalty and cap: math verified.** The fixed cap is
   finding M3.
7. **Module split and `range_check.py`: accepted.**

Not reviewed: behaviour on real exports (none available). All rates above depend on my
synthetic model, especially the RH of cloudy summer days. They show failure modes; they are not
field error rates.
