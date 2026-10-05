# Gubler-Thomas powdery mildew risk index (`powdery_mildew_gt`)

## Purpose

Grapevine powdery mildew (*Erysiphe necator*) spreads by conidia whenever temperatures are
moderate for several hours a day; it needs no rain or leaf wetness for that. The UC Davis
risk index of Gubler and Thomas turns the daily temperature course into a score of 0-100
points that growers use to adjust spray intervals: a high index means conditions favour
rapid conidial reproduction. The index only uses temperature, so our sensors measure
everything it needs. Its reliability is therefore listed as **full** in MIGRATION_PLAN §3.3.
The ascospore (primary infection) part of the UC Davis model needs leaf wetness and is
**not** implemented.

## Definition

The index is a day-by-day state machine with two phases.

A day $d$ is **favourable** when the longest run of consecutive time with temperature in the
band $[T_{lo}, T_{hi}]$ lasts at least $H_{min}$:

$$
F_d = \left[\, \max_{r \in \text{runs}_d} \sum_{i \in r} \Delta t_i \;\ge\; H_{min} \right],
\qquad T_{lo} \le T_i \le T_{hi} \;\; \forall i \in r
$$

A day has **heat** when valid samples at or above $T_{heat}$ cover at least $D_{heat}$:

$$
X_d = \left[\, \sum_{i \in d,\; T_i \ge T_{heat}} \Delta t_i \;\ge\; D_{heat} \right]
$$

**Waiting for onset.** A streak counter $s$ counts consecutive favourable days, and a
non-favourable day resets it. When $s = N_{on}$, the index starts on that day with
$I_d = I_{on}$.

**Active.** After onset the index moves by

$$
I_d = \min\!\Big(I_{max},\; \max\!\big(I_{min},\; I_{d-1} + P_{+}\,[F_d] - P_{-}\,[\neg F_d] - P_{heat}\,[X_d]\big)\Big)
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $T_i$ | temperature of sample $i$ | °C |
| $\Delta t_i$ | time represented by sample $i$ (see *Assumptions*) | h |
| $T_{lo}, T_{hi}$ | favourable band, 70 °F and 85 °F | °C |
| $H_{min}$ | minimum run in the band | h |
| $T_{heat}$, $D_{heat}$ | heat threshold (95 °F) and minimum heat duration | °C, min |
| $N_{on}$ | consecutive favourable days for onset | d |
| $I_{on}$ | index on the onset day | points |
| $P_{+}, P_{-}, P_{heat}$ | points added per favourable day, subtracted per non-favourable day, subtracted per heat day | points |
| $I_{min}, I_{max}$ | bounds of the index | points |
| $[\cdot]$ | 1 if the condition holds, else 0 | — |

The conversion from °F is $T_{°C} = (T_{°F} - 32)/1.8$: 70 °F = 21.11 °C, 85 °F = 29.44 °C
and 95 °F = 35.0 °C. Both band limits are inclusive.

### Interpretation choices (this project)

1. **Index value at onset.** On the onset day the index is set to $I_{on} = 60$, i.e. the three
   onset days earn their 20 points each. Verified in WP-L.1: the UC IPM model description
   states that "for each of these three days, the model assigns 20 points". It is configurable
   as `onset_index_points`.
2. **Heat and hours on the same day.** The heat penalty is applied independently of the
   hours rule, so a favourable day with heat nets $+20 - 10 = +10$ and a non-favourable heat day
   $-20$. The $+10$ case is confirmed by a secondary description of the index (Pest Prophet
   blog, see [literature verification](../literature-verification.md)). The same description
   says that the index "should not decline by more than 10 points" on one day, which would make
   a non-favourable heat day $-10$, not $-20$. Neither the APSnet text of Gubler et al. (1999)
   nor the UC IPM page could be read to confirm it, so the implementation is **unchanged**
   **[to be verified]**; this is an owner question (`docs/wp_log/WP-L.1.md`).
3. **Heat before onset** is ignored and does not reset the onset streak. This is a project
   interpretation **[to be verified]**: the descriptions known to us mention the heat penalty
   only for the running index.
