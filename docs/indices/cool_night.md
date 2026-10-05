# Cool Night Index (`cool_night`)

## Purpose

The Cool Night Index (CI) describes the night-time temperatures during the last weeks of
ripening. Cool nights during ripening are associated with better retention of colour and aroma
compounds; warm nights with faster loss of acidity. It is one of the three indices of the
multicriteria climatic classification (MCC) of Tonietto and Carbonneau (2004).

## Definition

$$CI = \frac{1}{N}\sum_{d=1}^{N} T_{min,d}$$

| Symbol | Meaning | Unit |
|---|---|---|
| $T_{min,d}$ | minimum air temperature of local calendar day $d$ | °C |
| $N$ | number of complete days in September | — |
| $CI$ | Cool Night Index | °C |

## Period and aggregation

- September 1–30 of the season year (northern hemisphere; March in the southern hemisphere).
- $T_{min,d}$ is the minimum of the valid raw samples of the local (Europe/Prague) calendar
  day, from `DailyWeather` (`temp_min`).
- Only days with `coverage >= analytics.min_daily_coverage` are used. The result is
  `complete` when the share of complete days in the period reaches
  `analytics.min_season_coverage`.
- Without any complete day the value is `None`.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `period_start` | `09-01` | MM-DD | Tonietto & Carbonneau (2004) |
| `period_end` | `09-30` | MM-DD | Tonietto & Carbonneau (2004) |

## Interpretation

Classes of Tonietto and Carbonneau (2004):

| Class | Label in results | CI |
|---|---|---|
| CI+2 very cool nights | `very_cool_nights` | $CI \le 12$ °C |
| CI+1 cool nights | `cool_nights` | $12 < CI \le 14$ °C |
| CI-1 temperate nights | `temperate_nights` | $14 < CI \le 18$ °C |
| CI-2 warm nights | `warm_nights` | $CI > 18$ °C |

Bounds and inclusive sides (≤ 12, > 12 ≤ 14, > 14 ≤ 18, > 18 °C) were verified in WP-L.1
against secondary sources quoting the classification table of Tonietto and Carbonneau (2004)
(see [literature verification](../literature-verification.md)): a value equal to a boundary
belongs to the cooler class, as implemented.

## Assumptions and limitations

- The daily minimum is taken from samples about every 30 min (1825 s); the true minimum between
  two samples can be lower, so CI is slightly overestimated compared with a station that
  records continuous extremes.
- The calendar-day minimum (00–24 h local time) is used, not the minimum of a night.
- The original classification was built on standard weather-station data (screen height);
  vineyard sensors may be placed at a different height and in a cold-air pooling position.

## Implementation

- Class `CoolNightIndex`, parameters `CoolNightParams`, classes `COOL_NIGHT_CLASSES` in
  `src/sivin/analytics/ripening/cool_night.py`.
- `IndexResult.daily`: the daily minima used. `details`: `n_days`.
- Tests: `tests/analytics/ripening/test_daily_indices.py::TestCoolNight`.

## References

- Tonietto, J., Carbonneau, A. (2004). A multicriteria climatic classification system for
  grape-growing regions worldwide. *Agricultural and Forest Meteorology*, 124(1–2), 81–97.
  https://doi.org/10.1016/j.agrformet.2003.06.001
