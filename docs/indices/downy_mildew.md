# Downy mildew (not implemented)

> **Status: not implemented.** This page explains why, and what would be needed. There is no
> `ClimateIndex` for downy mildew and no index id in the site data.

## Purpose

Grapevine downy mildew (*Plasmopara viticola*) is, together with powdery mildew, the most
important fungal disease of grapevine in Central Europe. A warning model would tell growers
when primary or secondary infections are likely to have happened.

## Why it is not implemented

The infection biology of downy mildew is driven by **water**. Oospores overwinter in leaf
litter and germinate in wet soil, and their zoospores reach the leaves in rain splash.
Infection needs free water on the leaf surface. The established models therefore need
rainfall and/or leaf wetness as **inputs**:

- **"3-10 rule"** (attributed to Baldacci, 1947; attribution and conditions verified in WP-L.1
  against secondary sources): primary infections are
  expected once the air temperature is at least 10 °C, at least 10 mm of rain has fallen within
  24-48 h, and the shoots are at least 10 cm long. **Rainfall** is a mandatory input, and the
  shoot length needs a phenological observation.
- **Rossi et al. (2008)**: a mechanistic model of primary infections that simulates oospore
  maturation and germination, zoospore release, dispersal and infection. It is driven by
  hourly **rainfall**, **leaf wetness**, temperature and relative humidity.

Our sensors measure **only air temperature and relative humidity** at ~30-minute intervals. A
model run with rainfall and wetness replaced by a humidity proxy would no longer be either
model. Neither step can be estimated from humidity: dispersal of the zoospores depends on rain
splash, and infection depends on free water on the leaf, which humidity does not measure. A result labelled "downy mildew" could not be validated and could mislead spraying
decisions, so the project does not compute one.

## What would be needed

| Need | Why | Notes |
|---|---|---|
| **Rain gauge** (tipping bucket, ≤ 0.2 mm resolution) at or near each vineyard | rainfall triggers primary infections (3-10 rule, Rossi et al. 2008) and splash dispersal | a single gauge per vineyard block may serve several T/RH sensors |
| **Leaf-wetness sensor** in the canopy | duration of surface wetness for the infection step; also replaces the RH proxy of `botrytis_broome` | needs placement and calibration rules (height, angle, orientation) |
| **Phenology observations** (budbreak, shoot length ≥ 10 cm, BBCH stages) | the 3-10 rule needs shoot length, and susceptibility depends on the stage | e.g. a phenology diary in the repository (proposal in MIGRATION_PLAN §3.1) |
| Data contract change | new variables (`rain_mm`, `leaf_wetness_min` or similar) in `MeasurementSeries`, the store and the site data | a plan change approved by the owner (MIGRATION_PLAN §0.3/3) |

## What could be done later

1. Once a rain gauge exists: implement the **3-10 rule** as a simple primary-infection
   warning, with shoot length from the phenology diary or the `budburst` index (WP-2.1).
2. Once leaf wetness exists: implement the primary-infection model of **Rossi et al. (2008)**
   and secondary-infection rules. Re-tune the wetness proxy of `botrytis_broome` against the
   measured wetness, or replace the proxy with it.
3. Alternatively, rainfall from an open reference station (ČHMÚ open data, see MIGRATION_PLAN
   §3.4) could feed the 3-10 rule. This would be a regional rather than a vineyard-level
   estimate and would have to be labelled `estimated`.

## Implementation

None. If one is added later, it would be a new `ClimateIndex` subclass in
`sivin.analytics.disease`, registered under its own id, with its own `docs/indices/<id>.md`.

## References

- Baldacci, E. (1947). Epifitie di *Plasmopara viticola* (1941-46) nell'Oltrepò Pavese ed
  adozione del calendario di incubazione come strumento di lotta. *Atti dell'Istituto Botanico
  e Laboratorio Crittogamico dell'Università di Pavia*, 8, 45-85. (No DOI; volume and pages
  as quoted by secondary sources, the series number given before could not be confirmed.)
- Rossi, V., Caffi, T., Giosuè, S., Bugiani, R. (2008). A mechanistic model simulating primary
  infections of downy mildew in grapevine. *Ecological Modelling*, 212(3), 480-491.
  https://doi.org/10.1016/j.ecolmodel.2007.10.046
