# Budburst estimate (`budburst`)

## Purpose

Orientational date of budburst from a thermal-time sum. Budburst marks the start of the
season and of the frost-sensitive period (used by frost indices of WP-2.2). García de
Cortázar-Atauri et al. (2009) compare several budburst models (forcing-only and
chilling-plus-forcing); this index implements the simplest forcing-only form with **fully
configurable parameters and no critical sum claimed from literature**. Results carry
`estimated = True` until calibrated against local BBCH observations.

## Definition

$$
S(d) = \sum_{d' = t_0}^{d} \max\left(0,\; T_{mean,d'} - T_{base}\right),
\qquad \hat d = \min\{\, d : S(d) \ge F^* \,\}
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $t_0$ | start of accumulation (default January 1, project default) | local date |
| $T_{mean,d}$ | daily mean, by default $(T_{max}+T_{min})/2$ | °C |
| $T_{base}$ | base temperature (default 5 °C [to be verified]) | °C |
| $F^*$ | critical sum (no default) | °C·d |
| $\hat d$ | predicted budburst date | local date |

Chilling (dormancy release) is not modelled.

## Period and aggregation

- January 1 – June 30 by default (project default, not from literature).
- Only complete days accumulate; incomplete days delay the prediction.
- `value` = day of year of the predicted budburst; `details`: `budburst_date`, `budburst_doy`,
  `budburst_f_star_c_d`, `thermal_sum_c_d`.
- `coverage`/`complete` refer to the days from the start to budburst (or the whole period).
- **Without `f_star_c_d`** (the default): `value = None`, `details["status"] = "not
  configured"`.
- Always `estimated = True`.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `base_temp_c` | 5.0 | °C | project default [to be verified] |
| `period` | January 1 – June 30 | local month-day | project default |
| `f_star_c_d` | none | °C·d | must be calibrated locally |
| `daily_mean` | `minmax` | — | project default |

## Interpretation

No classes. Treat the date as a rough indication; compare between sensors only with complete
data.

## Assumptions and limitations

- No chilling requirement; a warm spell in winter advances the predicted date.
- Base temperature and critical sum are not taken from a verified source; they need
  calibration on local BBCH 05/07 observations (proposed phenology log, outside this plan).
- The sensors must be deployed outdoors from the start date on; office records are excluded by
  QC (`PRE_DEPLOYMENT`), which leaves the days incomplete and the season incomplete.

## Implementation

- Class `BudburstIndex` with `BudburstParams` in `src/sivin/analytics/thermal/phenology.py`;
  accumulation by `ThermalTimeModel` (`thermal_time.py`).
- Tests: `tests/analytics/thermal/test_phenology.py` (not configured, configured with a
  synthetic F*, incomplete day).

## References

- García de Cortázar-Atauri, I., Brisson, N., Gaudillère, J. P. (2009). Performance of several
  models for predicting budburst date of grapevine (*Vitis vinifera* L.). *International
  Journal of Biometeorology*, 53, 317–326. [DOI not verified]
