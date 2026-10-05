# WP-L.1 — Literature and parameter verification

## Summary

Every citation and every `[to be verified]` / `[DOI not verified]` marker in `docs/indices/**`,
the references of `docs/quality-control.md` and `src/sivin/analytics/**` was inventoried and
checked against web sources. The result is in
[`docs/literature-verification.md`](../literature-verification.md): one table per topic
(claim, where used, source, value in source, code before → after, status) plus a bibliography
with 21 verified DOIs. One value was **corrected**: the GFV "general-model candidates"
1282 / 2528 °C·d are the **Sauvignon blanc** values of Parker et al. (2013), not species-level
values. The optional GSR cultivar preset `GSR_CULTIVAR_PRESETS` (Sauvignon blanc, 200 g/L,
2820 °C·d) was added and is not active. No default parameter value and no index result changed.
Thresholds that are project defaults (heat bands, hard frost, winter freeze) are now labelled as
such instead of carrying a literature marker.

**Important limit:** direct page access (WebFetch, curl) was blocked by the sandbox for every
publisher, indexing and DOI host. Verification used the web search tool (result URLs and
machine-written extracts) and the source of xclim 0.62.0 from PyPI. Values were accepted only
when consistent across sources; the rows marked `verified (secondary)` should be confirmed
against the primary tables by someone with library access.

## Changed files

- `src/sivin/analytics/thermal/huglin.py`, `gst.py`, `bedd.py`, `phenology.py`,
  `__init__.py` — docstrings and field descriptions (sources instead of markers); new
  constant `GSR_CULTIVAR_PRESETS` (exported from `sivin.analytics.thermal`).
- `src/sivin/analytics/ripening/cool_night.py`, `heat_hours.py`, `frost.py`, `winter_freeze.py`
  — docstrings and field descriptions only.
- `src/sivin/analytics/disease/gubler_thomas.py`, `botrytis.py` — docstrings and field
  descriptions only.
- `tests/analytics/thermal/test_phenology.py` — module docstring corrected; new hand-computed
  test of the GSR preset.
- `docs/indices/*.md` (all 18) — sources, DOIs, corrections, GFV enablement and GSR preset
  sections.
- `docs/quality-control.md` — References section only (DOIs, note on Zahumenský limits).
- `docs/literature-verification.md` (new), `docs/wp_log/WP-L.1.md` (new).

## How it was verified

- `make lint` → ruff check: all checks passed; ruff format --check: 191 files already
  formatted.
- `make type` → mypy --strict: no issues found in 116 source files.
- `make test` → 1279 passed.
- `make cov` → total 99 %; every changed module in `src/sivin/analytics/**` 100 %;
  `pytest --cov=sivin.analytics tests/analytics` → 1812 statements, 0 missed, 100 %.
- New test `test_gsr_cultivar_preset_is_optional_and_predicts`: constant 15 °C/day from April 1,
  2820 / 15 = 188 days → October 5 (DOY 278), computed by hand.
- Sources and status per claim: `docs/literature-verification.md`.

## What did not work / what was not verified

- **No primary text was read.** WebFetch and curl were refused by the egress proxy for doi.org,
  api.crossref.org, api.openalex.org, Wiley, ScienceDirect, OENO One, UC IPM, ResearchGate,
  HAL, Wikipedia and others. DOIs were confirmed through publisher URLs in search results, the
  xclim bibliography, or reference lists found by searching for the DOI string alone.
- Search extracts were inconsistent twice (Chardonnay GSR value: 200 vs 170 g/L target; Pinot
  noir GFV véraison: 2507 vs 2511 °C·d); those values were rejected. As a consequence **no
  GFV/GSR value is provided for the South-Moravian cultivars** (Grüner Veltliner, Riesling,
  Pinot blanc, Chardonnay, Müller-Thurgau, Welschriesling, Pinot noir, Blaufränkisch, Saint
  Laurent, Zweigelt); whether Parker et al. (2013, 2020) list them at all was not checked.
