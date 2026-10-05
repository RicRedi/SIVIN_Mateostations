# Literature and parameter verification

Result of WP-L.1 (October 2026, owner decision of 2026-10-05: "verify the literature"). For every
citation and every parameter value that the index documentation or code presents as coming
from literature, this page records the source used, the value found, the value in the code
before and after, and a status.

## Method and its limits

- **Access.** The sandbox blocked direct page access to every publisher, indexing and DOI host
  that was tried (doi.org, api.crossref.org, api.openalex.org, onlinelibrary.wiley.com,
  sciencedirect.com, oeno-one.eu, ipm.ucanr.edu, univ-brest.fr, Wikipedia, …). The only
  channels were (a) a **web search tool** that returns result titles and URLs plus a short
  machine-written extract of the matching pages, and (b) the **source code and documentation
  of the Python package xclim 0.62.0**, downloaded from PyPI (`docs/references.bib`,
  `xclim/indices/_agro.py`, `xclim/indices/helpers.py`, `xclim/indices/converters.py`).
- **What counts as verified.**
  - *Bibliographic data and DOIs*: the DOI appears in a publisher URL (e.g.
    `onlinelibrary.wiley.com/doi/<DOI>`, `link.springer.com/article/<DOI>`), in the xclim
    bibliography, or in reference lists that the search tool found when searching for the
    **DOI string alone** (so the DOI was not supplied by the query). URLs are listed below.
  - *Values*: the value appears in the extract of a page that quotes the primary source, in
    the primary paper's abstract, or in xclim code that cites the source, and no source found
    disagrees. Values seen only once, or with disagreeing sources, are **not** accepted.
- **Status values.**
  - `verified` — bibliographic data or value confirmed as above;
  - `verified (secondary)` — value confirmed in a named secondary source; the primary table or
    text was **not read**;
  - `corrected` — the previous text or value was wrong; old → new is given;
  - `unverifiable` — no reliable source found; the `[to be verified]` marker stays;
  - `project default` — not a literature claim; the text now says so instead of carrying a
    literature marker.
- **Residual risk.** Search extracts are machine-written summaries. Two results during this WP
  were inconsistent (Chardonnay GSR target, Pinot noir véraison F*), which is why single-hit
  values were rejected. A reader with library access should confirm the rows marked
  `verified (secondary)` against the primary tables, in particular the GFV and GSR cultivar
  values, the GST bounds and the BEDD constants.

## Inventory of markers (task 1)

Markers found at the start of the WP (`[to be verified]`, `[DOI not verified]`, `[… to be
verified]`) and what happened to them. Markers that concern local tuning (`[to be tuned]`) or
the sensor data sheet are not literature claims and were left alone.

Counts are occurrences of "to be verified" / "not verified" (any bracket form) in the file at
the start of the WP (commit `11f71ef`) and after it.

| File | Before | After | Remaining (why) |
|---|---|---|---|
| `docs/indices/huglin.md` | 7 | 2 | daily-mean definition of Huglin (1978) not found |
| `docs/indices/gdd_winkler.md` | 1 | 0 | — |
| `docs/indices/gst.md` | 6 | 0 | — |
| `docs/indices/bedd.md` | 11 | 4 | day-length coefficients; `before_adjustment` variant (3 markers, 1 sentence) |
| `docs/indices/budburst.md` | 3 | 2 | 5 °C base not traced to a source |
| `docs/indices/gfv.md` | 2 | 3 | general-model F*; year, volume and DOI of the secondary source Sturman et al. |
| `docs/indices/gsr.md` | 1 | 0 | — |
| `docs/indices/cool_night.md` | 2 | 0 | — |
| `docs/indices/dtr_ripening.md` | 1 | 0 | — |
| `docs/indices/heat_hours.md` | 10 | 0 | — (thresholds now labelled project defaults) |
| `docs/indices/tropical_days_nights.md` | 2 | 0 | normative ČHMÚ document not found (stated in text) |
| `docs/indices/frost.md` | 5 | 0 | — |
| `docs/indices/winter_freeze.md` | 4 | 0 | — |
| `docs/indices/dew_point.md` | 1 | 0 | — |
| `docs/indices/powdery_mildew_gt.md` | 10 | 4 | heat-day decrease limit; heat before onset; restart; wording of class 40–50 |
| `docs/indices/botrytis_broome.md` | 9 | 0 | — |
| `docs/indices/downy_mildew.md` | 4 | 0 | — |
| `docs/quality-control.md` | 9 | 5 | 4 concern the sensor data sheet / station records / sensor resolution (not literature); 1 is "not verified on real data" |
| `src/sivin/analytics/thermal/huglin.py` | 3 | 0 | — |
| `src/sivin/analytics/thermal/gst.py` | 3 | 0 | — |
| `src/sivin/analytics/thermal/bedd.py` | 12 | 2 | day-length coefficient; `before_adjustment` |
| `src/sivin/analytics/thermal/phenology.py` | 2 | 2 | budburst base temperature |
| `src/sivin/analytics/ripening/*.py` | 8 | 0 | — |
| `src/sivin/analytics/disease/*.py` | 7 | 0 | — |

