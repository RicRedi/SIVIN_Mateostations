# Growing season average temperature (`gst`)

## Purpose

A single number for the thermal regime of the growing season. Jones (2006) relates it to the
climate-maturity groups of grape varieties: which varieties ripen in a cool, intermediate, warm
or hot climate.

## Definition

$$
\mathrm{GST} = \frac{1}{|P|} \sum_{d \in P} T_{mean,d}
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $P$ | complete local days of April 1 – October 31 | — |
| $\lvert P\rvert$ | number of those days | d |
| $T_{mean,d}$ | daily mean temperature, by default $(T_{max}+T_{min})/2$ | °C |
| GST | growing season temperature | °C |

Jones (2006) and Jones et al. (2010) compute GST from monthly means of daily
$(T_{max}+T_{min})/2$ station data; averaging the daily values directly gives **nearly** the
same mean when all days are present (a mean of seven monthly means weights 30- and 31-day
months equally per month, so it differs from the mean of all days by hundredths of a °C). `IndexResult.daily` holds the daily means used.

## Period and aggregation

- April 1 – October 31 (northern hemisphere), local calendar days.
- Only complete days (`coverage >= analytics.min_daily_coverage`) are averaged.
- `coverage` = complete days / 214; `complete` = `coverage >= analytics.min_season_coverage`.
- Class only for a complete season (a spring-only mean is not comparable).
- No complete day → `value = None` (`status`).

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `daily_mean` | `minmax` | — | as in Jones (2006) station data |
| `period` | April 1 – October 31 | local month-day | Jones (2006) |
| `classes` | table below | °C | Jones (2006); bounds verified against secondary sources |

## Interpretation

This index uses the **6-class scheme of Jones (2006)** (bounds inclusive upper; a value equal
to a bound belongs to the lower group):

| Label | GST (°C) |
|---|---|
| `too_cool` | ≤ 13 |
| `cool` | 13 < GST ≤ 15 |
| `intermediate` | 15 < GST ≤ 17 |
| `warm` | 17 < GST ≤ 19 |
| `hot` | 19 < GST ≤ 24 |
| `too_hot` | > 24 |

The ranges too cool < 13, cool 13–15, intermediate 15–17, warm 17–19, hot 19–24 and too hot
> 24 °C were found in WP-L.1 in secondary sources quoting Jones (2006) / Jones et al. (2010)
(see [literature verification](../literature-verification.md)); the original figure and table
were not read. Which side of a bound is inclusive is not stated in those sources; the
upper-inclusive rule is a project convention.

Secondary sources disagree on whether Jones et al. (2010) or Hall & Jones (2010) split the hot
range into hot (19–21 °C) and very hot (21–24 °C). The split is not shipped; it can be
configured through `classes`.

## Assumptions and limitations

- In-canopy sensors, ~1830 s sampling; $(T_{max}+T_{min})/2$ from samples is close to but not
  identical with screen-station values.
- Missing days in a part of the season bias the mean towards the other part (e.g. missing July
  days lower GST); check `coverage` and `details["n_missing_days"]` (incomplete days of the
  period). Unlike the sums, the mean is not biased low by the mere number of missing days.

## Implementation

- Class `GstIndex` with `GstParams` in `src/sivin/analytics/thermal/gst.py`.
- Tests: `tests/analytics/thermal/test_gst_bedd.py` (hand example, both daily means, every
  class, empty season).

## References

- Jones, G. V. (2006). Climate and terroir: impacts of climate variability and change on wine.
  In: Macqueen, R. W., Meinert, L. D. (eds.), *Fine Wine and Terroir — The Geoscience
  Perspective*, Geoscience Canada Reprint Series 9, Geological Association of Canada,
  St. John's, 203–216. (No DOI.)
- Jones, G. V., Duff, A. A., Hall, A., Myers, J. W. (2010). Spatial analysis of climate in
  winegrape growing regions in the western United States. *American Journal of Enology and
  Viticulture*, 61(3), 313–326. https://doi.org/10.5344/ajev.2010.61.3.313
