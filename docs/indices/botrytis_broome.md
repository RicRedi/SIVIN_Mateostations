# Botrytis bunch rot — Broome infection model (`botrytis_broome`)

> **Estimated.** Wetness is not measured by our sensors; it is estimated from relative
> humidity. Every result of this index carries `estimated: true`, and its reliability is
> listed as **indicative** in MIGRATION_PLAN §3.3.

## Purpose

Grey mould / Botrytis bunch rot (*Botrytis cinerea*) infects flowers and ripening berries during
periods of surface wetness. Broome et al. (1995) fitted a logistic model that gives the expected
proportion of infected berries $Y$ from the **duration of wetness** and the **mean temperature
during wetness**. A high $Y$ marks a wetness period that favoured infection.

## Definition

For each wetness period with duration $W$ and mean temperature $T$:

$$
\ln\frac{Y}{1-Y} = a + b\,W + c\,W\,T + d\,W\,T^2
\qquad\Longrightarrow\qquad
Y = \frac{1}{1 + e^{-(a + b W + c W T + d W T^2)}}
$$

| Symbol | Meaning | Unit | Default |
|---|---|---|---|
| $Y$ | infection probability (proportion of infected berries) | — (0-1) | — |
| $W$ | wetness duration | h | — |
| $T$ | mean temperature during the wetness period | °C | — |
| $a$ | intercept | — | −2.647866 |
| $b$ | wetness coefficient | 1/h | −0.374927 |
| $c$ | wetness × temperature coefficient | 1/(h·°C) | 0.061601 |
| $d$ | wetness × temperature² coefficient | 1/(h·°C²) | −0.001511 |

The coefficients were verified in WP-L.1 against the UC IPM model page "Botrytis Bunch Rot of
Grape", which quotes the equation of Broome et al. (1995) as
$\ln(Y/(1-Y)) = -2.647866 - 0.374927\,W + 0.061601\,W T - 0.001511\,W T^2$ (the paper itself
was not read). They are configurable (`coefficients.*`).

Worked example (also a unit test): $W = 5$ h, $T = 15$ °C gives
$-2.647866 - 1.874635 + 4.620075 - 1.699875 = -1.602301$, so $Y = 1/(1 + e^{1.602301}) = 0.1677$.

### Wetness proxy

A sample is **wet** when its relative humidity is valid (present and not excluded by QC) and
$RH \ge RH_{wet}$, with a default of 90 %. A **wetness period** is a run of wet samples (see
`sampling.py`):

- each sample represents the time until the next sample, capped at `max_sample_duration_s`.
  A longer step is a data gap: the sample counts only the nominal interval, and the gap ends
  the period;
- dry interruptions (valid samples with $RH < RH_{wet}$) of up to `max_dry_interruption_h` in
  total are **bridged and counted** in $W$, on the assumption that surfaces stay wet through a
  brief dip in humidity. Longer dry spells end the period;
- missing or QC-excluded humidity always ends a period: nothing is known about that time;
- $W$ runs from the first wet sample to the end of the time represented by the last wet
  sample;
- $T$ is the duration-weighted mean of the valid temperatures within the period. A period
  without any valid temperature is skipped (and logged);
- periods shorter than `min_event_duration_h` are not reported.

## Period and aggregation

- Default period: **April 1 - October 31** (`season`). This is a project default. The
  susceptible stages are mainly bloom and ripening (veraison to harvest), which the plain
  date window does not model.
- A wetness period counts on the **local date of its last wet sample** and must end inside the
  period of the season year.
- Completeness: a day is covered when **both** `temp_coverage` and `rh_coverage` reach
  `analytics.min_daily_coverage`, because the model needs humidity. `coverage` is the share of
  covered days in the period. `complete` is `coverage >= analytics.min_season_coverage`. A
  failed humidity channel therefore lowers coverage even when temperature is complete.
- Output:
  - `value`: season maximum of $Y$. It is 0 when no wetness period was estimated in a period
    that has data, and `null` when the period has no samples.
  - `daily`: daily maximum of $Y$. It is 0 on covered days without a period and `NaN` on days
    that are neither covered nor have a period.
  - `details`: summary keys `n_events`, `wetness_proxy`, `total_wetness_h` and
    `max_infection_probability`, plus the event with the highest $Y$: `max_event_start_utc`,
    `max_event_duration_h` and `max_event_mean_temp_c`. The full list of events is available
    from `BotrytisBroome.infection_events(ctx)`.

## Parameters

Proposed configuration key: `analytics.indices.botrytis_broome` (wired in by the integration
WP).