MIGRATION_PLAN §7 (bibliography, outside the scope of this WP) carries three `[ověřit]` markers
(Greer & Weedon 2012, Gubler et al. 1999 authors, Zabadal et al. 2007 authors) and no DOIs. All
three are verified below; updating §7 is left to the owner (hand-off note).

## Heat accumulation and classification

| Claim | Where used | Source | Value in source | Code before → after | Status |
|---|---|---|---|---|---|
| Winkler regions I–V: ≤ 2500, 2501–3000, 3001–3500, 3501–4000, > 4000 °F·d; base 50 °F; April 1 – October 31 | `thermal/gdd.py`, `gdd_winkler.md` | Amerine & Winkler (1944), via secondary sources (search extract over viticulture web pages; primary not read) | as claimed | unchanged (°F·d × 5/9) | verified (secondary) |
| Huglin formula $K\sum\max(0, ((T_{mean}-10)+(T_{max}-10))/2)$, April 1 – September 30 | `thermal/formulas.py`, `huglin.md` | Huglin (1978); xclim 0.62 `huglin_index` (same formula, citing Huglin 1978) | as claimed | unchanged | verified (secondary) |
| Huglin $T_{mean}$ = $(T_{max}+T_{min})/2$ or mean of readings | `huglin.md` | not stated in any source found; xclim uses the daily mean `tas` | — | unchanged | unverifiable |
| K = 1.02 at 40° … 1.06 at 50° | `thermal/huglin.py` | Tonietto & Carbonneau (2004) and Huglin (1978) as quoted in search extracts | 1.02–1.06 | unchanged | verified (secondary) |
| K stepwise bands, upper-inclusive: (40,42] 1.02, (42,44] 1.03, (44,46] 1.04, (46,48] 1.05, (48,50] 1.06 | `thermal/huglin.py` | xclim 0.62 `huglin_day_length_latitude_coefficient`, method "huglin" (citing Huglin 1978) | identical table and edges | unchanged; marker removed | verified (secondary) |
| Huglin classes ≤ 1500, 1500–1800, 1800–2100, 2100–2400, 2400–3000, > 3000 (> lower, ≤ upper) | `thermal/huglin.py` | Tonietto & Carbonneau (2004) as quoted in search extracts (Croatian terroir-congress paper, Embrapa full text listing) | as claimed | unchanged | verified (secondary) |
| Huglin class names | `huglin.md` | same | HI+1 "warm temperate" confirmed; HI+2/HI+3 named inconsistently ("warm"/"very warm" vs "warm to very warm"/"hot") | labels unchanged | partly verified |
| GST classes too cool < 13, cool 13–15, intermediate 15–17, warm 17–19, hot 19–24, too hot > 24 °C | `thermal/gst.py`, `gst.md` | Jones (2006) / Jones et al. (2010) as quoted in a search extract; Jones (2006) quoted as "quality wine production limited to 13–21 °C" | bounds as claimed | unchanged; marker removed | verified (secondary) |
| GST split hot 19–21 / very hot 21–24 °C | `gst.md` | secondary extracts disagree (attributed to Hall & Jones 2009/2010) | conflicting | not shipped (unchanged) | unverifiable |
| Jones (2006) pages 203–216 | `gst.md` | search extract of the paper's listing (climateofwine.com PDF) | 203–216 | `[pages to be verified]` → pages kept | verified |
| BEDD: cap 9 °C·d (19 °C), DTR band 10–13 °C, factor 0.25, "adjust, then cap" | `thermal/bedd.py`, `bedd.md` | xclim 0.62 `biologically_effective_degree_days` (citing Gladstones 1992, Hall & Jones 2010): $\min(k\max(0,T_m-10)+TR_{adj}, 9)$ | as claimed | unchanged; markers replaced by "secondary source" | verified (secondary) |
| BEDD final floor at 0 | `thermal/formulas.py` | not in xclim | — | unchanged; documented as project choice | project default |
| BEDD `before_adjustment` order | `thermal/bedd.py` | not found | — | unchanged | unverifiable |
| BEDD day-length coefficient | `thermal/bedd.py` | xclim gives several variants (Gladstones 2011, Hall & Jones 2010); none matches a single Gladstones (1992) table | — | stays off (1.0) | unverifiable |