4. **Undetermined days.** A day is *undetermined* when it is not favourable on the samples we
   have and its temperature coverage is below `analytics.min_daily_coverage`: the missing
   data could have held the run. Such a day **leaves the state unchanged**. While waiting,
   the streak neither grows nor resets, but only for up to `max_undetermined_carry_days`
   (default 1, project default **[to be tuned]**) consecutive undetermined days. A longer run of
   undetermined days resets the streak, so "3 consecutive days" cannot span a long outage.
   Once active, the index gets neither +20 nor −10. A heat
   period that was observed on such a day still subtracts its points. A day with low coverage
   that already shows a long enough run is favourable, because more data cannot undo an
   observed run.
5. **The index stays active** until the end of the period once it has started, even if it
   falls to 0. This is a project interpretation **[to be verified]**: the descriptions known to
   us do not mention a restart, but the original text was not checked.
6. **Day boundaries.** Runs are searched within one local calendar day (Europe/Prague). The
   duration of the last sample of a day may reach a few minutes into the next day. **Known
   limitation:** a run that crosses midnight is split into two runs, one per day. For example,
   a band period from 21:00 to 03:00 gives about 3 h + 3 h, and neither day is favourable,
   although the run lasted 6 h. Such warm nights are rare in South Moravia; the behaviour is
   kept as is.

## Period and aggregation

- Default period: **April 1 - October 31** of the season year (`season`). This is a project
  default. The UC IPM guideline starts the index at budbreak, so on real data the start
  should be set to the observed budbreak. Days before the first sample of the period are not
  part of the curve, and the model is waiting for onset on them.
- Daily: one assessment per local calendar day, computed from the raw samples. QC-excluded and
  missing temperatures are not valid samples and break runs.
- Completeness: `coverage` is the share of days in the period whose temperature coverage
  reaches `analytics.min_daily_coverage` (`ClimateIndex._season_days`). `complete` is
  `coverage >= analytics.min_season_coverage`.
- Output: `value` is the season maximum of the index (points), and `classification` is the
  class of that maximum. `daily` is the index at the end of each day. `details` holds
  `onset_date`, `current_index_points`, `current_class` (class of the last computed day),
  `phase` and the counts of favourable, unfavourable,
  undetermined and heat days.

## Parameters

Proposed configuration key: `analytics.indices.powdery_mildew_gt` (wired in by the integration
WP).

| Config name | Default | Unit | Source |
|---|---|---|---|
| `band_min_temp_c` | 21.11 (70 °F) | °C | Gubler et al. (1999); UC IPM |
| `band_max_temp_c` | 29.44 (85 °F) | °C | Gubler et al. (1999); UC IPM |
| `min_favourable_run_h` | 6 | h | Gubler et al. (1999); UC IPM |
| `onset_days` | 3 | d | Gubler et al. (1999); UC IPM |
| `onset_index_points` | 60 | points | UC IPM model description (3 × 20) |
| `max_undetermined_carry_days` | 1 | d | project default **[to be tuned]** |
| `favourable_day_points` | 20 | points | Gubler et al. (1999); UC IPM |
| `unfavourable_day_points` | 10 | points | Gubler et al. (1999); UC IPM |
| `heat_temp_c` | 35.0 (95 °F) | °C | Gubler et al. (1999); UC IPM |
| `min_heat_duration_min` | 15 | min | Gubler et al. (1999); UC IPM |
| `heat_points` | 10 | points | Gubler et al. (1999); UC IPM |
| `min_index_points`, `max_index_points` | 0, 100 | points | UC IPM |
| `moderate_from_points`, `high_from_points` | 40, 60 | points | UC IPM classes |
| `season.start_month/day`, `season.end_month/day` | 4/1, 10/31 | — | project default |
| `sampling.nominal_interval_s` | 1830 | s | always set from `time.expected_interval_s` (WP-1.7) |
| `sampling.max_sample_duration_s` | 4575 (2.5 × 1830) | s | project default, to be tuned |

The values attributed to Gubler et al. (1999) and UC IPM were checked in WP-L.1 against excerpts
of the UC IPM pages and secondary descriptions found by web search (the pages themselves could
not be opened): 70–85 °F for 6 continuous hours, three consecutive days for onset, +20 / −10
points, 95 °F for 15 minutes −10 points, bounds 0–100, classes 0–30 / 40–50 / 60–100. One
secondary description gives other classes (0–20 / 30–50 / 60–100); the UC IPM text is kept.