| Config name | Default | Unit | Source |
|---|---|---|---|
| `wet_rh_threshold_pct` | 90 | % | project default, **to be tuned** (proxy, not from Broome et al.) |
| `max_dry_interruption_h` | 1.0 | h | project default, **to be tuned** |
| `min_event_duration_h` | 0 (report all) | h | project default, **to be tuned** |
| `max_wetness_h` | none (no cap) | h | project choice; caps $W$ in the formula |
| `coefficients.intercept` | −2.647866 | — | Broome et al. (1995), as quoted by UC IPM |
| `coefficients.wetness_h` | −0.374927 | 1/h | Broome et al. (1995), as quoted by UC IPM |
| `coefficients.wetness_temp` | 0.061601 | 1/(h·°C) | Broome et al. (1995), as quoted by UC IPM |
| `coefficients.wetness_temp_sq` | −0.001511 | 1/(h·°C²) | Broome et al. (1995), as quoted by UC IPM |
| `risk_bands` | empty (no classes) | — (0-1) | none; see *Interpretation* |
| `season.*` | 4/1 - 10/31 | — | project default |
| `sampling.nominal_interval_s` | 1830 | s | always set from `time.expected_interval_s` (WP-1.7) |
| `sampling.max_sample_duration_s` | 4575 (2.5 × 1830) | s | project default, to be tuned |

## Interpretation

$Y$ is a probability-like proportion of infected berries under the experimental conditions of
Broome et al. (1995). **No class limits are taken from the literature**, so by default the
index has no `classification`. Classes can be configured as `risk_bands`, a list of
`{label, min_probability}` in ascending order starting at 0, for example:

```yaml
risk_bands:
  - {label: low, min_probability: 0.0}
  - {label: elevated, min_probability: 0.3}
```

Such limits are local choices and must be documented as such when they are set.

Note the intercept: for $W \to 0$ the model gives $Y = 1/(1+e^{2.647866}) \approx 0.066$, not 0.
Very short estimated periods therefore still show a small $Y$. This value comes from the
regression intercept and has no meaning outside the wetness durations the model was fitted on.
`min_event_duration_h` can suppress such periods.

## Assumptions and limitations

- **The wetness proxy is the main source of error.** RH ≥ 90 % is a common but rough
  estimator of leaf and berry wetness. It tends to **overestimate** wetness on humid nights
  without dew on the berries. It **underestimates** wetness after rain, when surfaces stay wet
  while humidity is already below the threshold, and from rain itself, which our sensors do not
  record. The appropriate threshold depends on the sensor, its shelter and the canopy, and must
  be tuned against a leaf-wetness sensor (see `docs/indices/downy_mildew.md`). Sentelhas et
  al. (2008) review RH thresholds as wetness estimators.
- **Bias direction in South Moravia:** in late summer and autumn, nights with RH ≥ 90 % are
  frequent. Expect many short estimated periods and a non-zero daily curve on most nights,
  even when the berries stay dry.
- **Range of validity.** The model was fitted on detached mature berries with 4, 8, 12, 16 or
  20 h of wetness at 12–30 °C ($R^2 = 0.75$; UC IPM model page, verified in WP-L.1). Values
  outside that range, for example $W > 20$ h or $T$ below 12 °C or above 30 °C, are
  extrapolations. With the humidity proxy,
  multi-day fog or rain spells easily give $W > 24$ h, and $Y$ then **saturates near 1**: for
  example, $W = 48$ h at 20 °C gives $Y = 0.99992$. The optional parameter `max_wetness_h`
  (default: no cap, project choice) caps the $W$ used in the formula. The reported duration of
  the period is not changed.
- **Phenology** is not modelled: berries are susceptible at bloom and from veraison, and the
  default window also scores periods when no susceptible tissue is present.
- **~30-minute sampling:** $W$ has a resolution of one sample (~0.5 h), and a single dry
  sample is bridged with the default `max_dry_interruption_h = 1.0`.

## Implementation

- Pure model: `sivin.analytics.disease.botrytis.BroomeCoefficients` (`logit`,
  `infection_probability`), `logistic`.
- Wetness proxy: `sivin.analytics.disease.botrytis.WetnessPeriodDetector` (`WetnessPeriod`)
  on top of `sivin.analytics.disease.sampling.SampleDurations` and `RunFinder`.
- Index: `sivin.analytics.disease.botrytis.BotrytisBroome`, registered as `botrytis_broome`.
  It returns `InfectionEvent`s via `infection_events(ctx)`.
- Tests: `tests/analytics/disease/test_botrytis.py` (hand-computed $Y$, two synthetic nights
  with a bridged interruption, missing and QC-excluded humidity, duration-weighted
  temperature, filters, risk bands, empty season).

## References

- Broome, J. C., English, J. T., Marois, J. J., Latorre, B. A., Aviles, J. C. (1995).
  Development of an infection model for Botrytis bunch rot of grapes based on wetness duration
  and temperature. *Phytopathology*, 85, 97-102. https://doi.org/10.1094/Phyto-85-97
- Sentelhas, P. C., Dalla Marta, A., Orlandini, S., Santos, E. A., Gillespie, T. J.,
  Gleason, M. L. (2008). Suitability of relative humidity as an estimator of leaf wetness
  duration. *Agricultural and Forest Meteorology*, 148, 392-400.
  https://doi.org/10.1016/j.agrformet.2007.09.011
- UC IPM. *Models: Botrytis Bunch Rot of Grape* (online),
  https://ipm.ucanr.edu/DISEASE/DATABASE/grapebotrytis.html (secondary source of the
  coefficients and the fitting range; consulted via search index, October 2026).
