# Huglin heliothermal index (`huglin`)

## Purpose

Heat available for grapevine development and ripening, giving more weight to the warm part of
the day (daily maximum) and correcting for the longer days at higher latitudes. The index is the
heliothermal criterion of the multicriteria climatic classification of Tonietto & Carbonneau
(2004) and indicates which varieties can reach ripeness at a site.

## Definition

$$
\mathrm{HI} = \sum_{d \in P} K \cdot \max\left(0,\; \frac{(T_{mean,d} - 10) + (T_{max,d} - 10)}{2}\right)
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $P$ | complete local days of April 1 – September 30 | — |
| $T_{mean,d}$ | daily mean temperature (see `daily_mean`) | °C |
| $T_{max,d}$ | daily maximum temperature | °C |
| 10 | base temperature | °C |
| $K$ | day-length coefficient depending on latitude | — |
| HI | Huglin index | °C·d |

The clip at 0 is applied per day before multiplying by $K$ (same as the legacy code).

**Daily mean.** Huglin (1978) and Tonietto & Carbonneau (2004) use the daily mean air
temperature of climatological stations; whether it is meant as $(T_{max}+T_{min})/2$ or as a
mean of more readings is not stated in a source I can verify [to be verified]. The default here
is `minmax` (as for GDD); the legacy `vineyard_analyst.calculate_huglin_index` used the mean of
all samples (`sample_mean`).

## Period and aggregation

- Period: April 1 – September 30 (Huglin, 1978; northern hemisphere), local calendar days.
- Only complete days (`coverage >= analytics.min_daily_coverage`) contribute.
- `coverage` = complete days / 183; `complete` = `coverage >= analytics.min_season_coverage`.
- **Missing days bias the sum low.** An incomplete day contributes nothing (no gap filling),
  so the sum over the available days underestimates the true seasonal sum.
  `details["n_missing_days"]` = days of the period that are not complete. `complete` follows
  the plan's coverage rule (`coverage >= analytics.min_season_coverage`) and therefore does
  **not** mean unbiased: up to 10 % of the days may be missing in a complete season.
- The class is assigned only when the season is complete and
  `n_missing_days <= max_missing_days` (default 0).
- No complete day → `value = None` (`status`). No K (see below) → `value = None` (`status`).

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `base_temp_c` | 10.0 | °C | Huglin (1978) |
| `daily_mean` | `minmax` | — | project default, see above [to be verified] |
| `period` | April 1 – September 30 | local month-day | Huglin (1978) |
| `k_bands` | table below | °N, — | Tonietto & Carbonneau (2004) [to be verified] |
| `k_override` | none | — | fixed K instead of the lookup; legacy used 1.05 |
| `classes` | table below | °C·d | Tonietto & Carbonneau (2004) |
| `max_missing_days` | 0 | d | project default, to be tuned on real data |

Latitude bands, upper-inclusive as the table is commonly tabulated (40°01'–42° → 1.02, …,
48°01'–50° → 1.06) [to be verified]:

| Latitude | K |
|---|---|
| > 40° – 42° N | 1.02 |
| > 42° – 44° N | 1.03 |
| > 44° – 46° N | 1.04 |
| > 46° – 48° N | 1.05 |
| > 48° – 50° N | 1.06 |

Tonietto & Carbonneau (2004) give K from 1.02 to 1.06 between 40° and 50° latitude; the 2°
bands follow that range but the exact band edges are **[to be verified]** against the papers.
At or below 40° N, above 50° N and for a missing latitude no K is defined: the result is
`None` unless `k_override` is set. Some authors interpolate K linearly between 1.02 (40°) and
1.06 (50°), which gives K ≈ 1.056 at 48.88° N; interpolation is not implemented (out of
scope; set `k_override` to use such a value).

**Differences from the legacy script.** Two defaults differ from
`vineyard_analyst.calculate_huglin_index`, and both change the value on the same data:

1. **K.** The sensors are at about 48.88° N, so the lookup gives **K = 1.06**; legacy used a
   fixed **1.05** (the 46–48° value). This alone raises the index by 1.06 / 1.05 − 1 ≈ 0.95 %.
2. **Daily mean.** The default here is `minmax` = $(T_{max}+T_{min})/2$; legacy used the mean of
   all samples (`sample_mean`). The two differ every day depending on the shape of the diurnal
   curve, so the seasonal index can move by tens of °C·d in either direction.

Set `k_override: 1.05` and `daily_mean: sample_mean` to reproduce legacy numbers (on complete
in-season days; see the parity test).

## Interpretation

Classes of Tonietto & Carbonneau (2004); bounds are inclusive upper bounds (a value equal to a
bound belongs to the lower class):

| Class | Label | HI (°C·d) |
|---|---|---|
| HI-3 very cool | `very_cool` | ≤ 1500 |
| HI-2 cool | `cool` | 1500 < HI ≤ 1800 |
| HI-1 temperate | `temperate` | 1800 < HI ≤ 2100 |
| HI+1 warm temperate | `temperate_warm` | 2100 < HI ≤ 2400 |
| HI+2 warm | `warm` | 2400 < HI ≤ 3000 |
| HI+3 very warm | `very_warm` | > 3000 |

The label `temperate_warm` follows the example of the site data contract
(MIGRATION_PLAN §2.6); the English class name in the paper is "warm temperate"
[to be verified].

## Assumptions and limitations

- Only temperature is used; ~1825 s sampling slightly underestimates $T_{max}$.
- In-canopy sensors measure vineyard microclimate, not the screen temperature of the stations
  the classes were derived from.
- Incomplete days are skipped, which lowers the sum; check `n_missing_days`.
- Legacy difference: legacy selected months 4–9 of all data and summed every day regardless of
  completeness, with K = 1.05 and the sample mean. With `daily_mean: sample_mean`,
  `k_override: 1.05` and complete days both give the same value (parity test).

## Implementation

- Class `HuglinIndex` with `HuglinParams` and `LatitudeBand` in
  `src/sivin/analytics/thermal/huglin.py`; daily formula `huglin_daily` in `formulas.py`.
- K is looked up from `IndexContext.latitude_deg` (`HuglinParams.coefficient`); the value of K
  used is reported in `details["k"]`.
- Tests: `tests/analytics/thermal/test_gdd_huglin.py` (hand example, K lookup, missing K,
  classes, empty season, legacy parity), `test_formulas.py`.

## References

- Huglin, P. (1978). Nouveau mode d'évaluation des possibilités héliothermiques d'un milieu
  viticole. *Comptes Rendus de l'Académie d'Agriculture de France*, 64, 1117–1126.
- Tonietto, J., Carbonneau, A. (2004). A multicriteria climatic classification system for
  grape-growing regions worldwide. *Agricultural and Forest Meteorology*, 124, 81–97.
  [DOI not verified]
