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
- `value` = day of year of the **last** configured target (local date in `details["date"]`);
  per-target `<label>_date`,
  `<label>_doy`, `<label>_f_star_c_d` and `thermal_sum_c_d` in `details`.
- `coverage`/`complete` refer to the days from April 1 to the last target, or the whole period
  if it is not reached.
- **Without targets** (the default) the result is `value = None` with
  `details["status"] = "not configured"`.
- **Missing days delay the date.** An incomplete day contributes nothing (no gap filling), so
  the sum lags behind and the predicted date is late. `details["n_missing_days"]` = incomplete
  days from the period start to the predicted stage (or to the period end); `complete` follows
  the plan's coverage rule and does not mean unbiased.
- **Accumulation start not covered.** If more than `max_missing_days_at_start` (default 0)
  days are missing before the first complete day of the period (e.g. a sensor deployed after
  the start), the result is `value = None` with `details["status"] = "accumulation start not
  covered"` and `details["n_missing_days_at_start"]`.
- **DOY and leap years.** `value` is the day of year of the local date, which is also given as
  `details["date"]` (ISO). In leap years every date after February has a DOY one higher than
  in common years, so compare dates, not DOY values, across years.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `base_temp_c` | 0.0 | °C | Parker et al. (2020); verified (WP-L.1) |
| `period` | April 1 – October 31 | local month-day | start: day of year 91, Parker et al. (2020), verified (WP-L.1); end: project default |
| `targets` | none | list of `{label, f_star_c_d}` (°C·d) | user-supplied from Parker et al. (2020) |
| `max_missing_days_at_start` | 0 | d | project default, to be tuned |
| `daily_mean` | `minmax` | — | project default |

Targets must have unique lower-case labels (e.g. `sugar_200_g_l`) and increasing critical sums.
**No targets are active by default**: they depend on the cultivar of each sensor (unknown,
MIGRATION_PLAN §0.6 Q4).

Parker et al. (2020) give F* for six sugar targets (170, 180, 190, 200, 210 and 220 g/L) for 65
cultivars (base 0 °C, from day of year 91). WP-L.1 could not read the table of the paper; only
values quoted consistently by secondary sources are provided, as the **optional preset**
`GSR_CULTIVAR_PRESETS` in `sivin.analytics.thermal` (not active unless configured):

| Preset key | Target | F* (°C·d) | Source |
|---|---|---|---|
| `sauvignon_blanc` | `sugar_200_g_l` (200 g/L) | 2820 | Parker et al. (2020), quoted by Ausseil et al. (2021) |

No value could be confirmed for Grüner Veltliner, Riesling, Pinot blanc, Chardonnay,
Müller-Thurgau, Welschriesling, Pinot noir, Blaufränkisch, Saint Laurent or Zweigelt (for
Chardonnay the sources found disagree on the sugar target of the quoted value); see
[literature verification](../literature-verification.md). Further cultivars belong in the preset
only after their value has been read in Parker et al. (2020).

Example configuration (the Sauvignon blanc preset):

```yaml
gsr:
  targets:
    - {label: sugar_200_g_l, f_star_c_d: 2820.0}
```

In Python: `GsrParams(targets=GSR_CULTIVAR_PRESETS["sauvignon_blanc"])`.

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
- Optional cultivar preset `GSR_CULTIVAR_PRESETS` in `phenology.py`.
- Tests: `tests/analytics/thermal/test_phenology.py` (not configured, two synthetic targets,
  validation, Sauvignon blanc preset).

## References

- Parker, A. K., García de Cortázar-Atauri, I., Gény, L., Spring, J.-L., Destrac, A., Schultz,
  H., et al. (2020). Temperature-based grapevine sugar ripeness modelling for a wide range of
  *Vitis vinifera* L. cultivars. *Agricultural and Forest Meteorology*, 285–286, 107902.
  https://doi.org/10.1016/j.agrformet.2020.107902
- Ausseil, A.-G. E., Law, R. M., Parker, A. K., Teixeira, E. I., Sood, A. (2021). Projected wine
  grape cultivar shifts due to climate change in New Zealand. *Frontiers in Plant Science*, 12,
  618039. https://doi.org/10.3389/fpls.2021.618039 (secondary source of the preset value)
