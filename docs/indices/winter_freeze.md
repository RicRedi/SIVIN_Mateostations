# Winter freeze (`winter_freeze`)

## Purpose

Very low winter temperatures damage dormant buds, canes and trunks of *Vitis vinifera*.
Winter-injury background: Zabadal et al. (2007). The index counts days whose minimum fell below
damaging thresholds in the dormant season.

## Definition

$$N_{damage} = \sum_{d \in D} \mathbf{1}[T_{min,d} < T_{damage}], \qquad
N_{severe} = \sum_{d \in D} \mathbf{1}[T_{min,d} < T_{severe}], \qquad
T_{abs} = \min_{d \in D} T_{min,d}$$

| Symbol | Meaning | Unit |
|---|---|---|
| $D$ | complete local days of the dormant season | — |
| $T_{min,d}$ | minimum air temperature of local day $d$ | °C |
| $T_{damage}$, $T_{severe}$ | `damage_threshold_c`, `severe_threshold_c` | °C |
| $N_{damage}$ | damage days (the index value) | d |
| $N_{severe}$ | severe days | d |
| $T_{abs}$ | absolute minimum | °C |

## Period and aggregation

- The dormant season crosses New Year, which `Season` does not support. The index therefore
  uses **the winter ending in the season year**: season 2026 = 2025-11-01 … 2026-03-31. It is
  composed of two `Season`s (`dormant_start`..Dec 31 of the previous year and Jan 1..`dormant_end`
  of the season year), each selected with the base-class helper; coverage is the number of
  complete days over the total number of days of both parts (151 or 152 days by default).
- Only complete days count; `complete` follows `analytics.min_season_coverage`. Without any
  complete day the value is `None`.
- The autumn part lies in the previous calendar year, so `IndexContext.daily` must contain it.
  If the autumn part has no complete day, the value is `None` and
  `details["status"] = "previous_autumn_missing"`: a count over half a winter would look like a
  mild winter.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `dormant_start` | `11-01` (previous year) | MM-DD | project default `[to be tuned]` |
| `dormant_end` | `03-31` (season year) | MM-DD | project default `[to be tuned]` |
| `damage_threshold_c` | −15.0 (strict `<`) | °C | project default (MIGRATION_PLAN §3.2), not a literature value |
| `severe_threshold_c` | −20.0 (strict `<`) | °C | project default (MIGRATION_PLAN §3.2), not a literature value |

## Interpretation

Days below the thresholds indicate a risk of bud and wood injury. Cold hardiness depends on
variety, acclimation and the course of the winter; the thresholds are plan defaults, not
values taken from Zabadal et al. (2007), whose bulletin (105 pages) could not be read in
WP-L.1.

## Assumptions and limitations

- The daily minimum from samples about every 30 min slightly overestimates the true minimum.
- Air temperature at sensor height; cold-air pooling near the ground may be stronger.
- Acclimation and deacclimation (e.g. a warm spell before a frost) are not modelled.

## Implementation

- Class `WinterFreezeIndex`, parameters `WinterFreezeParams` (properties `autumn`, `spring`) in
  `src/sivin/analytics/ripening/winter_freeze.py`.
- `IndexResult.daily`: daily minima of the winter. `details`: `severe_days`, `min_temp_c`, `n_days`;
  only `status` and `n_days` when the previous autumn is missing.
- Tests: `tests/analytics/ripening/test_daily_indices.py::TestWinterFreeze`.

## References

- Zabadal, T. J., Dami, I. E., Goffinet, M. C., Martinson, T. E., Chien, M. L. (2007). *Winter
  injury to grapevines and methods of protection.* Michigan State University Extension
  Bulletin E2930. (Authors verified in WP-L.1; no DOI.)
