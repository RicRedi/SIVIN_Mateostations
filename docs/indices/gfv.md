# Grapevine Flowering Véraison model (`gfv`)

## Purpose

Predicts the dates of flowering and véraison from accumulated heat. Parker et al. (2011) fitted
a general Spring Warming model for *Vitis vinifera* on a large phenology dataset; Parker et al.
(2013) give cultivar-specific critical sums. **The predictions are orientational** until they
are calibrated against local BBCH observations of our vineyards.

## Definition

$$
S(d) = \sum_{d' = t_0}^{d} \max\left(0,\; T_{mean,d'} - T_{base}\right),
\qquad \hat d_s = \min\{\, d : S(d) \ge F^*_s \,\}
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $t_0$ | start of accumulation: March 1 (day of year 60 in common years) | local date |
| $T_{mean,d}$ | daily mean, by default $(T_{max}+T_{min})/2$ | °C |
| $T_{base}$ | base temperature, 0 °C | °C |
| $S(d)$ | thermal sum after day $d$ | °C·d |
| $F^*_s$ | critical sum of stage $s$ (flowering, véraison) | °C·d |
| $\hat d_s$ | predicted date of stage $s$: first local date with $S \ge F^*_s$ | local date |

With $T_{base} = 0$ °C, $\max(0, T_{mean})$ is used, i.e. days with a negative mean add
nothing (they do not subtract).

## Period and aggregation

- Accumulation from March 1 to October 31 (the end is a project default: a stage not reached by
  then is "not reached"). Parker et al. (2011) define the start as day of year 60; here it is
  defined as **March 1 in every year** (in leap years DOY 60 would be February 29).
- Only complete days (`coverage >= analytics.min_daily_coverage`) are accumulated; an incomplete
  day is skipped, which **delays** the predicted date.
- **Not configured by default:** without both critical sums the result is `value = None` with
  `details["status"] = "not configured"` (see Parameters).
- `value` = day of year of **véraison** (local date in `details["date"]`); `None` if not
  reached.
- `details`: `flowering_date`, `flowering_doy`, `veraison_date`, `veraison_doy` (ISO dates or
  `"not reached"`), the critical sums and `thermal_sum_c_d` (sum over the whole available
  period); `status` when véraison is not reached.
- **Missing days delay the date.** An incomplete day contributes nothing (no gap filling), so
  the sum lags behind and the predicted date is late. `details["n_missing_days"]` = incomplete
  days from the period start to the predicted stage (or to the period end); `complete` follows
  the plan's coverage rule and does not mean unbiased.
- **Accumulation start not covered.** If more than `max_missing_days_at_start` (default 0)
  days are missing before the first complete day of the period (e.g. a sensor deployed after
  the start), the result is `value = None` with `details["status"] = "accumulation start not
  covered"` and `details["n_missing_days_at_start"]`.
- **DOY and leap years.** `value` is the day of year of the local date, which is also given as
  `details["date"]` (ISO). In leap years every date after February has a DOY one higher than
  in common years, so compare dates, not DOY values, across years.
- `coverage`/`complete` refer to the days from March 1 to véraison, or to the whole period if
  véraison is not reached (so a running season is incomplete until véraison).
- `daily` = cumulative thermal sum.

## Parameters

| Config name | Default | Unit | Source |
|---|---|---|---|
| `base_temp_c` | 0.0 | °C | Parker et al. (2011); verified (WP-L.1) |
| `period` | March 1 – October 31 | local month-day | start: day of year 60, Parker et al. (2011), verified (WP-L.1); end: project default |
| `flowering_f_star_c_d` | none | °C·d | to be supplied (general model: Parker et al., 2011; cultivars: Parker et al., 2013) |
| `veraison_f_star_c_d` | none | °C·d | to be supplied, as above |
| `max_missing_days_at_start` | 0 | d | project default, to be tuned |
| `daily_mean` | `minmax` | — | project default |

Both critical sums must be set together and increase (flowering < véraison).

**Critical sums: result of the literature verification (WP-L.1).** No critical sums are shipped
and the model stays **off until configured** (owner decision).