## Phenology (GFV, GSR, budburst)

| Claim | Where used | Source | Value in source | Code before → after | Status |
|---|---|---|---|---|---|
| GFV base 0 °C, start day of year 60 (NH) | `thermal/phenology.py`, `gfv.md` | Parker et al. (2011), confirmed by several extracts (Parker et al. 2013; OENO One articles) | 0 °C, DOY 60 | unchanged | verified (secondary) |
| GFV general-model F* 1282 (flowering) / 2528 (véraison) °C·d | `gfv.md` (candidate, not active) | Sturman et al. (OENO One) and Ausseil et al. (2021): these are the **Sauvignon blanc** values | Sauvignon blanc 1282 / 2528 | doc: "general model" → "Sauvignon blanc (Parker et al. 2013)"; code: no default (unchanged) | corrected |
| GFV species-level F* of Parker et al. (2011) | `gfv.md` | not found | — | none shipped | unverifiable |
| GFV cultivar F*, other cultivars | `gfv.md` | single extract gave Chardonnay 1217/2541, Pinot noir 1219/2507, Riesling 1242/2584; a second extract gave Pinot noir véraison 2511 | conflicting | not listed | unverifiable |
| GSR base 0 °C, start day of year 91, targets 170–220 g/L in 10 g/L steps, 65 cultivars | `thermal/phenology.py`, `gsr.md` | Parker et al. (2020), as described in extracts of OENO One (Parker et al. 2020, "Adaptation to climate change by determining grapevine cultivar differences …") | as claimed | unchanged | verified (secondary) |
| GSR Sauvignon blanc, 200 g/L: F* = 2820 °C·d | `GSR_CULTIVAR_PRESETS`, `gsr.md` | Parker et al. (2020), quoted by Ausseil et al. (2021) (two consistent extracts) | 2820 | none → optional preset (not active) | verified (secondary) |
| GSR Chardonnay F* = 2723 °C·d | — | extracts disagree whether the target is 200 or 170 g/L | conflicting | not listed | unverifiable |
| GSR for Grüner Veltliner, Riesling, Pinot blanc, Müller-Thurgau, Welschriesling, Pinot noir, Blaufränkisch, Saint Laurent, Zweigelt | — | not found (whether the paper lists them could not be checked) | — | not listed | unverifiable |
| Budburst base 5 °C from January 1 | `thermal/phenology.py`, `budburst.md` | an extract mentions GDD models with 5 °C and 10 °C bases from January 1, without a traceable source | — | unchanged | unverifiable |

## Ripening, heat and cold

