# WP-1.5 — Quality control and transition detection

## Summary

Package `sivin.quality` implements quality control of one sensor's `MeasurementSeries` and the
detection of office-to-vineyard deployments and service retrievals (plan §2.7). Six checks
(`missing`, `range`, `spike`, `step`, `persistence`, `sampling`) are `QualityCheck` subclasses
registered in `check_registry`, each with a frozen pydantic settings model. `DeploymentDetector`
finds change points in level and variance (Gaussian likelihood ratio on prefix sums, binary
segmentation) **locally in epoch-anchored 30-day windows**, groups indoor-like segments
(absolute rules) into candidate indoor runs, places their boundaries exactly, moves a transport
transient to the indoor side and **confirms each boundary by the relative contrast of local
windows on both sides** (plan §2.7 step 2). Only confirmed office stays and confirmed
retrieval+redeployment pairs are flagged `PRE_DEPLOYMENT`; incomplete evidence produces a
warning. Known deployment times override detection only near themselves. `QualityPipeline`
runs screening checks → detection → deployed checks per outdoor stretch. Method, parameters and
limitations are in `docs/quality-control.md`. Everything was verified on synthetic data only.

Round 2 (after review round 1) reworked the detector for findings M1–M4 and all minors; see
*Round 2 changes* and the Status column of the review table.

## Changed files

- `src/sivin/quality/__init__.py` (re-exports), `events.py`, `samples.py`, `changepoint.py`,
  `windows.py`, `regime.py`, `contrast.py`, `boundaries.py`, `segmentation.py`, `timeline.py`,
  `deployment.py`, `pipeline.py`
- `src/sivin/quality/checks/{__init__,base,missing,range_check,spike,step,persistence,sampling}.py`
- `tests/quality/synthetic.py` (seeded synthetic generator), `tests/quality/test_*.py`
  (5 test modules)
- `docs/quality-control.md`, `docs/wp_log/WP-1.5.md`
- Merge commit of `wp/0.1-foundation` (34f6f18) into this branch (no conflicts).

### Public API

```python
# sivin.quality.events
class EventKind(StrEnum): DEPLOYMENT, RETRIEVAL, STEP, GAP, IRREGULAR_SAMPLING,
    NON_POSITIVE_INTERVAL, DEPLOYMENT_MISMATCH, UNCONFIRMED_TRANSITION
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
    contrast: ContrastSettings, transport: TransportSettings, known_tolerance_s, ignore_mask
class DeploymentDetector: __init__(settings=None, segmenter=None);
    detect(series, known_deployments=()) -> DeploymentResult
@dataclass(frozen=True) class DeploymentResult: events, pre_deployment, segments;
    transitions, warnings, outcome() -> CheckOutcome, deployed_ranges() -> ((start, stop), ...)

# sivin.quality.pipeline
class QualityPipelineSettings(BaseModel): screening_checks, deployed_checks, check_settings,
    detect_deployment, deployment
class QualityPipeline: __init__(screening, deployed, detector); from_settings(settings,
    registry=check_registry); run(series, known_deployments=()) -> QualityResult
@dataclass(frozen=True) class QualityResult: series, events, flag_counts, deployment
```

Building blocks with their own tests: `GaussianSegmentCost`, `BinarySegmentation`
(`changepoint.py`), `WindowedChangePoints` (`windows.py`), `RegimeClassifier`,
`IndoorAssessment`, `WindowFeatures` (`regime.py`), `TransitionContrast`, `ContrastVerdict`
(`contrast.py`), `BoundaryRefiner`, `TransportTrimmer` (`boundaries.py`), `RegimeSegmenter`,
`IndoorRun`, `Boundary` (`segmentation.py`), `KnownDeploymentReconciler`, `IndoorInterval`,
`indoor_mask` (`timeline.py`), `SampleArrays` (`samples.py`).

## How it was verified

In `/home/user/wt/wp-1.5` (after merging `wp/0.1-foundation` 34f6f18):

- `make lint` → `All checks passed!`, `57 files already formatted`
- `make type` → `Success: no issues found in 39 source files`
- `make test` → `419 passed`
- `make cov` → `Total coverage: 99.76%` (whole package);
  `pytest --cov=sivin.quality --cov-branch tests/quality` → 1298 statements, 3 missed,
  3 partial branches, **99 %** for the code of this WP (229 tests).

