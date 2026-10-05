# Tropical days and nights, characteristic days (`tropical_days_nights`)

## Purpose

Counts of characteristic days as used in Czech climatology (ČHMÚ): tropical days and nights
describe summer heat, summer days warm conditions, frost and ice days winter cold. The index is
a port of the legacy `calculate_tropical_extremes` (`vineyard_analyst.py`), extended by the
other characteristic days.

## Definition

For each complete local calendar day $d$ in the period:

| Category | Condition | Result key |
|---|---|---|
| tropical day | $T_{max,d} \ge 30$ °C | `tropical_days` (the index value) |
| tropical night | $T_{min,d} \ge 20$ °C | `tropical_nights` |
| summer day | $T_{max,d} \ge 25$ °C | `summer_days` |
| frost day | $T_{min,d} < 0$ °C | `frost_days` |
| ice day | $T_{max,d} < 0$ °C | `ice_days` |

$$N_c = \sum_{d} \mathbf{1}\left[\text{day } d \text{ meets the condition of category } c\right]$$

| Symbol | Meaning | Unit |
|---|---|---|
| $T_{max,d}$, $T_{min,d}$ | maximum / minimum air temperature of local day $d$ | °C |
| $N_c$ | number of days of category $c$ | d |

## Period and aggregation

- Default the calendar year (January 1 – December 31 of the season year).
- Daily extremes from `DailyWeather`; only complete days (`analytics.min_daily_coverage`),
  `complete` from `analytics.min_season_coverage`. Without any complete day the value is
  `None`.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `period_start` / `period_end` | `01-01` / `12-31` | MM-DD | calendar year |
| `tropical_day_tmax_c` | 30.0 | °C | ČHMÚ definition (also legacy script) |
| `tropical_night_tmin_c` | 20.0 | °C | ČHMÚ definition (also legacy script) |
| `summer_day_tmax_c` | 25.0 | °C | ČHMÚ definition |
| `frost_day_tmin_c` | 0.0 (strict `<`) | °C | ČHMÚ definition |
| `ice_day_tmax_c` | 0.0 (strict `<`) | °C | ČHMÚ definition |

## Interpretation

Counts per season; compare years and sensors. No further classes.

## Assumptions and limitations

- **Tropical night approximation:** strictly, a tropical night concerns the minimum temperature
  of the night. Here, as in the legacy script, the
  minimum of the local **calendar day** (00–24 h) is used, which mixes the end of one night with
  the start of the next.
- Extremes come from samples about every 30 min, not from extreme thermometers; true maxima are
  slightly higher and true minima slightly lower, so counts near the thresholds can differ from
  a climatological station.
- The exact ČHMÚ source document of the definitions is `[to be verified]`; the thresholds are
  the generally used Czech climatological ones.

## Implementation

- Class `CharacteristicDaysIndex`, parameters `CharacteristicDaysParams`, value object
  `DayCategory` in `src/sivin/analytics/ripening/characteristic_days.py`.
- `IndexResult.daily`: cumulative number of tropical days. `details`: all five counts, `n_days`.
- Tests: `tests/analytics/ripening/test_daily_indices.py::TestCharacteristicDays`.

## References

- Czech Hydrometeorological Institute (ČHMÚ): climatological definitions of characteristic days
  (tropical, summer, frost and ice days, tropical night). `[source document to be verified]`
