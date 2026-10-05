# Biologically effective degree-days (`bedd`)

## Purpose

A refinement of growing degree-days by Gladstones (1992): temperatures above a daily mean of
about 19 °C are assumed to add no further development, and the daily contribution is adjusted
for the diurnal temperature range (and optionally for day length). It describes the heat useful
for vine development better than plain GDD in warm or continental climates.

## Definition

$$
\mathrm{BEDD} = \sum_{d \in P} \min\left(c,\; \max\left(0,\;
k \cdot \max(0, T_{mean,d} - T_{base}) + A_d \right)\right)
$$

$$
A_d = f \cdot \Big(\max(0, \mathrm{DTR}_d - u) - \max(0, l - \mathrm{DTR}_d)\Big),
\qquad \mathrm{DTR}_d = T_{max,d} - T_{min,d}
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $P$ | complete local days of April 1 – October 31 | — |
| $T_{mean,d}$ | daily mean, by default $(T_{max}+T_{min})/2$ | °C |
| $T_{base}$ | base temperature, 10 °C | °C |
| $c$ | cap of the daily contribution, 9 °C·d (= 19 °C − 10 °C) | °C·d |
| $k$ | day-length coefficient (1 = off) | — |
| $\mathrm{DTR}_d$ | diurnal temperature range | °C |
| $l$, $u$ | band of DTR without adjustment, 10 and 13 °C | °C |
| $f$ | adjustment factor, 0.25 | °C·d/°C |
| $A_d$ | DTR adjustment: $f(\mathrm{DTR}-u)$ above $u$, $f(\mathrm{DTR}-l)$ (negative) below $l$ | °C·d |
| BEDD | biologically effective degree-days | °C·d |

This is the form in which the index is commonly quoted from Gladstones (1992) (for example by
Jones et al., 2010) **[to be verified]**: the cap, the DTR band 10–13 °C, the factor 0.25 and
the order of operations (adjustment added before the cap) are not checked against the book.
The final floor at 0 is an implementation choice so that a cold day with a small DTR cannot
subtract heat [to be verified]. Consequence of the formula as written: a day with
$T_{mean} \le 10$ °C but $\mathrm{DTR} > 13$ °C gets a small positive contribution.

## Period and aggregation

- April 1 – October 31, local calendar days; only complete days are summed.
- `coverage` = complete days / 214; `complete` = `coverage >= analytics.min_season_coverage`.
- `daily` = cumulative curve. No classes are defined.
- No complete day → `value = None` (`status`).

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `base_temp_c` | 10.0 | °C | Gladstones (1992) |
| `cap_c_d` | 9.0 | °C·d | Gladstones (1992), 19 °C upper mean [to be verified] |
| `dtr_lower_c` | 10.0 | °C | Gladstones (1992) [to be verified] |
| `dtr_upper_c` | 13.0 | °C | Gladstones (1992) [to be verified] |
| `dtr_factor` | 0.25 | °C·d/°C | Gladstones (1992) [to be verified]; 0 disables |
| `day_length_coefficient` | 1.0 | — | off; Gladstones gives latitude-dependent values, not shipped [to be verified] |
| `daily_mean` | `minmax` | — | project default |
| `period` | April 1 – October 31 | local month-day | northern-hemisphere growing season |

## Interpretation

No class boundaries are shipped: Gladstones (1992) relates BEDD sums to variety maturity
groups, but I cannot quote the numbers with certainty. Use BEDD to compare sensors and seasons.

## Assumptions and limitations

- Only temperature is used; ~1825 s sampling slightly underestimates DTR (extremes between
  samples are missed), which lowers the positive adjustment.
- In-canopy sensors: DTR in the canopy differs from screen DTR.
- The day-length adjustment is off by default because its coefficients are not verified.

## Implementation

- Class `BeddIndex` with `BeddParams` in `src/sivin/analytics/thermal/bedd.py`; daily formula
  `bedd_daily` and `dtr_adjustment` in `formulas.py`.
- Tests: `tests/analytics/thermal/test_gst_bedd.py` (hand example with cap, both DTR
  adjustments and floor), `test_formulas.py`.

## References

- Gladstones, J. (1992). *Viticulture and Environment.* Winetitles, Adelaide.
- Jones, G. V., Duff, A. A., Hall, A., Myers, J. W. (2010). Spatial analysis of climate in
  winegrape growing regions in the western United States. *American Journal of Enology and
  Viticulture*, 61(3), 313–326. [DOI not verified]
