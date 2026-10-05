# Grapevine Sugar Ripeness model (`gsr`)

## Purpose

Predicts the date on which grape sugar concentration reaches a target (e.g. 170–220 g/L) from
accumulated heat, with critical sums per cultivar and target (Parker et al., 2020). **The
predictions are orientational** until calibrated against local ripening data.

## Definition

$$
S(d) = \sum_{d' = t_0}^{d} \max\left(0,\; T_{mean,d'} - T_{base}\right),
\qquad \hat d_j = \min\{\, d : S(d) \ge F^*_j \,\}
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $t_0$ | start of accumulation, April 1 (day of year 91 in common years) | local date |
| $T_{mean,d}$ | daily mean, by default $(T_{max}+T_{min})/2$ | °C |
| $T_{base}$ | base temperature, 0 °C | °C |
| $F^*_j$ | critical sum of target $j$ (cultivar and sugar concentration) | °C·d |
| $\hat d_j$ | predicted date of target $j$ | local date |

## Period and aggregation

- April 1 – October 31 (the end is a project default); April 1 is used in every year.
- Only complete days are accumulated; incomplete days delay the prediction.
- `value` = day of year of the **last** configured target; per-target `<label>_date`,
  `<label>_doy`, `<label>_f_star_c_d` and `thermal_sum_c_d` in `details`.
- `coverage`/`complete` refer to the days from April 1 to the last target, or the whole period
  if it is not reached.
- **Without targets** (the default) the result is `value = None` with
  `details["status"] = "not configured"`.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `base_temp_c` | 0.0 | °C | Parker et al. (2020) |
| `period` | April 1 – October 31 | local month-day | start: Parker et al. (2020); end: project default |
| `targets` | none | list of `{label, f_star_c_d}` (°C·d) | user-supplied from Parker et al. (2020) |
| `daily_mean` | `minmax` | — | project default |

Targets must have unique lower-case labels (e.g. `sugar_200_g_l`) and increasing critical sums.
**No cultivar values are shipped**: they depend on the cultivar of each sensor (unknown,
MIGRATION_PLAN §0.6 Q4) and must be copied from Parker et al. (2020) by the owner.

Example configuration (numbers are placeholders, not literature values):

```yaml
gsr:
  targets:
    - {label: sugar_200_g_l, f_star_c_d: <F* from Parker et al. 2020>}
```

## Interpretation

No classes; the predicted date and its difference between sensors and seasons.

## Assumptions and limitations

- Sugar ripeness also depends on crop load, water status and management, which the model
  ignores.
- Fitted on station data; in-canopy sensors may differ.
- One target set per index configuration: sensors with different cultivars need per-sensor
  parameters (to be decided in the integration WP).

## Implementation

- Class `GsrIndex` with `GsrParams` and `PhenologyStage` in
  `src/sivin/analytics/thermal/phenology.py`; accumulation by `ThermalTimeModel`.
- Tests: `tests/analytics/thermal/test_phenology.py` (not configured, two synthetic targets,
  validation).

## References

- Parker, A. K. et al. (2020). Temperature-based grapevine sugar ripeness modelling for a wide
  range of *Vitis vinifera* L. cultivars. *Agricultural and Forest Meteorology*, 285–286,
  107902. [DOI not verified]
