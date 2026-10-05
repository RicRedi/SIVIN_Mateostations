# Growing degree-days / Winkler index (`gdd_winkler`)

## Purpose

Heat available to the grapevine during the growing season, accumulated above the temperature
below which grapevine development is assumed to stop. The seasonal sum classifies a site into
the Winkler regions I–V (Amerine & Winkler, 1944), which relate climate to the grape varieties
and wine styles that ripen well there. The cumulative curve shows how far the current season is
ahead of or behind other seasons and sensors.

## Definition

$$
\mathrm{GDD} = \sum_{d \in P} \max\left(0,\; T_{mean,d} - T_{base}\right),
\qquad T_{mean,d} = \frac{T_{max,d} + T_{min,d}}{2}
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $P$ | complete local days of the period (see below) | — |
| $T_{max,d}$, $T_{min,d}$ | maximum and minimum of the valid samples of day $d$ | °C |
| $T_{mean,d}$ | daily mean; by default the Winkler convention $(T_{max}+T_{min})/2$ | °C |
| $T_{base}$ | base temperature, 10 °C (50 °F) | °C |
| GDD | growing degree-days | °C·d |

The cumulative curve $\mathrm{GDD}(d) = \sum_{d' \le d} \max(0, T_{mean,d'} - T_{base})$ is
returned as `IndexResult.daily`.

## Period and aggregation

- Period: April 1 – October 31 of the season year (local calendar days, Europe/Prague).
- Daily values from `DailyWeather` (local calendar days; QC-excluded samples removed).
- Only days with `coverage >= analytics.min_daily_coverage` are summed; incomplete days are
  skipped (contribute nothing).
- `coverage` = complete days / 214 days; `complete` = `coverage >= analytics.min_season_coverage`.
- The Winkler region is assigned **only to a complete season**; a partial sum would always fall
  into a too cool region.
- No complete day in the period → `value = None` with detail `status`.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `base_temp_c` | 10.0 | °C | Amerine & Winkler (1944): 50 °F |
| `daily_mean` | `minmax` | — | Winkler convention $(T_{max}+T_{min})/2$; `sample_mean` = mean of all valid samples |
| `period` | `{start: {month: 4, day: 1}, end: {month: 10, day: 31}}` | local month-day | Amerine & Winkler (1944), northern hemisphere |
| `regions` | bounds below | °C·d | Amerine & Winkler (1944), converted from °F·d |

## Interpretation

Winkler regions (Amerine & Winkler, 1944) are defined in °F·d. A temperature *difference* of
1 °F equals 5/9 °C, so the bounds convert by the factor 5/9 without an offset:

| Region | °F·d (original) | °C·d (exact = °F·d × 5/9) | °C·d (usually quoted) |
|---|---|---|---|
| I (`region_i`) | ≤ 2500 | ≤ 1388.9 | < 1389 |
| II (`region_ii`) | 2500 – 3000 | 1388.9 – 1666.7 | 1389 – 1667 |
| III (`region_iii`) | 3000 – 3500 | 1666.7 – 1944.4 | 1667 – 1944 |
| IV (`region_iv`) | 3500 – 4000 | 1944.4 – 2222.2 | 1944 – 2222 |
| V (`region_v`) | > 4000 | > 2222.2 | > 2222 |

Arithmetic check: 2500 × 5/9 = 1388.89; 3000 × 5/9 = 1666.67; 3500 × 5/9 = 1944.44;
4000 × 5/9 = 2222.22. The implementation uses the exact converted bounds. The original classes
were given in whole °F·d (e.g. region II "2501–3000"); the implementation treats every bound as
**inclusive upper bound** (a value equal to a bound belongs to the lower region).

## Assumptions and limitations

- Only air temperature is measured (plus relative humidity, unused here); sampling ~1825 s.
  $T_{max}$ and $T_{min}$ of ~47 samples per day slightly underestimate the true extremes
  compared with a continuously recording thermometer, so GDD by `minmax` can be a little lower
  than a station value.
- The sensors are inside the canopy zone of a few vineyards, not standard screens at 2 m; the
  values describe the vineyard microclimate, not the regional climate the Winkler regions were
  calibrated on.
- Skipped incomplete days make the sum smaller; check `coverage`/`complete` before comparing
  seasons.
- Legacy difference: `vineyard_analyst.calculate_gdd` summed over the whole selected period
  (not April–October) and used every day regardless of completeness. On complete in-season
  data both give the same value (parity test).

## Implementation

- Class `GddWinklerIndex` with `GddWinklerParams` in `src/sivin/analytics/thermal/gdd.py`.
- Accumulation by `ThermalTimeModel` (`thermal_time.py`), daily mean by `daily_mean.py`,
  regions by `IntervalClassification` (`classification.py`), °F·d → °C·d by
  `fahrenheit_to_celsius_degree_days` (`formulas.py`).
- Tests: `tests/analytics/thermal/test_gdd_huglin.py` (hand-computed example, full season,
  incomplete and empty season, legacy parity), `test_formulas.py` (bound conversion).

## References

- Amerine, M. A., Winkler, A. J. (1944). Composition and quality of musts and wines of
  California grapes. *Hilgardia*, 15(6), 493–675. [DOI not verified]
- Winkler, A. J., Cook, J. A., Kliewer, W. M., Lider, L. A. (1974). *General Viticulture.*
  University of California Press, Berkeley.