- Still `[to be verified]`: GFV species-level F* (Parker et al. 2011); Huglin daily-mean
  definition; BEDD day-length coefficient and `before_adjustment` order; budburst 5 °C base;
  Gubler-Thomas daily decrease limit, heat before onset, no restart, wording of the 40–50 class.
- Poling (2008) critical-temperature table, Zabadal et al. (2007) thresholds and the Gladstones
  (1992) book were not readable; the corresponding code values are project defaults.
- Year, volume and DOI of Sturman et al. (OENO One article 1538), used only as a secondary
  source, were not found.

## Out of scope

- `MIGRATION_PLAN.md` §7: the three `[ověřit]` items (Greer & Weedon 2012; Gubler et al. 1999
  authors; Zabadal et al. 2007 authors) are verified, and DOIs are now known for most entries;
  §7 says "Huglin … 64, 1117–1126" (confirmed) and "Rossi … 212, 480–491" (confirmed). The
  plan could carry the DOIs from `docs/literature-verification.md` — owner's file.
- `MIGRATION_PLAN.md` §0.3/5 says DOI verification is an owner item because doi.org is not
  reachable; with this WP most DOIs are verified indirectly, the rule text could be updated.
- BEDD: the project floors the daily contribution at 0, xclim does not; the difference matters
  only on cold days with DTR < 10 °C (documented in `bedd.md`, no change).
- The legacy `vineyard_analyst.py` Magnus coefficients (17.27 / 237.7) are kept as
  `LEGACY_MAGNUS`; no change needed.

## Open questions for the owner

1. **Gubler-Thomas, heat on a non-favourable day.** A secondary description (Pest Prophet blog)
   says the index "should not decline by more than 10 points" in one day, so a non-favourable
   day with ≥ 95 °F would be −10, not −20 as implemented. The UC IPM/APSnet text that would
   confirm it could not be opened. Apply the 10-point daily limit (small code change in
   `GublerThomasModel`, new parameter, test), or keep the current rule? In South Moravia the
   case (≥ 35 °C on a day without 6 h in 21–29 °C) is rare.
2. **GFV/GSR cultivar values.** Can you (or someone with library access) copy the F* rows for
   your cultivars from Parker et al. (2013, Table/Supplement) and Parker et al. (2020)? They
   can then be added to `GSR_CULTIVAR_PRESETS` (and a GFV equivalent) with the page reference.
   Related: plan Q4 (cultivar per sensor).
3. **Config/CLI wiring (for WP-1.7).** Proposed: `analytics.indices.gsr.targets` accepts either
   explicit targets or a `preset: sauvignon_blanc` key resolved through
   `GSR_CULTIVAR_PRESETS`; `analytics.indices.gfv` stays without defaults. No new CLI command.
4. **Contract note.** `GSR_CULTIVAR_PRESETS` is a module constant in `thermal/phenology.py`; if
   presets should be per sensor (registry `variety` field, §2.4), the integration WP needs to
   map `variety` → preset key. No contract change is proposed here.

## Review

Verdict: APPROVE (round 1)

Reviewer: independent reviewer session, 2026-10-05. Same access limits as the worker: WebFetch
was refused by the egress proxy (tried ipm.ucanr.edu and pmc.ncbi.nlm.nih.gov), so the
re-checks below rest on independent WebSearch queries (result URLs + machine-written
extracts), my own knowledge of the literature, and the code itself. Nothing was read in a
primary table.

### Gates (run by the reviewer in `/home/user/wt/wp-L.1`)

- `make lint` -> ruff check passed, ruff format: 191 files already formatted.
- `make type` -> mypy --strict: no issues found in 116 source files.
- `make test` -> 1279 passed.
- `make cov` -> 1279 passed, TOTAL 99 %; `sivin/analytics/thermal/phenology.py` 100 %.