| Claim | Where used | Source | Value in source | Code before → after | Status |
|---|---|---|---|---|---|
| Cool Night Index = mean $T_{min}$ in September (NH) | `ripening/cool_night.py` | Tonietto & Carbonneau (2004); xclim 0.62 `cool_night_index` | as claimed | unchanged | verified (secondary) |
| CI classes ≤ 12, > 12 ≤ 14, > 14 ≤ 18, > 18 °C | `ripening/cool_night.py` | Tonietto & Carbonneau (2004) as quoted in search extracts (with the "> … ≤ …" notation) | as claimed, cooler class inclusive | unchanged; marker removed | verified (secondary) |
| DTR ripening index | `ripening/dtr.py` | descriptive, no literature values | — | unchanged | project default |
| Heat bands 20–30 °C optimum, > 30 °C, > 35 °C | `ripening/heat_hours.py` | not stated as thresholds in the cited papers. Background: light-saturated photosynthesis optimal at 30 °C (Greer & Weedon 2012, abstract); 35 °C maximum halved anthocyanins vs 25 °C (Mori et al. 2007, abstract) | — | values unchanged; labelled project defaults | project default |
| Characteristic days: tropical day $T_{max}\ge30$, tropical night $T_{min}\ge20$, summer day $T_{max}\ge25$, frost day $T_{min}<0$, ice day $T_{max}<0$ °C | `ripening/characteristic_days.py` | ČHMÚ statement on tropical (hot) days (≥ 30.0 °C); Czech Wikipedia "Charakteristický den" | as claimed | unchanged | verified (secondary) |
| Hard frost −2 °C | `ripening/frost.py` | plan default; extracts citing Poling (2008): serious damage after budburst below about −2.2 °C | −2.2 °C (secondary) | unchanged; labelled project default | project default |
| Poling (2008) stage-specific critical temperatures | `frost.md` | table not readable | — | not used | unverifiable |
| Winter freeze −15 / −20 °C | `ripening/winter_freeze.py` | plan default, not in a source read | — | unchanged; labelled project default | project default |
| Magnus coefficients a = 17.625, b = 243.04 °C (c = 6.1094 hPa) | `ripening/psychrometry.py` | Alduchov & Eskridge (1996), AERK form, quoted in extracts; xclim 0.62 `aerk96` = (610.94 Pa, 17.625, −30.12 K) | 17.625, 243.04 °C | unchanged | verified |
| FAO-56 eq. 11: $e^\circ(T) = 0.6108\exp(17.27T/(T+237.3))$ | `ripening/psychrometry.py` | FAO-56 chapter 3, https://www.fao.org/4/x0490e/x0490e07.htm (extract) | as claimed | unchanged | verified |

## Disease models

| Claim | Where used | Source | Value in source | Code before → after | Status |
|---|---|---|---|---|---|
| Gubler-Thomas: 70–85 °F for ≥ 6 continuous hours, 3 consecutive days for onset, +20 / −10 points, bounds 0–100 | `disease/gubler_thomas.py` | UC IPM "Models: Powdery Mildew of Grape" and "Powdery Mildew / Grape" (extracts); APSnet feature (extract) | as claimed | unchanged | verified (secondary) |
| Index at onset = 60 (20 points for each onset day) | `disease/gubler_thomas.py` | UC IPM model description: "for each of these three days, the model assigns 20 points" | 60 | unchanged; marker removed | verified (secondary) |
| Heat: ≥ 95 °F for 15 min, −10 points | `disease/gubler_thomas.py` | UC IPM / Pest Prophet (extracts); one APSnet extract says "above 35 °C" without duration | 95 °F, 15 min | unchanged | verified (secondary) |
| Favourable day with heat nets +10 | `disease/gubler_thomas.py` | Pest Prophet blog (secondary) | +10 | unchanged | verified (secondary) |
| Daily decrease limited to 10 points (non-favourable heat day −10, not −20) | `disease/gubler_thomas.py` | Pest Prophet blog only | max −10 per day | **not applied**; owner question | unverifiable |
| Classes 0–30 low / 40–50 moderate / 60–100 high | `disease/gubler_thomas.py` | UC IPM guideline (extract: "≤ 30 … 40 to 50 … 60 to 100"); Pest Prophet gives 0–20 / 30–50 / 60–100 | UC IPM as claimed | unchanged | verified (secondary) |
| Heat before onset ignored; index never restarts | `disease/gubler_thomas.py` | not found | — | unchanged | unverifiable |
| Broome logit $-2.647866 - 0.374927W + 0.061601WT - 0.001511WT^2$ | `disease/botrytis.py` | UC IPM "Models: Botrytis Bunch Rot of Grape" (extract quoting Broome et al. 1995) | identical | unchanged; markers removed | verified (secondary) |
| Broome fitting range: detached mature berries, 4–20 h wetness, 12–30 °C, $R^2$ = 0.75 | `botrytis_broome.md` | same | as stated | doc: "not verified" → range added | verified (secondary) |
| 3-10 rule (≥ 10 °C, shoots ≥ 10 cm, ≥ 10 mm rain in 24–48 h), Baldacci (1947) | `downy_mildew.md` | Rossi et al. ("Empirical vs. mechanistic models …"), MDPI review (extracts) | as claimed; Baldacci (1947) *Atti Ist. Bot. Lab. Crittogam. Univ. Pavia* 8, 45–85 | doc: "ser. 5" removed (not confirmed) | corrected (citation) |

