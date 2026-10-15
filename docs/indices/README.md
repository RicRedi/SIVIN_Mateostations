# Climate indices: overview

What the viticultural indices of `sivin` measure and what a grower can read from them. Each
index has its own page with the formula, period, parameters, interpretation, limitations and
literature. The literature check is in [../literature-verification.md](../literature-verification.md).

The indices are computed from the quality-checked temperature and humidity of each sensor with
`sivin indices --season YEAR` (part of the daily `sivin run`) and written to
`data/derived/indices/<season>.json`. They are not shown on the web portal yet (WP-3.4).

Days are local calendar days (Europe/Prague). An index uses only days with enough valid
measurements. Missing days are not filled, so sums over a season with gaps come out too low, and
a result says how complete its period was (`coverage`, `complete`).

## Heat of the season

How warm the growing season is, and so which varieties and wine styles a site suits. Comparing
sensors shows the warmer and cooler parts of a vineyard.

| Index | What it measures | Period |
|---|---|---|
| [Growing degree-days / Winkler](gdd_winkler.md) | Sum of daily mean temperatures above 10 °C (°C·d); classifies the site into Winkler regions I–V. The cumulative curve shows whether the season is ahead or behind. | Apr 1 – Oct 31 |
| [Huglin index](huglin.md) | Heat sum that weights the warm part of the day and corrects for day length at our latitude (K = 1.06); classes of Tonietto & Carbonneau (2004) say which varieties can ripen. | Apr 1 – Sep 30 |
| [Biologically effective degree-days (BEDD)](bedd.md) | Degree-days capped at a daily mean of about 19 °C and adjusted for the diurnal range (Gladstones, 1992): heat that is still useful for development. | Apr 1 – Oct 31 |
| [Growing season temperature (GST)](gst.md) | Mean temperature of the season; Jones (2006) maps it to cool / intermediate / warm / hot climate-maturity groups of varieties. | Apr 1 – Oct 31 |

## Phenology

Estimated dates of development stages from accumulated heat. **All three are orientational**
until calibrated against local BBCH observations of our vineyards.

| Index | What it estimates |
|---|---|
| [Budburst](budburst.md) | Date of budburst: start of the season and of the frost-sensitive period. Simplest forcing-only model with configurable parameters, no critical sum taken from literature. |
| [GFV (Grapevine Flowering Véraison)](gfv.md) | Dates of flowering and véraison (Parker et al., 2011, 2013), per cultivar where a critical sum is known. |
| [GSR (Grapevine Sugar Ripeness)](gsr.md) | Date when berry sugar reaches a target concentration, e.g. 200 g/L (Parker et al., 2020), per cultivar and target. |

## Ripening conditions

The weather in the weeks before harvest, which affects acidity, colour and aroma.

| Index | What it measures | Period |
|---|---|---|
| [Cool Night Index](cool_night.md) | Mean minimum temperature in September. Cool nights favour colour and aroma, warm nights faster loss of acidity (Tonietto & Carbonneau, 2004). | September |
| [Diurnal range during ripening](dtr_ripening.md) | Mean day–night temperature difference while berries ripen; descriptive, without literature classes. | Aug 1 – Sep 30 |
| [Hours in temperature bands](heat_hours.md) | Hours in a range favourable for photosynthesis and ripening, and hours of heat stress. Thresholds are project defaults, not literature values. | Apr 1 – Oct 31 |

## Frost, cold and heat extremes

| Index | What it measures | Period |
|---|---|---|
| [Frost hours and frost nights](frost.md) | Time at or below frost thresholds, number of frost nights and absolute minimum; optionally only after (modelled) budburst, when frost damages shoots. | Apr 1 – Oct 31 |
| [Winter freeze](winter_freeze.md) | Days with minima below thresholds that damage dormant buds, canes and trunks. | dormant season |
| [Tropical days and nights, characteristic days](tropical_days_nights.md) | Counts used in Czech climatology (ČHMÚ): tropical days and nights, summer days, frost and ice days. | calendar year |

## Humidity and disease risk

Air humidity drives leaf wetness and fungal diseases. Our sensors do not measure leaf wetness, so
it is estimated from relative humidity (RH ≥ 90 % by default), and the disease indices are risk
indicators, not forecasts of infection. Precipitation is collected since WP-1.9 but not used by
the disease indices yet (WP-2.5).

| Index | What it measures |
|---|---|
| [Dew point](dew_point.md) | Temperature at which the air becomes saturated; a small difference to the air temperature means dew and wet leaves are likely. |
| [Vapour pressure deficit (VPD)](vpd.md) | Drying power of the air: high VPD means water stress, low VPD long leaf wetness. |
| [Grey mould (Botrytis), Broome model](botrytis_broome.md) | Expected share of infected berries from the duration of (estimated) wetness and its mean temperature (Broome et al., 1995). |
| [Powdery mildew, Gubler-Thomas index](powdery_mildew_gt.md) | Daily risk score 0–100 from hours of moderate temperature; growers use it to adjust spray intervals. Needs temperature only. |
| [Downy mildew](downy_mildew.md) | **Not implemented**: the page explains why and what would be needed (rain, leaf wetness, phenology observations). Planned with precipitation in WP-2.5. |

## Adding an index

Each index is a class registered in `sivin.analytics` and needs its own page here with the
sections of the existing pages (Purpose, Definition, Period and aggregation, Parameters,
Interpretation, Assumptions and limitations, Implementation, References). Add it to this
overview as well.
