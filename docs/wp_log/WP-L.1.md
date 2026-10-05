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

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