Acceptance tests (all synthetic, `tests/quality/synthetic.py`, which now has day-to-day Markov
cloudiness, a synoptic anomaly, seasonal and cloud-dependent humidity, fog, heat waves, fronts,
a car phase and office variants 12/16/22/27/30 °C and humid):

| Criterion | Test | Result |
|---|---|---|
| office 3 d → outdoor 10 d: deployment ±1 sample, all earlier samples `PRE_DEPLOYMENT` | `TestOfficeThenVineyard::test_deployment_found_within_one_sample` (6 seeds × 4 seasons) | passes |
| office variants (unheated 12 °C, cool 16 °C, warm 27 °C, hot 30 °C, humid) | `test_office_variants` (4 seeds each) | passes |
| overcast deployment (winter, summer) | `test_overcast_deployment` | passes |
| car transport is `PRE_DEPLOYMENT`, deployment at arrival | `test_car_transport_counts_as_pre_deployment` | passes |
| gaps of 12/12 h, 48 h before, 48 h after the boundary | `TestGapsAtTheBoundary` | passes |
| 60 days outdoor: no event, several seeds and seasons | `TestNoTransition::test_sixty_outdoor_days_raise_no_false_alarm` | passes |
| cloudy summer false-alarm rate ≤ 0.1 per sensor-year | `test_cloudy_summer_false_alarm_rate` (10.1 sensor-years) | 0 false transitions |
| year with fog, heat wave, fronts: no transition | `test_year_with_fog_heat_wave_and_fronts` | passes |
| cold front is not a transition; sensor only in the office is not flagged | `TestNoTransition` | passes |
| service visit → retrieval + deployment | `TestService::test_retrieval_and_redeployment` (6 seeds × 4 seasons) | passes |
| retrieval without redeployment only warns, no flags | `test_retrieval_without_redeployment_only_warns` | passes |
| same service visit found identically in 1-, 3- and 5-year series | `TestLongSeries` | identical events |
| known time overrides within tolerance; mismatch warns and keeps detection; known time inside office stay ends it; unknown service + known dates applied with warning; relocation without warning; only later relocation known; known time inside a service visit; before the data | `TestKnownDeployments` | passes |
| each check positive/negative incl. irregular sampling, fast front not STEP, fog not STUCK | `test_checks.py` | passes |

### Measured on the reviewer's independent generator (round 2)

The reviewer's scripts `/tmp/claude-0/review-1.5/s1.py`–`s8.py` were re-run unchanged against
this branch (default settings; "correct" = exactly the expected transitions, each within ±1
sample). These are synthetic rates from the reviewer's model, not field error rates.

| Scenario (n) | winter | spring | summer | autumn | round 1 |
|---|---|---|---|---|---|
| office 6 h → outdoor 20 d (20) | 0/20 | 0/20 | 0/20 | 0/20 | 0, 0, 3, 0 /20 |
| office 1 d → outdoor 20 d (20) | 20/20 | 20/20 | **20/20** | 20/20 | summer 16/20 |
| office 3 d → outdoor 20 d (20) | 20/20 | 20/20 | 20/20 | 20/20 | summer 19/20 |
| office 14 d → outdoor 20 d (20) | 20/20 | 20/20 | 19/20 (one at +3) | 20/20 | summer 17/20 |
| deploy hour 06/10/18/22 UTC, office 3 d (15 each) | 15/15 all | 15/15 all | 15, 14, 15, 15 | 15/15 all | summer 10–12/15 |
| service 3 h / 12 h (15) | 0/15 | 0/15 | 0/15 | 0/15 | 0–1/15 (Q2) |
| service 1 d (15) | 14/15 | 14/15 | 9/15 | 15/15 | 13, 8, 11, 13 |
| service 2 d (15) | 15/15 | 15/15 | 14/15 | 15/15 | 15, 15, 14, 15 |
| service 5 d (15) | 15/15 | 15/15 | 13/15 | 14/15 | 15, 15, 12, 15 |
| gaps −6/+0, 0/+6, ±12, −48, +48 h (15 each) | 15/15 each | 15/15 each | 15/15 each | 15/15 each | summer 12–13/15 |
| car 1.5 h at 35 °C: offset vs arrival | 0 | 0 | 0 or −3 | 0 | −3 everywhere |
| car 1.5 h at 45/55 °C (`OUT_OF_RANGE`) | 0 | 0 or +2 | 0 | 0 | 0 |
| overcast winter deployment 5 Jan / 1 Dec (15) | 15/15, 15/15 | | | | 15/15, 15/15 |
| **overcast summer deployment (15)** | | | **15/15** | | 0/15 |

