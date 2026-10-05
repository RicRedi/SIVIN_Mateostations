# Diurnal temperature range during ripening (`dtr_ripening`)

## Purpose

The mean diurnal temperature range (DTR) during ripening describes the contrast between warm days
and cool nights while the berries ripen. Tonietto and Carbonneau (2004) use the night
temperature (Cool Night Index) as the ripening criterion; the DTR complements it with the
day-night contrast. The plan (MIGRATION_PLAN §3.2) cites Tonietto and Carbonneau (2004) for it.
It is a descriptive index without literature classes.

## Definition

$$DTR = \frac{1}{N}\sum_{d=1}^{N} \left(T_{max,d} - T_{min,d}\right)$$

| Symbol | Meaning | Unit |
|---|---|---|
| $T_{max,d}$, $T_{min,d}$ | maximum and minimum air temperature of local day $d$ | °C |
| $N$ | number of complete days in the ripening window | — |
| $DTR$ | mean diurnal temperature range | °C |

## Period and aggregation

- Ripening window: `period_start`..`period_end` (default August 1 – September 30), or
  `start_date`..`period_end` when an explicit start date is given. The integration (WP-1.7) is
  meant to pass the modelled véraison date of the season (WP-2.1, `gfv`) as `start_date`.
  `start_date` must lie in the computed season year.
- Daily extremes from `DailyWeather`; only complete days (`analytics.min_daily_coverage`);
  `complete` from `analytics.min_season_coverage` relative to the window length.
- Without any complete day the value is `None`.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `period_start` | `08-01` | MM-DD | project default `[to be tuned]` |
| `period_end` | `09-30` | MM-DD | project default `[to be tuned]` |
| `start_date` | `None` | date | e.g. modelled véraison (WP-2.1) |

## Interpretation

No classes are defined. Larger values mean a stronger day–night contrast. Compare sensors and
seasons with each other rather than with absolute thresholds.

## Assumptions and limitations

- The extremes come from samples about every 30 min; both are slightly damped, so the DTR is
  slightly underestimated.
- The default window is a fixed calendar window; ripening in South Moravia depends on variety
  and season, so a modelled véraison date is preferable once available.

## Implementation

- Class `DtrRipeningIndex`, parameters `DtrRipeningParams` (method `window(year)`) in
  `src/sivin/analytics/ripening/dtr.py`.
- `IndexResult.daily`: daily ranges (°C). `details`: `n_days`, `window_start`, `window_end`.
- Tests: `tests/analytics/ripening/test_daily_indices.py::TestDtrRipening`.

## References

- Tonietto, J., Carbonneau, A. (2004). A multicriteria climatic classification system for
  grape-growing regions worldwide. *Agricultural and Forest Meteorology*, 124(1–2), 81–97.
  https://doi.org/10.1016/j.agrformet.2003.06.001
