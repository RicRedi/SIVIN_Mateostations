# Quality control and transition detection

Package `sivin.quality` (WP-1.5) checks the measurements of one sensor, sets
[`QcFlag`](../src/sivin/core/flags.py) bits in the `qc` column and reports events (deployments,
retrievals, steps, gaps). The binding design is
[MIGRATION_PLAN.md §2.7](../MIGRATION_PLAN.md#27-kvalita-dat-validace-vstupu-párování-a-přechody).

All numeric thresholds below are **project defaults for ~30 min data, not values quoted from
literature**, unless the table says otherwise. They are marked *[to be tuned]* and must be
checked against real data once it is available (owner questions Q1–Q3). The methodology of the
range, step (rate-of-change) and persistence tests follows Zahumenský (2004).

## Contents

- [Flags and events](#flags-and-events)
- [Pipeline order](#pipeline-order)
- [Checks](#checks)
- [Deployment detection](#deployment-detection)
- [Configuration](#configuration)
- [Limitations](#limitations)
- [Implementation](#implementation)
- [References](#references)

## Flags and events

| Flag | Set by | Excluded from indices by default |
|---|---|---|
| `MISSING` (1) | `missing` | yes |
| `OUT_OF_RANGE` (2) | `range` | yes |
| `SPIKE` (4) | `spike` | yes |
| `STEP` (8) | `step` | no (informative) |
| `STUCK` (16) | `persistence` | yes |
| `PRE_DEPLOYMENT` (32) | deployment detector | yes |
| `TIMESTAMP_SUSPECT` (128) | `sampling` (also set by the parsers for DST, WP-1.2) | no |

`NEIGHBOR_OUTLIER` (64) needs the sensor alignment of WP-1.6 and `MANUAL_EXCLUDE` (256) is set
by the owner; neither is produced here. Existing flags of the input are kept (all flags are
OR-ed).

Events (`QualityEvent`, `DeploymentEvent`) carry `kind`, `t_utc`, `detail`, `severity`
(`info`/`warning`), `source` (`detected`/`registry`), an optional `confidence` (0–1) and, for
intervals, `end_utc`. Kinds: `deployment`, `retrieval`, `step`, `gap`, `irregular_sampling`,
`non_positive_interval`, `deployment_mismatch`. The first three are the `type` values of the
site contract (`events/<id>.json`, plan §2.6).

The `qc` field is one bit field per row (frozen contract, plan §2.5). A finding in humidity
therefore flags the whole row, temperature included; see [Limitations](#limitations).

## Pipeline order

`QualityPipeline.run(series, known_deployments=())` runs three stages:

1. **Screening checks on the whole series** — default `missing`, `sampling`, `range`. These are
   wrong wherever the sensor is. Their `MISSING` and `OUT_OF_RANGE` flags are passed on, so the
   detector ignores a gross error (e.g. a −999 sentinel) instead of seeing a regime change.
2. **Deployment detection on the whole series** — `deployment`/`retrieval` events and
   `PRE_DEPLOYMENT` for every sample recorded indoors.
3. **Deployed checks on every continuous outdoor stretch separately** — default `spike`, `step`,
   `persistence`. Indoor data are not judged by outdoor expectations (a stable office
   temperature is not "stuck"), and the jump at a deployment or retrieval is never reported as
   a spike or a step, because no stretch spans it.

With `detect_deployment: false` the whole series is one outdoor stretch.

The result (`QualityResult`) holds the flagged series, all events in time order, the number of
rows per single flag (`flag_counts`) and the detector details (segments, regimes, features).

## Checks

Every check is a subclass of `QualityCheck` registered under a name in `check_registry`; its
settings are a frozen pydantic model (`extra="forbid"`). A new check is a new registered class.
All checks use the real timestamps of the series; they never assume a regular grid. `NaN`
values are skipped by every check except `missing`.

Notation: $x_i$ value, $t_i$ time of sample $i$ (s), $\Delta t_i = t_i - t_{i-1}$,
$\Delta t_0 = 1825$ s the nominal interval.

### `missing` — missing values → `MISSING`

A row is missing if **all** checked variables are `NaN` (`rule: all`, default) or if **any** is
(`rule: any`).

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `variables` | `[temp_c, rh_pct]` | — | both measured variables |
| `rule` | `all` | — | project choice: the row flag is shared, `any` would discard a valid temperature whenever only humidity is missing; aggregates ignore a single `NaN` anyway |

### `range` — plausible values → `OUT_OF_RANGE`

Temperature is flagged outside $[\max(T^{phys}_{min}, T^{clim}_{min}),\ \min(T^{phys}_{max},
T^{clim}_{max})]$, humidity outside $[h_{min}, h_{max}]$. A climatological limit set to `null`
falls back to the physical one.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `temp_physical_min_c` / `temp_physical_max_c` | −50 / 60 | °C | project default *[to be verified against the sensor data sheet]* |
| `temp_climate_min_c` / `temp_climate_max_c` | −30 / 42 | °C | project default for South Moravia *[to be verified against station records]* |
| `rh_min_pct` / `rh_max_pct` | 0 / 100 | % | physical limits of relative humidity |

### `spike` — isolated departure that returns → `SPIKE`

With $d^- = x_i - x_{i-1}$, $d^+ = x_{i+1} - x_i$ (previous and next *valid* samples), rate
limit $r$ and $\tau^\pm = \max(\Delta t^\pm, \Delta t_{min})$ in hours, sample $i$ is a spike if

$$
d^- d^+ < 0, \qquad |d^-| > r\,\tau^-, \qquad |d^+| > r\,\tau^+, \qquad \Delta t^\pm \le \Delta t_{max}.
$$

The threshold grows with the actual interval, so a longer interval tolerates a larger change;
$\Delta t_{min}$ keeps closely spaced samples from getting a tiny threshold, and a neighbour more
than $\Delta t_{max}$ away cannot confirm a spike. A row gets `SPIKE` if either variable spikes.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `temp_max_rate_c_per_h` | 8 (≈ 4.06 °C per 1825 s) | °C/h | project default *[to be tuned]*; method Zahumenský (2004) |
| `rh_max_rate_pct_per_h` | 40 (≈ 20.3 % per 1825 s) | %/h | project default *[to be tuned]* |
| `min_interval_s` | 1825 | s | nominal interval |
| `max_interval_s` | 5475 | s | project default, 3 × nominal interval |

### `step` — sudden persistent level shift → `STEP` + `step` event

For consecutive valid samples with $|x_k - x_{k-1}| \ge J$ and $\Delta t_k \le \Delta t_{max}$,
let $m^-$ be the median over $[t_{k-1} - W, t_{k-1}]$ and $m^+$ over $[t_k, t_k + W]$ (each
needs at least `min_window_samples`). Sample $k$ is a step if

$$
\operatorname{sign}(m^+ - m^-) = \operatorname{sign}(x_k - x_{k-1}), \qquad
|m^+ - m^-| \ge f\,|x_k - x_{k-1}|.
$$

A spike returns, so its medians agree and it is not a step; a gradual change (cold front) has
small single-interval jumps and is not examined. The flag is informative.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `temp_min_jump_c` | 5 | °C | project default *[to be tuned]* |
| `rh_min_jump_pct` | 25 | % | project default *[to be tuned]* |
| `window_s` | 10 800 (3 h) | s | project default |
| `min_window_samples` | 3 | count | project default |
| `persistence_fraction` | 0.5 | — | project default |
| `max_interval_s` | 5475 | s | project default, 3 × nominal interval |

### `persistence` — unchanged value → `STUCK`

Valid values are scanned left to right; a run grows while $\max - \min \le \varepsilon$. A run
whose first and last samples are at least $D$ apart gets `STUCK` on all its samples. Humidity
runs entirely at or above the saturation threshold are exempt (fog, dew).

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `temp_tolerance_c` | 0.05 | °C | half of an assumed 0.1 °C resolution *[to be verified]* |
| `temp_min_duration_s` | 21 600 (6 h) | s | project default *[to be tuned]*; method Zahumenský (2004) |
| `rh_tolerance_pct` | 0.5 | % | half of an assumed 1 % resolution *[to be verified]* |
| `rh_min_duration_s` | 43 200 (12 h) | s | project default *[to be tuned]* |
| `rh_saturation_pct` | 99 | % | project default; `null` disables the exemption |

### `sampling` — gaps and irregular intervals → `TIMESTAMP_SUSPECT` + events

Each interval $\Delta t_i$ is

- **non-positive** if $\Delta t_i \le 0$ (impossible in a valid `MeasurementSeries`; checked
  for raw arrays by `classify_intervals`),
- a **gap** if $\Delta t_i > k\,\Delta t_0$ → `gap` event from $t_{i-1}$ to $t_i$, no flag,
- **regular** if $|\Delta t_i - n\,\Delta t_0| \le \varepsilon\,\Delta t_0$ with
  $n = \max(\operatorname{round}(\Delta t_i / \Delta t_0), 1)$ ($n \ge 2$ = missed samples),
- **irregular** otherwise → `TIMESTAMP_SUSPECT` on sample $i$.

Irregular and non-positive intervals are summarised in one warning event each.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `expected_interval_s` | 1825 | s | legacy configs (`time.expected_interval_s`) |
| `gap_factor` | 3 | — | project default *[to be tuned]* |
| `tolerance_fraction` | 0.25 | — | project default, tolerates clock drift *[to be tuned]* |

## Deployment detection

A sensor is switched on in the office (stable 20–25 °C, small daily range, low humidity), carried
into the vineyard (step in temperature and humidity, much larger daily range) and possibly
brought back for service and redeployed. `DeploymentDetector` finds these transitions in five
steps.

### 1. Change points in level and variance

Rows without temperature and rows flagged by `ignore_mask` (default
`MISSING | OUT_OF_RANGE | MANUAL_EXCLUDE`) are not used. Humidity is used as a second variable if
at least `min_rh_fraction` of the usable rows have it; otherwise the detector works on
temperature alone.

Within a segment each variable $v$ is modelled as independent Gaussian with its own mean and
variance. For a segment $[a, b)$ with $m = b - a$ samples and maximum-likelihood variance
$\hat\sigma^2_v(a, b)$, twice the negative maximised log-likelihood is, up to terms that cancel,

$$
C(a, b) = m \sum_v \ln\!\left(\hat\sigma^2_v(a, b) + \sigma^2_{v,0}\right),
$$

where $\sigma^2_{v,0}$ is a variance floor (quantised indoor data can have zero variance).
Splitting at $\tau$ gains the log-likelihood-ratio statistic of one change in mean and variance

$$
G(\tau) = C(a, b) - C(a, \tau) - C(\tau, b) = 2 \ln \Lambda(\tau).
$$

With prefix sums $S_1(j) = \sum_{i<j} x_i$ and $S_2(j) = \sum_{i<j} x_i^2$,
$\hat\sigma^2(a, b) = \frac{S_2(b) - S_2(a)}{m} - \left(\frac{S_1(b) - S_1(a)}{m}\right)^2$, so
each $C$ costs O(1) and one scan over all $\tau$ of a segment is O(m) (data are centred first
for numerical stability).

**Binary segmentation** (greedy, largest gain first) splits the segment whose best split has the
largest gain, as long as that gain reaches the penalty

$$
\beta = c\,(p + 1)\ln n,
$$

with $p = 2 \times$ (number of variables) parameters per segment, $+1$ for the location, $n$
samples and factor $c$ (1 = Schwarz/BIC weight, Schwarz 1978), and at most
`max_change_points` times. Both sides of a split must last at least `min_segment_s` (time
measured on the real timestamps; the last sample's slot ends one median interval after it) and
contain at least 3 samples. This is the change-point family of CUSUM-type likelihood tests
(Page 1954) and penalised-cost segmentation (Killick et al. 2012 give the optimal, linear-time
PELT search; here the simpler binary segmentation of Scott & Knott 1974 is used to avoid a new
dependency).

Outdoor weather is not i.i.d. Gaussian, so outdoor data produce many change points; that is
expected — the regime step decides which of them matter.

### 2. Regime of each segment

`RegimeClassifier` computes three robust features of a segment:

- median temperature $\tilde T$ and its distance from the comfort band $[T_{lo}, T_{hi}]$:
  $d = \max(T_{lo} - \tilde T,\ \tilde T - T_{hi},\ 0)$;
- daily spread $s$: the median over consecutive 24-h windows (counted from the segment start,
  windows with fewer than `min_window_samples` samples skipped, the whole segment if none is
  left) of $P_{95} - P_5$ of temperature — percentiles so that one spike does not matter;
- median relative humidity $\tilde h$ (if humidity is used).

Each feature becomes a membership in "indoor" with a linear ramp, combined by a logical AND:

$$
\mu_{band} = 1 - \operatorname{clip}\!\left(\tfrac{d}{r_T}, 0, 1\right), \quad
\mu_{spread} = 1 - \operatorname{clip}\!\left(\tfrac{s - s_{max}}{r_s}, 0, 1\right), \quad
\mu_{rh} = 1 - \operatorname{clip}\!\left(\tfrac{\tilde h - h_{max}}{r_h}, 0, 1\right),
$$

$$
S = \min(\mu_{band}, \mu_{spread}, \mu_{rh}), \qquad
\text{regime} = \begin{cases}\text{indoor} & S \ge S_0\\ \text{outdoor} & \text{otherwise}\end{cases},
\qquad \text{confidence} = |2S - 1|.
$$

All three must look indoor: an overcast winter day has a small spread but is far from the band;
a summer day is inside the band but has a large spread and humid nights; an office has neither.

### 3. Regimes and boundaries

Adjacent segments with the same label are merged. Each remaining boundary is **refined**: within
the two regimes it separates, and at most `min_segment_s` from the first estimate, the position
with the largest $G(\tau)$ wins. The minimum segment duration thus limits the search but not the
final boundary (without refinement a retrieval less than a day after an earlier weather change
point could not be placed exactly). The merged regimes are then classified again on their final
extent; neighbours that now agree are merged.

### 4. Events and confidence

An indoor → outdoor boundary is a `deployment`, outdoor → indoor a `retrieval`, at the time of
the first sample of the new regime. The confidence is the smaller of the two regimes'
confidences. The detail names the median temperature step, the ratio of daily spreads and the
humidity change, e.g. `indoor → outdoor: step -13.6 °C, daily spread x11.4, humidity +33 %`.

Level shifts *within* a regime are reported by the `step` check, not by the detector, so that a
step is not reported twice.

### 5. Known deployments and `PRE_DEPLOYMENT`

Known deployment times (e.g. `placement.from` of the sensor registry, plan §2.4) are ground truth:

1. each known time becomes a `deployment` with source `registry` and confidence 1;
2. a detected deployment within `known_tolerance_s` of a known time is replaced by it (its
   detail is kept in the event);
3. a detected deployment farther than the tolerance from every known time is not applied and
   produces a `deployment_mismatch` warning;
4. a known time without a detected deployment within the tolerance produces a warning too;
5. detected retrievals are kept (the interface carries no retrieval times);
6. with known times, the sensor counts as indoors before the first one (unless it precedes the
   data).

The transitions are then applied in time order (deployment → outdoor, retrieval → indoor; a
transition into the current state changes nothing). Without known times the state before the
first transition is the regime of the first segment. Every row recorded while indoors — before
the first deployment, between a retrieval and the next deployment, after a final retrieval —
gets `PRE_DEPLOYMENT`; rows without values take the state of their timestamp.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `change_points.min_segment_s` | 86 400 (1 day) | s | project default; also the shortest detectable service stay |
| `change_points.penalty_factor` | 1 | — | BIC weight (Schwarz 1978) |
| `change_points.max_change_points` | 50 | count | project default, bounds the work |
| `change_points.temp_variance_floor_c2` | 0.01 | °C² | (0.1 °C)², project default |
| `change_points.rh_variance_floor_pct2` | 0.25 | %² | (0.5 %)², project default |
| `change_points.min_rh_fraction` | 0.5 | — | project default |
| `regime.comfort_band_low_c` / `comfort_band_high_c` | 18 / 27 | °C | project default (brief) *[to be tuned]* |
| `regime.band_ramp_c` | 4 | °C | project default |
| `regime.indoor_max_daily_spread_c` | 3 | °C | project default *[to be tuned]* |
| `regime.spread_ramp_c` | 3 | °C | project default |
| `regime.indoor_max_rh_pct` | 65 | % | project default *[to be tuned]* |
| `regime.rh_ramp_pct` | 15 | % | project default |
| `regime.indoor_threshold` | 0.5 | — | project default |
| `regime.min_window_samples` | 12 | count | a quarter of a day at 1825 s |
| `known_tolerance_s` | 21 600 (6 h) | s | project default *[to be tuned with Q3]* |
| `ignore_mask` | 259 | bit mask | `MISSING \| OUT_OF_RANGE \| MANUAL_EXCLUDE` |

## Configuration

The settings are pydantic models inside `sivin.quality` and are not yet part of
`config/sivin.yaml`. Proposed section (wired in by the integration workpackage):

```yaml
quality:
  screening_checks: [missing, sampling, range]
  deployed_checks: [spike, step, persistence]
  check_settings:
    range: { temp_climate_min_c: -30.0, temp_climate_max_c: 42.0 }
  detect_deployment: true
  deployment:
    known_tolerance_s: 21600
    change_points: { min_segment_s: 86400 }
    regime: { comfort_band_low_c: 18.0, comfort_band_high_c: 27.0 }
```

## Limitations

- **Not verified on real data.** All tests use the synthetic generator in
  `tests/quality/synthetic.py`; thresholds are project defaults to be tuned once real exports
  (Q1) and known deployment dates (Q3) are available.
- **One flag field per row.** A humidity finding (`range`, `spike`, `persistence`) also
  excludes the row's temperature, because the contract has a single `qc` column (plan §2.5).
- **Short indoor stays** (service shorter than `min_segment_s`, default one day) are not
  detected as retrieval + deployment; transport time (car, minutes to hours) is attributed to
  whichever regime it resembles.
- **Unusual indoor conditions** — an unheated store in winter, a hot office without air
  conditioning, a sensor left on a sunny window sill — can violate the indoor rules and be
  labelled outdoor; a sheltered, shaded outdoor spot in calm overcast weather with low humidity
  for a whole day could look indoor. Known deployment times override the detected
  deployments (rule 2-3 above).
- **Known deployments override deployments only.** A service visit missing in the registry is
  still detected as a retrieval, but its redeployment is then only a warning, and the data until
  the next known deployment stay `PRE_DEPLOYMENT` (conservative: data are excluded rather than
  accepted).
- **Persistence** uses greedy left-to-right runs; a run that starts in the middle of an earlier
  run within the tolerance can be split. Humidity at saturation is never `STUCK`.
- **Greedy binary segmentation** is not guaranteed optimal (PELT would be); the refinement step
  and the regime merging make the reported boundaries insensitive to that in the tested cases.

## Implementation

| Concept | Module | Tests |
|---|---|---|
| `QualityCheck`, `CheckOutcome`, `check_registry` | `sivin/quality/checks/base.py` | `tests/quality/test_base_and_events.py` |
| checks `missing`, `range`, `spike`, `step`, `persistence`, `sampling` | `sivin/quality/checks/*.py` | `tests/quality/test_checks.py` |
| `GaussianSegmentCost`, `BinarySegmentation` | `sivin/quality/changepoint.py` | `tests/quality/test_changepoint_regime.py` |
| `RegimeClassifier` | `sivin/quality/regime.py` | `tests/quality/test_changepoint_regime.py` |
| `RegimeSegmenter` (merge + refine) | `sivin/quality/segmentation.py` | `tests/quality/test_changepoint_regime.py` |
| `KnownDeploymentReconciler`, `DeploymentTimeline` | `sivin/quality/timeline.py` | `tests/quality/test_deployment.py` |
| `DeploymentDetector`, `DeploymentResult` | `sivin/quality/deployment.py` | `tests/quality/test_deployment.py` |
| `QualityEvent`, `DeploymentEvent` | `sivin/quality/events.py` | `tests/quality/test_base_and_events.py` |
| `QualityPipeline`, `QualityResult` | `sivin/quality/pipeline.py` | `tests/quality/test_pipeline.py` |
| synthetic generator | `tests/quality/synthetic.py` | `tests/quality/test_pipeline.py` |

## References

- Killick, R., Fearnhead, P., Eckley, I. A. (2012). Optimal detection of changepoints with a
  linear computational cost. *Journal of the American Statistical Association*, 107(500),
  1590–1598. [DOI not verified]
- Page, E. S. (1954). Continuous inspection schemes. *Biometrika*, 41(1/2), 100–115.
  [DOI not verified]
- Schwarz, G. (1978). Estimating the dimension of a model. *The Annals of Statistics*, 6(2),
  461–464. [DOI not verified]
- Scott, A. J., Knott, M. (1974). A cluster analysis method for grouping means in the analysis
  of variance. *Biometrics*, 30(3), 507–512. [DOI not verified]
- Zahumenský, I. (2004). *Guidelines on Quality Control Procedures for Data from Automatic
  Weather Stations.* World Meteorological Organization, Geneva.