| Office variant, office 3 d → outdoor 15 d (15) | Correct | Round 1 |
|---|---|---|
| cool 16 °C, spring | 15/15 | 15/15 |
| humid 22 °C, RH 68 %, June | 15/15 | 15/15 |
| warm 27 °C, RH 55 %, July | 15/15 | 12/15 |
| **unheated 12 °C, January** | **15/15** | 0/15 |
| **hot 30 °C, July** | **15/15** | 0/15 |
| sunny window sill, daily range 6 °C, April | 0/15 (no event, documented limitation) | 0/15 |

| False alarms (no transition in the data) | Runs | False transitions | Other |
|---|---|---|---|
| plain year from 1 Jan | 30 seeds | **0** (round 1: 0.07 per sensor-year) | `PRE_DEPLOYMENT` 0 rows; SPIKE/STEP/STUCK/OUT_OF_RANGE/TIMESTAMP_SUSPECT 0 |
| year with fog, heat wave, fronts, frost nights | 30 seeds | **0** (round 1: 0.13 per sensor-year) | STEP 0.4 rows/yr, max 1 (the −7 °C/0.5 h front, one interval; round 1: 1.5, max 3); STUCK 0 (round 1: 0.4, max 13) |
| **office 3 d → outdoor 20 d, Jun/Jul/Aug, mixed and overcast** | 180 runs | **0** (round 1: 377); 180/180 true deployments | confidence of true deployments: min 0.5, P5 0.75, median 0.75 |
| summer only (Jun–Aug, 92 d), own generator in the reviewer's model, mixed and overcast | 60 runs = 15.1 sensor-years | **0 per sensor-year** | — |

| Multi-year (office 3 d → outdoor, 3-day service in the last year, n=6) | Correct | Runtime per series (median) | Round 1 |
|---|---|---|---|
| 1 y (17 422 rows) | 6/6 | 0.19 s | 6/6 |
| 3 y (51 982 rows) | 6/6 | 0.55–0.60 s | 4/6 |
| 5 y (86 542 rows) | 6/6 | 0.75–0.83 s | 2/6 |

| Known dates (reviewer scenarios B, C, s8) | Result | Round 1 |
|---|---|---|
| known = first deployment, service of 1/2/5 d not in registry: 2nd outdoor stretch `PRE_DEPLOYMENT` | 0 % in all seasons; warning in every run where the service was detected | 100 % |
| relocation office → A → car 1 h → B, both known | 0 mismatch warnings, 0 % outdoor rows flagged | 15/15 warned |
| only a later relocation known | 0 of 1420 outdoor rows flagged (round 1: 947); office rows still flagged | |

Edge cases (s8): empty, 1 row, 5 rows, all NaN, all out of range, temperature only — no error.

## Round 2 changes

- **M2/M1 — relative confirmation (`contrast.py`).** A boundary is confirmed only if the indoor
  window is indoor-like (absolute rules, `regime.py`: room band 5–35 °C, daily spread ≤ 4 °C,
  median RH ≤ 75 %, daily RH spread ≤ 8 %), the outdoor window is not, and at least 2 of 4
  relative votes hold on local 2-day windows next to the boundary: spread ratio ≥ 2, level
  difference ≥ 5 °C, outdoor RH ≥ indoor + 15 %, RH-spread ratio ≥ 2. The narrow comfort band
  (18–27 °C) was replaced by the wide room band plus the steady-humidity criterion, so that 12 °C
  and 30 °C offices are found and cloudy summer days (RH follows the daily cycle) are not.
- **M3 — local search (`windows.py`).** Binary segmentation runs in 30-day windows every
  15 days on an epoch-anchored grid; results are pooled. Cap 30 per window. The result no
  longer depends on the series length (test `TestLongSeries`).
- **M4 — known dates (`timeline.py`).** Known times override detection only within the
  tolerance; unmatched detected deployments (including service pairs) are applied with a
  warning; a known time inside the detected office stay ends it; a later known time without a
  matching detection is a relocation (info, no warning, no flags). Answers Q4 with the
  orchestrator's default.
- **Applying runs (`segmentation.py`).** A service visit counts only with a confirmed retrieval
  *and* redeployment; a retrieval without redeployment, a half-confirmed run or a run covering
  all data is never flagged (`unconfirmed_transition` warning where a boundary was confirmed).
