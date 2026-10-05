# Vapour pressure deficit (`vpd`)

## Purpose

The vapour pressure deficit (VPD) is the drying power of the air: the difference between the
vapour pressure at saturation and the actual vapour pressure. High VPD raises transpiration and
can induce stomatal closure and water stress; low VPD favours long leaf wetness. The index
reports the daily maxima, the time above a threshold and, optionally, the daytime mean.

## Definition

FAO-56 (Allen et al., 1998, eq. 11 and the RH-based actual vapour pressure):

$$e_s(T) = 0.6108\,\exp\left(\frac{17.27\,T}{T + 237.3}\right), \qquad
e_a = e_s(T)\,\frac{RH}{100}, \qquad VPD = e_s(T) - e_a$$

| Symbol | Meaning | Unit |
|---|---|---|
| $T$ | air temperature | °C |
| $RH$ | relative humidity | % |
| $e_s$ | saturation vapour pressure | kPa |
| $e_a$ | actual vapour pressure | kPa |
| $VPD$ | vapour pressure deficit | kPa |

Per complete day $d$: $VPD_{max,d} = \max_{i \in d} VPD_i$. Index value:
$\overline{VPD_{max}} = \frac{1}{N}\sum_d VPD_{max,d}$.

Hours above threshold (durations as in [`heat_hours`](heat_hours.md)):
$H = \frac{1}{3600}\sum_i \Delta t_i\,\mathbf{1}[VPD_i > VPD_{thr}]$.

Optional daytime mean: duration-weighted mean of $VPD_i$ (weights $\Delta t_i$) over samples whose local clock hour $h$
satisfies `daytime_start_hour` ≤ $h$ < `daytime_end_hour`.

## Period and aggregation

- Default April 1 – October 31 (growing season; project choice `[to be tuned]`).
- A day counts only when both its temperature and humidity coverage reach
  `analytics.min_daily_coverage` (the index filters `rh_coverage` itself); `complete` follows
  `analytics.min_season_coverage`. Without any usable day the value is `None`.
- `RH <= 0 %` is a sensor artefact and gives `NaN` (as for the dew point); such samples are
  counted in `details["n_rh_non_positive"]` and logged. `RH > 100 %` gives a negative VPD and
  is passed through.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `period_start` / `period_end` | `04-01` / `10-31` | MM-DD | growing season, project choice `[to be tuned]` |
| `threshold_kpa` | 2.0 | kPa | project default `[to be tuned]`, not from literature |
| `daytime_start_hour` | `None` | h (local) | optional |
| `daytime_end_hour` | `None` | h (local) | optional |
| `sampling.max_sample_duration_s` | 4575 | s | project default `[to be tuned]` (2.5 × 1830 s) |
| `sampling.nominal_interval_s` | 1830 | s | nominal sampling interval; always set from `time.expected_interval_s` (WP-1.7) |

## Interpretation

No literature classes are used; the threshold is a project value to be tuned. Compare sensors
and seasons; high daily maxima and many hours above the threshold indicate a strong atmospheric
demand for water.

## Assumptions and limitations

- FAO-56 eq. 11 applied to instantaneous samples (FAO-56 averages $e_s$ of $T_{max}$ and
  $T_{min}$ for daily values; here each sample is used directly).
- Air at sensor height; leaf-to-air VPD would need leaf temperature.
- "Daytime" is a fixed clock window, not sunrise–sunset (no radiation sensor).

## Implementation

- Pure functions `saturation_vapour_pressure_kpa(temp_c)` and
  `vapour_pressure_deficit_kpa(temp_c, rh_pct)` in
  `src/sivin/analytics/ripening/psychrometry.py`.
- Class `VpdIndex`, parameters `VpdParams` in `src/sivin/analytics/ripening/vpd.py`.
- `IndexResult.daily`: daily maximum VPD. `details`: `hours_above_threshold_h`,
  `threshold_kpa`, `max_vpd_kpa`, `n_rh_non_positive`, optionally `mean_daytime_vpd_kpa`, `n_days`.
- Tests: `tests/analytics/ripening/test_formulas.py::TestVapourPressure`,
  `tests/analytics/ripening/test_hour_indices.py::TestVpd`.

## References

- Allen, R. G., Pereira, L. S., Raes, D., Smith, M. (1998). *Crop evapotranspiration —
  Guidelines for computing crop water requirements.* FAO Irrigation and Drainage Paper 56. FAO,
  Rome. (No DOI.) Chapter 3, eq. 11, https://www.fao.org/4/x0490e/x0490e07.htm — the constants
  0.6108 kPa, 17.27 and 237.3 °C were verified in WP-L.1.
