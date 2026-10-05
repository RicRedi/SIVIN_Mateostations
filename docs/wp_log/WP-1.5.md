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

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
