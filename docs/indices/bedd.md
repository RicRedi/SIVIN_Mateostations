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

This is the form in which the index is quoted from Gladstones (1992) by secondary sources. In
WP-L.1 the cap of 9 °C·d (19 °C mean), the DTR band 10–13 °C, the factor 0.25 and the order
"adjust, then cap" were checked against the BEDD implementation and documentation of xclim 0.62
(`biologically_effective_degree_days`, citing Gladstones 1992 and Hall & Jones 2010):
$\min\left(k \cdot \max(0, T_{mean} - 10) + A, 9
ight)$. The book itself was not read
(see [literature verification](../literature-verification.md)).

**Order of cap and adjustments** (`cap_order`). The default matches the secondary source; the
alternative was not found in any source checked in WP-L.1 [to be verified]:

- `after_adjustment` (default, the formula above): the adjusted contribution is capped at $c$
  (as in xclim 0.62).
- `before_adjustment`: the mean excess is capped first (mean capped at 19 °C, as Gladstones'
  monthly formulation is reported), then adjusted; the daily contribution can exceed $c$:

$$
\mathrm{BEDD}_d = \max\left(0,\; k \cdot \min\left(c, \max(0, T_{mean,d} - T_{base})\right) + A_d\right)
$$

The final floor at 0 is a project choice so that a cold day with a small DTR cannot subtract
heat; xclim 0.62 has no such floor, so on such days the two differ (the project value is
higher). Consequence of the formula as written: a day with
$T_{mean} \le 10$ °C but $\mathrm{DTR} > 13$ °C gets a small positive contribution.

## Period and aggregation

- April 1 – October 31, local calendar days; only complete days are summed.
- `coverage` = complete days / 214; `complete` = `coverage >= analytics.min_season_coverage`.
- `daily` = cumulative curve. No classes are defined.
- **Missing days bias the sum low.** An incomplete day contributes nothing (no gap filling),
  so the sum over the available days underestimates the true seasonal sum.
  `details["n_missing_days"]` = days of the period that are not complete. `complete` follows
  the plan's coverage rule (`coverage >= analytics.min_season_coverage`) and therefore does
  **not** mean unbiased: up to 10 % of the days may be missing in a complete season.
- No complete day → `value = None` (`status`).

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `base_temp_c` | 10.0 | °C | Gladstones (1992) |
| `cap_c_d` | 9.0 | °C·d | Gladstones (1992), 19 °C upper mean; secondary: xclim 0.62 |
| `dtr_lower_c` | 10.0 | °C | Gladstones (1992); secondary: xclim 0.62 |
| `dtr_upper_c` | 13.0 | °C | Gladstones (1992); secondary: xclim 0.62 |
| `dtr_factor` | 0.25 | °C·d/°C | Gladstones (1992); secondary: xclim 0.62; 0 disables |
| `day_length_coefficient` | 1.0 | — | off; Gladstones gives latitude-dependent values, not shipped [to be verified] |
| `cap_order` | `after_adjustment` | — | default as in xclim 0.62; `before_adjustment` not found in a source [to be verified] |
| `daily_mean` | `minmax` | — | project default |
| `period` | April 1 – October 31 | local month-day | northern-hemisphere growing season |

## Interpretation

No class boundaries are shipped: Gladstones (1992) relates BEDD sums to variety maturity
groups, but I cannot quote the numbers with certainty. Use BEDD to compare sensors and seasons.

## Assumptions and limitations

- Only temperature is used; ~1830 s sampling slightly underestimates DTR (extremes between
  samples are missed), which lowers the positive adjustment.
- In-canopy sensors: DTR in the canopy differs from screen DTR.
- The day-length adjustment is off by default because its coefficients are not verified.

## Implementation

- Class `BeddIndex` with `BeddParams` in `src/sivin/analytics/thermal/bedd.py`; daily formulas
  `bedd_daily`, `bedd_daily_cap_before_adjustment` and `dtr_adjustment` in `formulas.py`.
- Tests: `tests/analytics/thermal/test_gst_bedd.py` (hand example with cap, both DTR
  adjustments and floor), `test_formulas.py`.

## References

- Gladstones, J. (1992). *Viticulture and Environment.* Winetitles, Adelaide. ISBN 1-875130-12-3.
- Hall, A., Jones, G. V. (2010). Spatial analysis of climate in winegrape-growing regions in
  Australia. *Australian Journal of Grape and Wine Research*, 16(3), 389–404.
  https://doi.org/10.1111/j.1755-0238.2010.00100.x
- Jones, G. V., Duff, A. A., Hall, A., Myers, J. W. (2010). Spatial analysis of climate in
  winegrape growing regions in the western United States. *American Journal of Enology and
  Viticulture*, 61(3), 313–326. https://doi.org/10.5344/ajev.2010.61.3.313
- Secondary source for the constants: xclim 0.62.0,
  `xclim.indices.biologically_effective_degree_days` (Ouranos, PyPI package source).
