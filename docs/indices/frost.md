# Frost hours and frost nights (`frost`)

## Purpose

Spring frost after budburst can kill young shoots and inflorescences; the critical temperature
depends on the phenological stage (reviewed by Poling, 2008). The index measures how long the
temperature was at or below frost thresholds, how many frost nights occurred and the absolute
minimum, and optionally reports the same figures from a given date on (e.g. modelled budburst),
where frost is critical.

It replaces the legacy `frost_events_count`, which counted **rows** at or below 0 °C; with about
two samples per hour that number is not a time and depends on the sampling. This index returns
**hours**.

## Definition

Sample durations as in [`heat_hours`](heat_hours.md):
$\Delta t_i = t_{i+1} - t_i$ if that step is at most $\Delta t_{max}$, otherwise (data gap)
and for the last sample the nominal interval $\Delta t_{nom}$; split at local midnight.

$$H_{frost} = \frac{1}{3600}\sum_{i \in D} \Delta t_i\,\mathbf{1}[T_i \le T_{frost}], \qquad
H_{hard} = \frac{1}{3600}\sum_{i \in D} \Delta t_i\,\mathbf{1}[T_i \le T_{hard}]$$

$$N_{nights} = \sum_{d \in D} \mathbf{1}[T_{min,d} < T_{frost}], \qquad
T_{abs} = \min_{d \in D} T_{min,d}$$

With `after_date` $d_0$ the same quantities over $D_{crit} = \{d \in D : d \ge d_0\}$ are
reported with the prefix `critical_`.

| Symbol | Meaning | Unit |
|---|---|---|
| $D$ | complete local days of the period | — |
| $T_i$ | air temperature of sample $i$ | °C |
| $T_{min,d}$ | minimum temperature of local day $d$ | °C |
| $T_{frost}$, $T_{hard}$ | `frost_c`, `hard_frost_c` | °C |
| $H_{frost}$ | frost hours (the index value) | h |
| $H_{hard}$ | hard-frost hours | h |
| $N_{nights}$ | frost nights ($T_{min,d} < T_{frost}$, strict, as the ČHMÚ frost day) | d |
| $T_{abs}$ | absolute minimum | °C |

## Period and aggregation

- Default April 1 – October 31 (growing season; project choice `[to be tuned]`).
- Only complete days count; `complete` follows `analytics.min_season_coverage`. Excluded and
  missing samples count nothing. Without any complete day the value is `None`.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `period_start` / `period_end` | `04-01` / `10-31` | MM-DD | growing season (Amerine & Winkler 1944), project choice `[to be tuned]` |
| `frost_c` | 0.0 (≤) | °C | MIGRATION_PLAN §3.2 |
| `hard_frost_c` | −2.0 (≤) | °C | project default (MIGRATION_PLAN §3.2), not a literature value |
| `after_date` | `None` | date | e.g. modelled budburst (WP-2.1); must lie in the season year |
| `sampling.max_sample_duration_s` | 4575 | s | project default `[to be tuned]` (2.5 × 1830 s) |
| `sampling.nominal_interval_s` | 1830 | s | nominal sampling interval; always set from `time.expected_interval_s` (WP-1.7) |

## Interpretation

Any frost hour after budburst is a potential damage event. Stage-specific critical temperatures
are reviewed by Poling (2008); the values in that review are not copied here because its table
could not be read in WP-L.1. The defaults 0 °C and −2 °C are thresholds of the project plan,
not literature values; secondary sources citing Poling (2008) mention serious damage of green
tissue after budburst below about −2.2 °C (28 °F).

## Assumptions and limitations

- Air temperature at sensor height, not bud or tissue temperature; radiative cooling of buds on
  clear nights can bring them below air temperature.
- "Frost night" uses the minimum of the local calendar day (00–24 h), not of the night, and
  the strict condition $T_{min} < 0$ °C of the ČHMÚ frost day, so it agrees with
  `tropical_days_nights.frost_days`. Frost **hours** use $T \le 0$ °C: a day with
  $T_{min} = 0.0$ °C has frost hours but no frost night.
- Samples about every 30 min miss short dips between samples.

## Implementation

- Class `FrostIndex`, parameters `FrostParams` in `src/sivin/analytics/ripening/frost.py`;
  durations from `SampleDurations` (`durations.py`).
- `IndexResult.daily`: frost hours per day. `details`: `frost_h`, `hard_frost_h`,
  `frost_nights`, `min_temp_c`, `n_days` and, with `after_date`, `after_date` and the
  `critical_*` figures.
- Tests: `tests/analytics/ripening/test_hour_indices.py::TestFrost` (hours vs rows, irregular
  sampling gives the same hours).

## References

- Poling, E. B. (2008). Spring cold injury to winegrapes and protection strategies and methods.
  *HortScience*, 43(6), 1652–1662. https://doi.org/10.21273/HORTSCI.43.6.1652
- Amerine, M. A., Winkler, A. J. (1944). Composition and quality of musts and wines of
  California grapes. *Hilgardia*, 15(6), 493–675. https://doi.org/10.3733/hilg.v15n06p493
