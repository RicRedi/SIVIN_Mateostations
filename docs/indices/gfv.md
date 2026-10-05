# Grapevine Flowering Véraison model (`gfv`)

## Purpose

Predicts the dates of flowering and véraison from accumulated heat. Parker et al. (2011) fitted
a general Spring Warming model for *Vitis vinifera* on a large phenology dataset; Parker et al.
(2013) give cultivar-specific critical sums. **The predictions are orientational** until they
are calibrated against local BBCH observations of our vineyards.

## Definition

$$
S(d) = \sum_{d' = t_0}^{d} \max\left(0,\; T_{mean,d'} - T_{base}\right),
\qquad \hat d_s = \min\{\, d : S(d) \ge F^*_s \,\}
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $t_0$ | start of accumulation: March 1 (day of year 60 in common years) | local date |
| $T_{mean,d}$ | daily mean, by default $(T_{max}+T_{min})/2$ | °C |
| $T_{base}$ | base temperature, 0 °C | °C |
| $S(d)$ | thermal sum after day $d$ | °C·d |
| $F^*_s$ | critical sum of stage $s$ (flowering, véraison) | °C·d |
| $\hat d_s$ | predicted date of stage $s$: first local date with $S \ge F^*_s$ | local date |

With $T_{base} = 0$ °C, $\max(0, T_{mean})$ is used, i.e. days with a negative mean add
nothing (they do not subtract).

## Period and aggregation

- Accumulation from March 1 to October 31 (the end is a project default: a stage not reached by
  then is "not reached"). Parker et al. (2011) define the start as day of year 60; here it is
  defined as **March 1 in every year** (in leap years DOY 60 would be February 29).
- Only complete days (`coverage >= analytics.min_daily_coverage`) are accumulated; an incomplete
  day is skipped, which **delays** the predicted date.
- `value` = day of year of **véraison** (local date); `None` if not reached.
- `details`: `flowering_date`, `flowering_doy`, `veraison_date`, `veraison_doy` (ISO dates or
  `"not reached"`), the critical sums and `thermal_sum_c_d` (sum over the whole available
  period); `status` when véraison is not reached.
- `coverage`/`complete` refer to the days from March 1 to véraison, or to the whole period if
  véraison is not reached (so a running season is incomplete until véraison).
- `daily` = cumulative thermal sum.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `base_temp_c` | 0.0 | °C | Parker et al. (2011) |
| `period` | March 1 – October 31 | local month-day | start: Parker et al. (2011); end: project default |
| `flowering_f_star_c_d` | 1282 | °C·d | general model, Parker et al. (2011) [to be verified] |
| `veraison_f_star_c_d` | 2528 | °C·d | general model, Parker et al. (2011) [to be verified] |
| `daily_mean` | `minmax` | — | project default |

The two critical sums are the values of the general GFV model as I recall them from Parker et
al. (2011); they are **[to be verified]** against the paper. Cultivar-specific values are in
Parker et al. (2013); none are shipped. Set them per sensor once the cultivar is known
(MIGRATION_PLAN §0.6, Q4).

## Interpretation

No classes. Compare predicted dates between sensors and seasons; a difference of a few days
between sensors is meaningful only if both have complete data.

## Assumptions and limitations

- The general model ignores cultivar differences (up to weeks between early and late varieties).
- Not calibrated locally; Parker et al. (2011) fitted it on station temperatures, ours are
  in-canopy.
- Skipped incomplete days delay the prediction; a sensor deployed after March 1 cannot predict
  until a full season of data exists.

## Implementation

- Class `GfvIndex` with `GfvParams` in `src/sivin/analytics/thermal/phenology.py`, a subclass
  of `ThermalTimePhenologyIndex`; accumulation by `ThermalTimeModel` (`thermal_time.py`).
- Tests: `tests/analytics/thermal/test_phenology.py` (both stages reached, véraison not
  reached, running season, empty season, parameter validation).

## References

- Parker, A. K., García de Cortázar-Atauri, I., van Leeuwen, C., Chuine, I. (2011). General
  phenological model to characterise the timing of flowering and veraison of *Vitis vinifera*
  L. *Australian Journal of Grape and Wine Research*, 17, 206–216. [DOI not verified]
- Parker, A. K. et al. (2013). Classification of varieties for their timing of flowering and
  veraison using a modelling approach: a case study for the grapevine species *Vitis vinifera*
  L. *Agricultural and Forest Meteorology*, 180, 249–264. [DOI not verified]