- **Transport (`boundaries.py`).** Samples next to the boundary outside both the indoor and the
  outdoor reference range (± 3 °C), for at most 3 h, move to the indoor side. Indoor windows keep
  3 h distance from the boundary.
- **Boundary refinement across gaps.** The refinement radius is measured from the samples on
  both sides of the boundary (a 12–48 h gap at the boundary previously broke detection after the
  rework; found with the reviewer's scenario H and fixed).
- **Event detail** comes from the local windows and lists the votes, e.g.
  `indoor → outdoor: level -15.3 °C, daily spread x3.4, humidity +41 %, votes 4/4`.
- **Confidence** is the share of relative votes that hold (0.5–1 for confirmed transitions);
  documented as a heuristic score, not a calibrated probability.
- **STEP:** new `max_adjacent_fraction = 0.4`; a −10 °C/1 h front (two −5 °C intervals) is no
  longer a step. A front within one interval still is (documented).
- **STUCK:** temperature duration 12 h (was 6 h); a run with ≥ 50 % samples at RH ≥ 97 % is exempt
  for both variables (fog, inversion).
- **Generator:** see the acceptance table above.

## What did not work / what was not verified

- **No real data.** Thresholds are project defaults and are not tuned; the detector and the
  checks were never run on a real export (Q1) and never compared with real deployment dates
  (Q3). Both synthetic generators are models of the signals, not fits to real data. In
  particular the steady-humidity rule (indoor daily RH spread ≤ 8 %) relies on the assumption
  that office humidity is steady and that outdoor humidity follows the daily cycle even under
  overcast skies; that must be checked on real data.
- Service visits of about one day are found in 9–15 of 15 runs; shorter visits not at all
  (Q2). The sunny-window-sill office (daily range 6 °C) is not detected.
- Physical temperature limits (−50/60 °C), the climatological limits for South Moravia
  (−30/42 °C) and the assumed sensor resolutions (0.1 °C, 1 %) are not verified against the
  sensor data sheet or regional station records.
- Literature: the range/step/persistence methodology is attributed to Zahumenský (2004) as in
  the plan; no numeric threshold is quoted from it. DOIs are not given (no access to doi.org);
  all marked `[DOI not verified]`.

## Decisions and deviations from the brief

1. **Two check lists instead of one** (`screening_checks` before detection, `deployed_checks`
   per outdoor stretch after it). Accepted by the reviewer in round 1.
2. **`step` events come from `StepCheck`, not from the detector.** Accepted in round 1.
3. **`MISSING` rule defaults to `all`.** Accepted in round 1.
4. **Sampling:** whole multiples of 1825 s are regular; gaps are events only. Accepted.
5. **Known deployments** override detection only near themselves (round 2, orchestrator
   decision on M4; rules in `docs/quality-control.md`).
6. **Plan §2.7 step 2** names the distance from the "comfort band"; it is implemented as a wide
   room band (5–35 °C) in the absolute rules plus the relative votes, because an office outside
   the comfort band must be detectable (orchestrator decision on M2).
7. **A sensor whose data are all indoor is not flagged** (no contrast to confirm anything; it
   is flagged retroactively once the deployment is in the data, because the pipeline reruns on
   the stored history).
8. Module `checks/range_check.py` instead of `checks/range.py`; the detector is split into
   small modules (plan §1.2).

## Out of scope

- `src/sivin/core/flags.py` / plan §2.5: a single `qc` field per row means a humidity finding
  excludes the temperature of the row (already raised as open question 5 in WP-0.1). Proposal:
  per-variable flag columns (`qc_temp`, `qc_rh`) or a variable mask in a future contract change.
- `src/sivin/analytics/base.py` (`IndexRegistry`) and `checks/base.py` (`CheckRegistry`) repeat
  the same registry logic; the generic `Registry[T]` proposed in the WP-0.1 note would serve
  both (and `ExportParser` in WP-1.2).
- Integration (WP-1.7 / WP-3.2): add `quality: QualityPipelineSettings` to `SivinConfig`
  (proposed YAML in `docs/quality-control.md` → *Configuration*), pass `placement.from` of the
  registry (WP-1.1) as `known_deployments`, write `QualityResult.events` to
  `data/derived/events/<sensor_id>.json` and the site contract (`type`, `t`, `source`,
  `confidence`, `detail`), and log `deployment_mismatch` / `unconfirmed_transition` warnings
  into the run summary (`data/runs/*.jsonl`). Proposed CLI command:
  `sivin qc [--sensor ID] [--dry-run]`. The site contract should describe `confidence` as a
  heuristic score.
- `SamplingSettings.expected_interval_s` defaults to `LEGACY_SAMPLING_INTERVAL_S`; once wired,
  it should be taken from `time.expected_interval_s` to keep one source.

## Open questions for the owner

1. **Q3:** known deployment dates and any service visits per sensor are needed to tune the
   absolute and relative thresholds and `known_tolerance_s`.
2. **Q2:** is a minimum detectable service stay of about one day acceptable, or are short visits
   (hours) common? Shorter visits stay vineyard data.
3. Climatological temperature limits for South Moravia: confirm or provide (default −30/42 °C),
   and the temperature/humidity resolution of the sensors (assumed 0.1 °C and 1 %).
4. Q4 (redeployment missing in the registry) is answered by the orchestrator's round-2 default:
   applied with a warning. Confirm or change.

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
| major | `src/sivin/quality/regime.py:236-267` | False retrievals on cloudy summer days (absolute rules) | fixed (round 2): absolute steady-humidity rule + relative confirmation; 0 false transitions in 180 summer runs (was 377) and in 30 plain/30 extreme years; overcast summer deployment 15/15 |
| major | `src/sivin/quality/regime.py:191-213`, `segmentation.py:346` | Plan §2.7 step 2 (relative confirmation) not implemented, deviation not declared | fixed (round 2): `contrast.py` implements §2.7 step 2 on local windows; 12 °C and 30 °C offices 15/15; comfort band replaced by room band (declared, deviation 6) |
| major | `src/sivin/quality/deployment.py:68-76`, `changepoint.py:197` | Fixed change-point cap makes the result depend on series length | fixed (round 2): epoch-anchored 30-day windows (`windows.py`); 1/3/5-year service 6/6 each; `TestLongSeries` checks identical events |
| major | `src/sivin/quality/timeline.py:458-470`, `deployment.py:281` | Known deployments discard detected redeployments; outdoor data excluded permanently | fixed (round 2): orchestrator default (Q4); unmatched detections applied with warning; 2nd outdoor stretch 0 % flagged; later relocation only: 0 of 1420 rows |
| minor | `src/sivin/quality/regime.py:213`, `deployment.py:340`, `docs/quality-control.md:266-271` | Confidence is an uncalibrated rule-score margin, not a probability | fixed (round 2): confidence = share of relative votes; documented as heuristic score in docs and code |
| minor | `src/sivin/quality/timeline.py:463-468` | Every relocation produces a `deployment_mismatch` warning | fixed (round 2): a later known time without matching detection is a relocation (info, no warning); 0 warnings in 60 runs |
| minor | `src/sivin/quality/segmentation.py:355-368` | Transport (car) rows left as vineyard data | fixed (round 2): `TransportTrimmer`; 35 °C car offset 0 vs arrival except a few summer runs (−3) where the car lies within the outdoor range |
| minor | `src/sivin/quality/deployment.py:347-356` | Event detail compares whole merged regimes, so the numbers can mislead | fixed (round 2): detail from local 2-day windows next to the boundary, with votes |
| minor | `src/sivin/quality/checks/step.py:270-281` | A fast convective front is flagged `STEP` | fixed (round 2): `max_adjacent_fraction` 0.4; −10 °C/1 h front no longer STEP; a front within one interval still is (documented) |
| minor | `src/sivin/quality/checks/persistence.py:404-417` | Long isothermal fog can be flagged `STUCK` | fixed (round 2): exemption when ≥ 50 % of the run has RH ≥ 97 % for both variables; temperature duration 12 h; STUCK 0 in 30 extreme years |
| minor | `tests/quality/synthetic.py:36-45`, `tests/quality/test_deployment.py` | Test generator has no cloud or synoptic variability, so tests miss the M1–M3 failures | fixed (round 2): generator with Markov cloudiness, synoptic anomaly, seasonal/cloud RH, fog, heat waves, fronts, car, office variants; new acceptance tests |
| nit | `docs/quality-control.md:340-342` | Service visits shorter than a day go undetected and their rows count as vineyard data | open, documented (owner question Q2; orchestrator: stays) |

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
