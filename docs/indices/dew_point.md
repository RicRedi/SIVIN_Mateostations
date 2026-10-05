# Dew point (`dew_point`)

## Purpose

The dew point is the temperature to which air must cool to become saturated. When the canopy
cools to the dew point, dew forms and leaves stay wet, which favours fungal diseases. The mean
dew-point depression $T - T_d$ describes how close the air is to saturation. The formula is also
available as a pure function for other modules (e.g. disease models).

## Definition

Magnus form (Alduchov and Eskridge, 1996):

$$\gamma = \ln\left(\frac{RH}{100}\right) + \frac{a\,T}{b + T}, \qquad
T_d = \frac{b\,\gamma}{a - \gamma}$$

| Symbol | Meaning | Unit |
|---|---|---|
| $T$ | air temperature | °C |
| $RH$ | relative humidity | % |
| $a$ | Magnus coefficient, 17.625 | — |
| $b$ | Magnus coefficient, 243.04 | °C |
| $T_d$ | dew point | °C |

$RH \le 0$ is physically impossible (sensor error) and $\ln$ is undefined: such samples get
**no** dew point (`NaN`) and are counted in `details["n_rh_non_positive"]` (with a warning). The
legacy script replaced 0 % by 0.0001 %, which produces an absurd dew point around −100 °C.

Daily means are **duration-weighted**: each sample weighs with the time it represents
(as in [`heat_hours`](heat_hours.md), split at local midnight), so densely sampled stretches
do not weigh more. Index value: the mean of the daily means of $T_d$; `mean_depression_c` the
mean of the daily means of $T - T_d$.

## Period and aggregation

- Default April 1 – October 31 (growing season; project choice `[to be tuned]`).
- A day counts only when **both** its temperature coverage and its humidity coverage
  (`rh_coverage`) reach `analytics.min_daily_coverage`; `DailyWeather.complete_days()` checks
  temperature only, so the index filters humidity itself. Coverage is the share of such days in
  the period; `complete` follows `analytics.min_season_coverage`.
- A sample counts when temperature and humidity are present and its row is not excluded.
- Without any usable day (or if no sample gives a dew point) the value is `None`.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `period_start` / `period_end` | `04-01` / `10-31` | MM-DD | growing season, project choice `[to be tuned]` |
| `magnus_a` | 17.625 | — | Alduchov & Eskridge (1996) |
| `magnus_b_c` | 243.04 | °C | Alduchov & Eskridge (1996) |
| `sampling.max_sample_duration_s` | 4562.5 | s | project default `[to be tuned]` (weights) |
| `sampling.nominal_interval_s` | 1825 | s | nominal sampling interval (weights) |

The legacy coefficients $a = 17.27$, $b = 237.7$ °C (`vineyard_analyst.py`) are available as
`LEGACY_MAGNUS` and can be configured; at 20 °C / 50 % they give 9.254 °C instead of 9.261 °C.

## Interpretation

No classes. A small depression (night-time near 0 °C) indicates likely dew formation and leaf
wetness; this is used qualitatively only.

## Assumptions and limitations

- Capacitive RH sensors are least accurate near saturation, exactly where the dew point matters
  most; readings above 100 % are passed through.
- Air at sensor height; leaf surfaces can be colder (radiative cooling), so dew can form while
  the air is above its dew point.

## Implementation

- Pure functions `dew_point_c(temp_c, rh_pct, coefficients)` and `non_positive_humidity(rh_pct)`,
  constants `ALDUCHOV_ESKRIDGE_1996`, `LEGACY_MAGNUS` in
  `src/sivin/analytics/ripening/psychrometry.py`.
- Class `DewPointIndex`, parameters `DewPointParams` in
  `src/sivin/analytics/ripening/dew_point.py`.
- `IndexResult.daily`: daily mean dew point. `details`: `mean_depression_c`,
  `n_rh_non_positive`, `magnus_a`, `magnus_b_c`, `n_days`.
- Tests: `tests/analytics/ripening/test_formulas.py::TestDewPoint`,
  `tests/analytics/ripening/test_hour_indices.py::TestDewPoint`.

## References

- Alduchov, O. A., Eskridge, R. E. (1996). Improved Magnus form approximation of saturation
  vapor pressure. *Journal of Applied Meteorology*, 35, 601–609. `[DOI not verified]`