## Quality control references

| Claim | Where used | Source | Value in source | Code before → after | Status |
|---|---|---|---|---|---|
| Zahumenský (2004), WMO guideline: range, step and persistence tests | `quality-control.md` | ResearchGate / Scribd listings (extracts) | method as claimed; its limits (2 °C step for 6–12 s samples, 0.1 °C persistence over 60 min) are for dense sampling | QC thresholds are project defaults (unchanged) | verified (citation) |
| PELT, CUSUM, BIC, binary segmentation references | `quality-control.md` | see bibliography | — | DOIs added | verified |

## Bibliography (verified)

Each entry lists where its DOI or data were confirmed.

- Alduchov, O. A., Eskridge, R. E. (1996). Improved Magnus form approximation of saturation
  vapor pressure. *Journal of Applied Meteorology*, 35(4), 601–609.
  https://doi.org/10.1175/1520-0450(1996)035<0601:IMFAOS>2.0.CO;2 — xclim `references.bib`;
  ADS bibcode 1996JApMe..35..601A.
- Allen, R. G., Pereira, L. S., Raes, D., Smith, M. (1998). *Crop evapotranspiration —
  Guidelines for computing crop water requirements.* FAO Irrigation and Drainage Paper 56. FAO,
  Rome. No DOI; https://www.fao.org/4/x0490e/x0490e07.htm (chapter 3).
- Amerine, M. A., Winkler, A. J. (1944). Composition and quality of musts and wines of
  California grapes. *Hilgardia*, 15(6), 493–675. https://doi.org/10.3733/hilg.v15n06p493 —
  DOI-only search: OUCI reference lists.
- Ausseil, A.-G. E., Law, R. M., Parker, A. K., Teixeira, E. I., Sood, A. (2021). Projected wine
  grape cultivar shifts due to climate change in New Zealand. *Frontiers in Plant Science*, 12,
  618039. https://doi.org/10.3389/fpls.2021.618039 — frontiersin.org URL.
- Baldacci, E. (1947). Epifitie di *Plasmopara viticola* (1941–46) nell'Oltrepò Pavese ed
  adozione del calendario di incubazione come strumento di lotta. *Atti dell'Istituto Botanico
  e Laboratorio Crittogamico dell'Università di Pavia*, 8, 45–85. No DOI; secondary quotations.
- Broome, J. C., English, J. T., Marois, J. J., Latorre, B. A., Aviles, J. C. (1995).
  Development of an infection model for Botrytis bunch rot of grapes based on wetness duration
  and temperature. *Phytopathology*, 85, 97–102. https://doi.org/10.1094/Phyto-85-97 —
  DOI-only search: OUCI and Springer reference lists; APS abstract page
  apsnet.org/…/1995Abstracts/Phyto_85_97.htm.
- García de Cortázar-Atauri, I., Brisson, N., Gaudillère, J. P. (2009). Performance of several
  models for predicting budburst date of grapevine (*Vitis vinifera* L.). *International
  Journal of Biometeorology*, 53, 317–326. https://doi.org/10.1007/s00484-009-0217-4 —
  link.springer.com URL.
- Gladstones, J. (1992). *Viticulture and Environment.* Winetitles, Adelaide.
  ISBN 1-875130-12-3 — xclim `references.bib`. No DOI.
- Greer, D. H., Weedon, M. M. (2012). Modelling photosynthetic responses to temperature of
  grapevine (*Vitis vinifera* cv. Semillon) leaves on vines grown in a hot climate. *Plant,
  Cell & Environment*, 35(6), 1050–1064. https://doi.org/10.1111/j.1365-3040.2011.02471.x —
  onlinelibrary.wiley.com URL.