## Interpretation

| Index (points) | Class | Meaning (UC IPM) |
|---|---|---|
| 0-30 | `low` | pathogen survives, reproduction slow; longest spray intervals |
| 40-50 | `moderate` | pathogen reproduces about every 15 days; intermediate intervals |
| 60-100 | `high` | pathogen reproduces about every 5 days; shortest intervals |

The index only changes in steps of 10 points, so the classes have no gaps. The meaning column
follows the UC IPM / APSnet excerpts found in WP-L.1 (60–100: the pathogen reproduces about
every 5 days; 0–30: about every 15 days or not at all). The "40–50: every 15 days" wording of
the moderate class was not found and is a paraphrase **[to be verified]**; the exact
spray-interval advice depends on the fungicide and is not part of this project.

## Assumptions and limitations

- **Temperature only.** The index ignores leaf wetness and humidity by design.
- **Hours come from sample durations, not row counts.** Each valid sample represents the
  time until the next sample. A step longer than `max_sample_duration_s` is a data gap: the
  sample then represents only the nominal interval, and the gap ends the run. With the
  ~1830 s sampling, 12 consecutive samples in the band (21 960 s = 6.1 h) make a favourable
  day, and 11 samples (5.59 h) do not.
- **"95 °F for 15 minutes"** becomes "valid samples ≥ 35 °C representing at least 15 min".
  With ~30-minute sampling, **one valid sample ≥ 35 °C is enough**. A short heat peak between
  two samples is missed.
- **Sensor placement.** The model was developed for canopy temperatures in Californian
  vineyards. Our sensors' height and exposure (sun, shelter) affect band hours and heat
  peaks. An unshielded sensor in the sun overestimates heat.
- **Few sensors, local climate.** In South Moravia temperatures ≥ 35 °C are rare, so the heat
  rule seldom acts. Days in the 21-29 °C band for 6 h are common in summer, so the index is
  often high from June to August. The classes have not been validated against observed
  disease in our vineyards.
- **No budbreak date.** The default period starts April 1. Until a phenology diary or the
  `budburst` index (WP-2.1) provides the date, early warm spells before budbreak can start
  the index too early.

## Implementation

- Model: `sivin.analytics.disease.gubler_thomas.GublerThomasModel` (state machine;
  `GublerThomasParams`, `DayAssessment`, `GublerThomasState`, `Phase`, `RiskClass`,
  `fahrenheit_to_celsius`).
- Daily assessment from raw samples: `sivin.analytics.disease.powdery_mildew.PowderyMildewDayAssessor`,
  using `sivin.analytics.disease.sampling.SampleDurations` and `RunFinder`.
- Index: `sivin.analytics.disease.powdery_mildew.PowderyMildewGublerThomas`, registered as
  `powdery_mildew_gt`.
- Tests: `tests/analytics/disease/test_gubler_thomas.py` (state machine on a hand-built day
  sequence covering onset, growth, decline, heat interruption, bounds 0-100 and undetermined
  days; hourly integration example; 1825 s sampling (synthetic legacy spacing); QC exclusion; empty and complete
  season), `tests/analytics/disease/test_sampling.py`.

## References

- Gubler, W. D., Rademacher, M. R., Vasquez, S. J., Thomas, C. S. (1999). Control of powdery
  mildew using the UC Davis powdery mildew risk index. *APSnet Features*, American
  Phytopathological Society. https://doi.org/10.1094/APSnetFeature-1999-0199
- University of California Statewide Integrated Pest Management Program (UC IPM). *Grape Pest
  Management Guidelines: Powdery Mildew* (online), https://ipm.ucanr.edu/agriculture/grape/powdery-mildew/,
  and *Models: Powdery Mildew of Grape*, https://ipm.ucanr.edu/DISEASE/DATABASE/grapepowderymildew.html.
  [edition and date not stated in the excerpts; consulted via search index, October 2026]
- Pest Prophet blog, "How to Use Powdery Mildew Risk Index Model on Grapes",
  https://blog.pestprophet.com/how-to-use-powdery-mildew-risk-index-model-on-grapes/
  (secondary, commercial; source of the daily-limit statement in interpretation 2).