- **Correction.** 1282 °C·d (flowering) and 2528 °C·d (véraison) were listed here before as
  values recalled for the *general* GFV model. They are the **Sauvignon blanc** values of
  Parker et al. (2013), as quoted by Sturman et al. (OENO One, "The application of
  high-resolution atmospheric modelling to weather and climate variability in vineyard
  regions") and by Ausseil et al. (2021). They are not a species-level value.
- The species-level (general) F* of Parker et al. (2011) **could not be found** in any source
  available to WP-L.1; it stays **[to be verified]**.
- Base temperature 0 °C and the start on day of year 60 (March 1) are verified.

Cultivar values that could be confirmed (secondary sources, primary table not read):

| Cultivar | Flowering F* (°C·d) | Véraison F* (°C·d) | Source |
|---|---|---|---|
| Sauvignon blanc | 1282 | 2528 | Parker et al. (2013), quoted by Sturman et al. and Ausseil et al. (2021) |

Values for the other cultivars common in South Moravia (Grüner Veltliner, Riesling, Pinot
blanc, Chardonnay, Müller-Thurgau, Welschriesling, Pinot noir, Blaufränkisch, Saint Laurent,
Zweigelt) are in Parker et al. (2013) for the cultivars it covers, but no value could be
confirmed by two consistent sources (for Pinot noir the sources found give different véraison
values); none is listed. See [literature verification](../literature-verification.md).

**How to enable the model.** Set both critical sums for the cultivar of the sensor, e.g. for
Sauvignon blanc:

```yaml
gfv:
  flowering_f_star_c_d: 1282.0
  veraison_f_star_c_d: 2528.0
```

Set them per sensor once the cultivar is known (MIGRATION_PLAN §0.6, Q4); the wiring into the
configuration is done by the integration WP-1.7.

## Interpretation

No classes. Compare predicted dates between sensors and seasons; a difference of a few days
between sensors is meaningful only if both have complete data.

## Assumptions and limitations

- The general model ignores cultivar differences (up to weeks between early and late varieties).
- Not calibrated locally; Parker et al. (2011) fitted it on station temperatures, ours are
  in-canopy.
- Skipped incomplete days delay the prediction; a sensor deployed after March 1 cannot predict
  until a full season of data exists.

## Implementation

- Class `GfvIndex` with `GfvParams` in `src/sivin/analytics/thermal/phenology.py`, a subclass
  of `ThermalTimePhenologyIndex`; accumulation by `ThermalTimeModel` (`thermal_time.py`).
- Tests: `tests/analytics/thermal/test_phenology.py` (not configured by default, both stages
  reached, véraison not reached, running season, empty season, leap year, late deployment,
  parameter validation).

## References

- Parker, A. K., García de Cortázar-Atauri, I., van Leeuwen, C., Chuine, I. (2011). General
  phenological model to characterise the timing of flowering and veraison of *Vitis vinifera*
  L. *Australian Journal of Grape and Wine Research*, 17(2), 206–216.
  https://doi.org/10.1111/j.1755-0238.2011.00140.x
- Parker, A., García de Cortázar-Atauri, I., Chuine, I., Barbeau, G., Bois, B., Boursiquot,
  J.-M., et al. (2013). Classification of varieties for their timing of flowering and veraison
  using a modelling approach: a case study for the grapevine species *Vitis vinifera* L.
  *Agricultural and Forest Meteorology*, 180, 249–264.
  https://doi.org/10.1016/j.agrformet.2013.06.005
- Ausseil, A.-G. E., Law, R. M., Parker, A. K., Teixeira, E. I., Sood, A. (2021). Projected wine
  grape cultivar shifts due to climate change in New Zealand. *Frontiers in Plant Science*, 12,
  618039. https://doi.org/10.3389/fpls.2021.618039 (secondary source of the Sauvignon blanc
  values)
- Sturman, A., Zawar-Reza, P., Soltanzadeh, I., Katurji, M., Bonnardot, V., Parker, A. K.,
  Trought, M. C. T. The application of high-resolution atmospheric modelling to weather and
  climate variability in vineyard regions. *OENO One* (2017), 51(2), 99–105 (article 1538 on
  oeno-one.eu). https://doi.org/10.20870/oeno-one.2016.0.0.1538 [DOI not verified]
  (bibliographic details from a single search extract; not confirmed) (secondary source of the Sauvignon blanc
  values)
