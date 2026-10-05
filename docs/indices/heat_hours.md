# Hours in temperature bands (`heat_hours`)

## Purpose

How long the vines spend in a temperature range favourable for photosynthesis and ripening, and
how long they are exposed to heat stress. High temperatures during ripening reduce the
accumulation of anthocyanins in red varieties (Mori et al., 2007); leaf photosynthesis
declines above its temperature optimum (Greer and Weedon, 2012). The thresholds below are the
project defaults of MIGRATION_PLAN §3.2, **not literature values**. WP-L.1 found only background
support: light-saturated leaf photosynthesis of Semillon was optimal at 30 °C (Greer and
Weedon, 2012, abstract), and a daily maximum of 35 °C halved the anthocyanin content of
Cabernet Sauvignon berries compared with 25 °C (Mori et al., 2007, abstract). The optimum band
20–30 °C has no source.

## Definition

Each valid raw sample $i$ represents the time until the next sample; a step longer than the
cap is a data gap, and the sample then represents only the nominal interval:

$$\Delta t_i = \begin{cases} t_{i+1} - t_i & \text{if } t_{i+1} - t_i \le \Delta t_{max} \\
\Delta t_{nom} & \text{otherwise (gap)} \end{cases}, \qquad \Delta t_{last} = \Delta t_{nom}$$

Hours in a band $B$ over the complete days $D$ of the period:

$$H_B = \frac{1}{3600}\sum_{i \in D} \Delta t_i \cdot \mathbf{1}\left[T_i \in B\right]$$

| Band | Condition | Result key |
|---|---|---|
| optimum | $T_{opt,min} \le T_i \le T_{opt,max}$ | `optimum_h` |
| heat stress | $T_i > T_{heat}$ | `heat_stress_h` (the index value) |
| extreme heat | $T_i > T_{extreme}$ | `extreme_heat_h` |

| Symbol | Meaning | Unit |
|---|---|---|
| $t_i$ | timestamp of sample $i$ (UTC) | s |
| $T_i$ | air temperature of sample $i$ | °C |
| $\Delta t_{max}$ | `sampling.max_sample_duration_s` | s |
| $\Delta t_{nom}$ | `sampling.nominal_interval_s` | s |
| $H_B$ | hours in band $B$ | h |

## Period and aggregation

- Default April 1 – October 31 (growing season of Amerine and Winkler, 1944).
- A sample's interval that crosses local midnight is split at midnight, so each part counts on
  its own local day. Excluded samples (`analytics.exclude_mask`) and missing values count
  nothing, and do not extend their predecessor.
- Only complete days (temperature coverage ≥ `analytics.min_daily_coverage`) count;
  `complete` follows `analytics.min_season_coverage`. Without any complete day the value is
  `None`.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `period_start` / `period_end` | `04-01` / `10-31` | MM-DD | Amerine & Winkler (1944) growing season |
| `optimum_min_c` | 20.0 | °C | project default (MIGRATION_PLAN §3.2), not a literature value |
| `optimum_max_c` | 30.0 | °C | project default (MIGRATION_PLAN §3.2), not a literature value |
| `heat_stress_c` | 30.0 | °C | project default (MIGRATION_PLAN §3.2); background Greer & Weedon (2012): photosynthesis optimum 30 °C |
| `extreme_heat_c` | 35.0 | °C | project default (MIGRATION_PLAN §3.2); background Mori et al. (2007): 35 °C treatment |
| `sampling.max_sample_duration_s` | 4562.5 | s | project default `[to be tuned]` (2.5 × 1825 s) |
| `sampling.nominal_interval_s` | 1825 | s | nominal sampling interval (legacy configs) |

## Interpretation

No literature classes are used. More heat-stress hours during ripening indicate a higher risk
of reduced anthocyanin accumulation (red varieties) and of reduced photosynthesis; the exact
response depends on variety and duration (Mori et al. studied one red variety, Greer and
Weedon one white variety).

## Assumptions and limitations

- Only air temperature is measured; berry temperature in direct sun can be several degrees
  higher, so the hours underestimate the heat load on exposed bunches.
- With ~30 min sampling each sample stands for ~30 min; short peaks between samples are missed.
- A sample followed by a gap longer than `max_sample_duration_s` counts only the nominal
  interval; the default cap of 2.5 × 1825 s still bridges one missed sample plus clock drift.
  The same rule is used by the disease models (WP-2.3), so the two copies can be unified.
  Days with gaps are mostly excluded by the daily coverage rule anyway.

## Implementation

- Class `HeatHoursIndex` (method `band_hours(ctx, selection)` returns all bands per day),
  parameters `HeatHoursParams` in `src/sivin/analytics/ripening/heat_hours.py`.
- Durations: `SampleDurations` in `src/sivin/analytics/ripening/durations.py`.
- `IndexResult.daily`: heat-stress hours per day. `details`: `optimum_h`, `heat_stress_h`,
  `extreme_heat_h`, `observed_h`, `n_days`.
- Tests: `tests/analytics/ripening/test_hour_indices.py::TestHeatHours`,
  `tests/analytics/ripening/test_durations.py`.

## References

- Amerine, M. A., Winkler, A. J. (1944). Composition and quality of musts and wines of
  California grapes. *Hilgardia*, 15(6), 493–675. https://doi.org/10.3733/hilg.v15n06p493
- Greer, D. H., Weedon, M. M. (2012). Modelling photosynthetic responses to temperature of
  grapevine (*Vitis vinifera* cv. Semillon) leaves on vines grown in a hot climate. *Plant,
  Cell & Environment*, 35(6), 1050–1064. https://doi.org/10.1111/j.1365-3040.2011.02471.x
- Mori, K., Goto-Yamamoto, N., Kitayama, M., Hashizume, K. (2007). Loss of anthocyanins in
  red-wine grape under high temperature. *Journal of Experimental Botany*, 58(8), 1935–1945.
  https://doi.org/10.1093/jxb/erm055