- Gubler, W. D., Rademacher, M. R., Vasquez, S. J., Thomas, C. S. (1999). Control of powdery
  mildew using the UC Davis powdery mildew risk index. *APSnet Features*.
  https://doi.org/10.1094/APSnetFeature-1999-0199 — DOI-only search: APS *Plant Disease*
  reference lists; apsnet.org feature page.
- Hall, A., Jones, G. V. (2010). Spatial analysis of climate in winegrape-growing regions in
  Australia. *Australian Journal of Grape and Wine Research*, 16(3), 389–404.
  https://doi.org/10.1111/j.1755-0238.2010.00100.x — xclim `references.bib`; Wiley URL.
- Huglin, P. (1978). Nouveau mode d'évaluation des possibilités héliothermiques d'un milieu
  viticole. *Comptes Rendus de l'Académie d'Agriculture de France*, 64, 1117–1126. No DOI;
  HAL INRAE record hal-02732734. xclim cites the same title in the *Symposium International sur
  l'Écologie de la Vigne*, Constanța, 1978, pp. 89–98.
- Jones, G. V. (2006). Climate and terroir: impacts of climate variability and change on wine.
  In Macqueen, R. W., Meinert, L. D. (eds.), *Fine Wine and Terroir — The Geoscience
  Perspective*. Geoscience Canada Reprint Series 9, Geological Association of Canada,
  St. John's, 203–216. No DOI.
- Jones, G. V., Duff, A. A., Hall, A., Myers, J. W. (2010). Spatial analysis of climate in
  winegrape growing regions in the western United States. *American Journal of Enology and
  Viticulture*, 61(3), 313–326. https://doi.org/10.5344/ajev.2010.61.3.313 — DOI-only search:
  ajevonline.org/content/61/3/313.
- Killick, R., Fearnhead, P., Eckley, I. A. (2012). Optimal detection of changepoints with a
  linear computational cost. *Journal of the American Statistical Association*, 107(500),
  1590–1598. https://doi.org/10.1080/01621459.2012.737745 — DOI-only search (mindat, Lancaster
  research directory).
- Mori, K., Goto-Yamamoto, N., Kitayama, M., Hashizume, K. (2007). Loss of anthocyanins in
  red-wine grape under high temperature. *Journal of Experimental Botany*, 58(8), 1935–1945.
  https://doi.org/10.1093/jxb/erm055 — academic.oup.com PDF URL `…/58/8/1935/…/erm055.pdf`.
- Page, E. S. (1954). Continuous inspection schemes. *Biometrika*, 41(1/2), 100–115.
  https://doi.org/10.1093/biomet/41.1-2.100 — academic.oup.com URL.
- Parker, A. K., García de Cortázar-Atauri, I., van Leeuwen, C., Chuine, I. (2011). General
  phenological model to characterise the timing of flowering and veraison of *Vitis vinifera*
  L. *Australian Journal of Grape and Wine Research*, 17(2), 206–216.
  https://doi.org/10.1111/j.1755-0238.2011.00140.x — onlinelibrary.wiley.com URL.
- Parker, A., García de Cortázar-Atauri, I., Chuine, I., Barbeau, G., Bois, B., Boursiquot,
  J.-M., et al. (2013). Classification of varieties for their timing of flowering and veraison
  using a modelling approach: a case study for the grapevine species *Vitis vinifera* L.
  *Agricultural and Forest Meteorology*, 180, 249–264.
  https://doi.org/10.1016/j.agrformet.2013.06.005 — Google Scholar lookup link with DOI;
  HAL hal-00846880.
- Parker, A. K., García de Cortázar-Atauri, I., Gény, L., Spring, J.-L., Destrac, A., Schultz,
  H., et al. (2020). Temperature-based grapevine sugar ripeness modelling for a wide range of
  *Vitis vinifera* L. cultivars. *Agricultural and Forest Meteorology*, 285–286, 107902.
  https://doi.org/10.1016/j.agrformet.2020.107902 — DOI-only search: sciencedirect.com URL,
  ADS bibcode 2020AgFM..28507902P.