### Independent spot-check (task 1-3)

Each item re-searched by the reviewer; "corroborated" means an independent query (not the
worker's) returned the same value or DOI.

| Claim | Worker status | Reviewer result |
|---|---|---|
| GFV 1282 / 2528 °C·d are Sauvignon blanc (Parker et al. 2013), not general model | corrected | corroborated (two queries; extracts of OENO One art. 1538 and Ausseil 2021 give "Sauvignon blanc: F* = 1282 / 2528, base 0 °C, DOY 60"). Parker et al. (2011) abstract extract gives only a range of variety F* (flowering 1120-1411, véraison 2286-2941), so keeping the general F* `[to be verified]` is correct. |
| GSR Sauvignon blanc 200 g/L = 2820 °C·d (Parker 2020 via Ausseil 2021) | verified (secondary) | corroborated (Ausseil et al. 2021 extract: "F* for Sauvignon blanc for 200 g/l is 2820, from Parker et al. 2020a") |
| GSR base 0 °C, DOY 91, six targets 170-220 g/L, 65 cultivars | verified (secondary) | corroborated (ScienceDirect/ADS/IVES extracts) |
| GFV base 0 °C, DOY 60 | verified (secondary) | corroborated |
| Gubler-Thomas 70-85 °F, 6 h, 3 days, +20/-10, 95 °F 15 min -10, favourable+heat = +10 | verified (secondary) | corroborated (UC IPM / Pest Prophet extracts) |
| Gubler-Thomas onset index 60 (3 x 20) | verified (secondary) | corroborated ("for each of these three days, the model assigns 20 points ... after 3 days an index of 60") |
| Broome logit coefficients, R² = 0.75 | verified (secondary) | corroborated (UC IPM extract, identical coefficients) |
| GST classes 13-15-17-19-24 °C, Jones (2006) | verified (secondary) | corroborated (extract also gives the 13-21 °C quality limit) |
| Huglin classes 1500/1800/2100/2400/3000, "> lower, <= upper" | verified (secondary) | corroborated (ClimClass/ResearchGate/Embrapa extracts) |
| BEDD cap 9, DTR 10/13 °C, factor 0.25 | verified (secondary) | corroborated (xclim docs extract) |
| Magnus AERK 17.625 / 243.04 / 6.1094 | verified | corroborated |
| Zahumenský step 2 °C, persistence 0.1 °C / 60 min | verified (citation) | corroborated |
| Baldacci (1947) Atti Ist. Bot. Lab. Crittogam. Pavia 8, 45-85 | corrected (citation) | corroborated |
| Greer & Weedon (2012): light-saturated optimum 30 °C | background only | corroborated |
| Poling (2008): about -2.2 °C after budburst | secondary | corroborated |

DOIs re-searched by the reviewer and corroborated by a result for the DOI string or a
publisher URL: Gubler et al. 1999 (APSnetFeature-1999-0199), Sentelhas et al. 2008, García de
Cortázar-Atauri et al. 2009, Greer & Weedon 2012, Rossi et al. 2008, Parker et al. 2013,
Amerine & Winkler 1944, Jones et al. 2010, Poling 2008, Ausseil et al. 2021, Parker et al.
2011 (Wiley URL), Parker et al. 2020 (ScienceDirect/ADS). The remaining nine (Alduchov &
Eskridge 1996, Broome et al. 1995, Hall & Jones 2010, Killick et al. 2012, Mori et al. 2007,
Page 1954, Schwarz 1978, Scott & Knott 1974, Tonietto & Carbonneau 2004) agree with the
reviewer's own knowledge of these papers and were not re-searched individually. No DOI, value
or page in the report was found to be wrong or invented.

### Code (task 5)

- Changes in `src/sivin/analytics/**` are docstrings/field descriptions plus the new
  read-only `GSR_CULTIVAR_PRESETS` (MappingProxyType of tuples of frozen `PhenologyStage`) and
  its re-export. No formula touched.
- Mechanical check: dumped `model_dump()` of every pydantic model with defaults and every
  upper-case module constant in `sivin.analytics` at base `11f71ef` and at `HEAD`
  (throwaway script in `/tmp/claude-0/review-L.1/`). The only difference is the new preset
  constant; all defaults are identical, so no index result can change.
- New test `test_gsr_cultivar_preset_is_optional_and_predicts`: 2820 / 15 = 188 days from
  April 1 -> October 5, DOY 278 — hand-checked, correct.
- Scope: all changed files lie in the Files scope; in `docs/quality-control.md` only the
  References section changed.

### Relabelling (task 4)

Heat bands, hard frost, winter freeze are labelled "project default (plan §3.2), not a
literature value" consistently in code descriptions and in `heat_hours.md`, `frost.md`,
`winter_freeze.md`. Every remaining `[to be verified]` in `src/sivin/analytics/**` and
`docs/indices/**` corresponds to a row marked unverifiable in the report. No number found that
is still presented as literature-backed without a source.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | `docs/literature-verification.md:120`, `docs/indices/tropical_days_nights.md:60-65` | Characteristic-day thresholds are `verified (secondary)` on the basis of a ČHMÚ post on X and Czech Wikipedia only. That is weaker than the other `verified (secondary)` rows (which rest on a named scientific or institutional secondary source) and the method section's own rule. Suggest status `partly verified` (tropical day ≥ 30 °C by ČHMÚ; the rest via Wikipedia) or say so in the cell. | open |
| minor | `docs/literature-verification.md:29-37` | Report clarity: the owner has to scan ~20 `verified (secondary)` rows to know what needs library access. Add a short explicit list "To confirm with library access": Parker 2013 table (GFV cultivar F*, incl. general F* of Parker 2011), Parker 2020 table (GSR presets, South-Moravian cultivars), Jones 2006 figure (GST), Gladstones 1992 (BEDD constants, day-length coefficient, cap order), Tonietto & Carbonneau 2004 tables (K bands, HI/CI classes and names), UC IPM / Gubler 1999 text (daily decrease limit, classes wording), Broome 1995 (coefficients, fitting range), Poling 2008, Zabadal 2007, Huglin 1978 daily-mean definition. | open |
| nit | `docs/literature-verification.md:124`, `:125` | Magnus and FAO-56 rows say `verified` although, as for other rows, the primary text was not read (extracts + xclim). Either `verified (secondary)` or note that the status refers to multiple concordant sources; harmless since values are standard. | open |
| nit | `docs/indices/gfv.md:143-146`, `docs/literature-verification.md:266-269` | Sturman et al.: a reviewer search returned OENO One 2017, 51(2), 99-105, HAL hal-01671144, DOI shown as 10.20870/oeno-one.2016.0.0.1538 (single extract, not confirmed). Could be added with `[DOI not verified]`; current text is honest as is. | open |
| nit | `docs/literature-verification.md` bibliography, Zabadal entry | "105 pp." is not mentioned among the confirmed facts; drop it or state its source. | open |

No blocker or major finding.

### Deviations assessment

- No GFV/GSR values for South-Moravian cultivars: correct decision. Rejecting values whose
  extracts disagreed (Chardonnay target, Pinot noir véraison) follows the stated method and the
  "never invent values" rule.
- Gubler-Thomas daily-decrease limit not applied, raised as owner question: correct — the only
  source is a commercial blog; changing behaviour on that basis would be worse than asking.
- `GSR_CULTIVAR_PRESETS` as a module constant (not wired into config): within scope and
  inactive by default as the owner decided; the proposed config key for WP-1.7 is reasonable.
- The honesty of the report is good: the method section states the access limit, the meaning of
  each status, and that no primary text was read; the hand-off note repeats it. The "21 DOIs"
  count matches the bibliography.