- Poling, E. B. (2008). Spring cold injury to winegrapes and protection strategies and methods.
  *HortScience*, 43(6), 1652–1662. https://doi.org/10.21273/HORTSCI.43.6.1652 — DOI-only
  search: EDIS and OUCI reference lists.
- Rossi, V., Caffi, T., Giosuè, S., Bugiani, R. (2008). A mechanistic model simulating primary
  infections of downy mildew in grapevine. *Ecological Modelling*, 212(3), 480–491.
  https://doi.org/10.1016/j.ecolmodel.2007.10.046 — DOI-only search: sciencedirect.com, ADS
  2008EcMod.212..480R; RePEc v212y2008i3p480-491.
- Schwarz, G. (1978). Estimating the dimension of a model. *The Annals of Statistics*, 6(2),
  461–464. https://doi.org/10.1214/aos/1176344136 — projecteuclid.org URL.
- Scott, A. J., Knott, M. (1974). A cluster analysis method for grouping means in the analysis
  of variance. *Biometrics*, 30(3), 507–512. https://doi.org/10.2307/2529204 — DOI-only search.
- Sentelhas, P. C., Dalla Marta, A., Orlandini, S., Santos, E. A., Gillespie, T. J., Gleason,
  M. L. (2008). Suitability of relative humidity as an estimator of leaf wetness duration.
  *Agricultural and Forest Meteorology*, 148, 392–400.
  https://doi.org/10.1016/j.agrformet.2007.09.011 — search extract (Springer reference lists);
  flore.unifi.it record.
- Tonietto, J., Carbonneau, A. (2004). A multicriteria climatic classification system for
  grape-growing regions worldwide. *Agricultural and Forest Meteorology*, 124(1–2), 81–97.
  https://doi.org/10.1016/j.agrformet.2003.06.001 — xclim `references.bib`.
- Winkler, A. J., Cook, J. A., Kliewer, W. M., Lider, L. A. (1974). *General Viticulture.*
  2nd ed. University of California Press, Berkeley. ISBN 0-520-02591-1. No DOI.
- Zabadal, T. J., Dami, I. E., Goffinet, M. C., Martinson, T. E., Chien, M. L. (2007). *Winter
  injury to grapevines and methods of protection.* Michigan State University Extension
  Bulletin E2930, 105 pp. No DOI; authors confirmed in search extracts.
- Zahumenský, I. (2004). *Guidelines on Quality Control Procedures for Data from Automatic
  Weather Stations.* World Meteorological Organization, Geneva. No DOI.

Secondary and software sources used for values:

- xclim 0.62.0 (Ouranos), source distribution from PyPI: `xclim/indices/_agro.py`
  (`huglin_index`, `biologically_effective_degree_days`, `cool_night_index`),
  `xclim/indices/helpers.py` (`huglin_day_length_latitude_coefficient`),
  `xclim/indices/converters.py` (Magnus coefficient sets), `docs/references.bib`.
- UC IPM, *Models: Powdery Mildew of Grape*,
  https://ipm.ucanr.edu/DISEASE/DATABASE/grapepowderymildew.html; *Powdery Mildew / Grape*,
  https://ipm.ucanr.edu/agriculture/grape/powdery-mildew/; *Models: Botrytis Bunch Rot of
  Grape*, https://ipm.ucanr.edu/DISEASE/DATABASE/grapebotrytis.html.
- Pest Prophet blog, *How to Use Powdery Mildew Risk Index Model on Grapes*,
  https://blog.pestprophet.com/how-to-use-powdery-mildew-risk-index-model-on-grapes/.
- Sturman, A., Zawar-Reza, P., Soltanzadeh, I., Katurji, M., Bonnardot, V., Parker, A. K.,
  Trought, M. C. T. The application of high-resolution atmospheric modelling to weather and
  climate variability in vineyard regions. *OENO One*, https://oeno-one.eu/article/view/1538.
  [year and volume not verified] [DOI not verified]
- ČHMÚ (Czech Hydrometeorological Institute), statement on tropical (hot) days of 2024 on X
  (@CHMUCHMI); Wikipedia (cs), *Charakteristický den*.
