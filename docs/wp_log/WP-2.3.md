# WP-2.3 — Disease models

## Summary

New package `sivin.analytics.disease` with two registered climate indices and one documented
non-implementation.

- **`powdery_mildew_gt`** (`PowderyMildewGublerThomas`) implements the Gubler-Thomas (UC Davis)
  powdery mildew risk index as a readable day-by-day state machine, `GublerThomasModel`.
  It has two phases, *waiting for onset* and *active*, and an explicit rule for days without
  enough data.
- **`botrytis_broome`** (`BotrytisBroome`) implements the Broome et al. (1995) logit infection
  model. Wetness is *estimated* as runs of RH ≥ 90 % with bridged short dry interruptions, so
  every result has `estimated=True`.
- Hour-based quantities are computed from the time each sample represents
  (`SampleDurations`, `RunFinder`), never from row counts.
- `docs/indices/downy_mildew.md` explains why downy mildew is not modelled (rain and leaf
  wetness are not measured) and what hardware would be needed.

## Changed files

- `src/sivin/analytics/disease/__init__.py`: package docstring and re-exports. Importing the
  package registers both indices.
- `src/sivin/analytics/disease/sampling.py`: `SamplingParams`, `SampleDurations`,
  `SampleTiming`, `SampleRun`, `RunFinder`.
- `src/sivin/analytics/disease/period.py`: `SeasonWindow`, a configurable model period mapped
  to `Season`.
- `src/sivin/analytics/disease/result.py`: `DiseaseIndex[P]`, the common base that builds the
  `IndexResult`, the days the model runs over and the daily curve.
- `src/sivin/analytics/disease/gubler_thomas.py`: `fahrenheit_to_celsius`,
  `GublerThomasParams`, `DayAssessment`, `Phase`, `GublerThomasState`, `GublerThomasModel`,
  `RiskClass`.
- `src/sivin/analytics/disease/powdery_mildew.py`: `PowderyMildewDayAssessor`,
  `PowderyMildewGublerThomas`.
- `src/sivin/analytics/disease/botrytis.py`: `BroomeCoefficients`, `logistic`, `RiskBand`,
  `BotrytisBroomeParams`, `WetnessPeriod`, `InfectionEvent`, `WetnessPeriodDetector`,
  `BotrytisBroome`.
- `tests/analytics/disease/{conftest,test_sampling,test_gubler_thomas,test_botrytis}.py`.
- `docs/indices/{powdery_mildew_gt,botrytis_broome,downy_mildew}.md`, `docs/wp_log/WP-2.3.md`.

## Public API

```python
from sivin.analytics.disease import (
    PowderyMildewGublerThomas,      # index_id "powdery_mildew_gt", unit "points"
    GublerThomasParams, GublerThomasModel, GublerThomasState, DayAssessment, Phase, RiskClass,
    PowderyMildewDayAssessor, fahrenheit_to_celsius,
    BotrytisBroome,                 # index_id "botrytis_broome", unit "1", estimated=True
    BotrytisBroomeParams, BroomeCoefficients, RiskBand, WetnessPeriodDetector,
    WetnessPeriod, InfectionEvent, logistic,
    SamplingParams, SampleDurations, SampleTiming, SampleRun, RunFinder, SeasonWindow,
    DiseaseIndex,
)
GublerThomasModel(params).step(state, day) / .run(days) / .classify(points)
BotrytisBroome(params).infection_events(ctx) -> list[InfectionEvent]
BroomeCoefficients().logit(wetness_h, temp_c) / .infection_probability(wetness_h, temp_c)
SampleDurations(nominal_interval_s, max_duration_s).measure(timestamps_utc) -> SampleTiming
RunFinder(max_interruption_s=0.0).find(timing, condition, valid) -> list[SampleRun]
```

**Results.**

- `powdery_mildew_gt`:
  - `value` is the season maximum of the index (points).
  - `classification` is the class of the last day (`low`/`moderate`/`high`).
  - `daily` is the index per local day.
  - `details` has `onset_date`, `current_index_points`, `phase` and day counts.
- `botrytis_broome`:
  - `value` is the season maximum of Y (0-1).
  - `daily` is the daily maximum of Y.
  - `details` has `n_events`, `wetness_proxy` and flat `event_NNN_*` keys (start, duration,
    mean T, Y).
  - `classification` is `None` unless `risk_bands` are configured.

## How it was verified

All commands were run in `/home/user/wt/wp-2.3` with a uv-created `.venv` (Python 3.12).

- `make lint`: `All checks passed!`, `43 files already formatted`.
- `make type`: `Success: no issues found in 27 source files` (mypy `--strict`, no ignores in
  `src/`).
- `make test`: `213 passed` (181 foundation + 32 new).
- `make cov`: every module of `sivin/analytics/disease` is at 100 % (statements and
  branches, 492 statements and 86 branches in total). `TOTAL 1317 0 264 0 100%`.
- The test expectations were computed by hand, with the arithmetic in comments:
  - Gubler-Thomas state machine on a 23-day sequence: onset after a reset streak, growth to the
    bound of 100, +20/−10 heat on the same day, an undetermined day held, observed heat on an
    undetermined day, decline to the bound of 0.
  - A 10-day hourly integration example: index `0,0,60,70,60,60,80,60,80,70`, with an
    incomplete day that still shows a 10 h run and the band edges 21.2 °C (in) and
    29.5 °C (out).
  - Legacy 1825 s sampling: 12 samples (6.08 h) give a favourable day, 11 samples (5.58 h) do
    not.
  - A QC-excluded sample breaks a run.
  - Broome: Y(5 h, 15 °C) = 0.1676603 and Y(3 h, 20 °C) = 0.1312688; a bridged dry hour;
    missing and QC-excluded RH end events; the duration-weighted mean temperature.
  - A day with temperature but **no humidity**: coverage 2/3, `complete=False`, daily `NaN`
    (orchestrator request).
  - The empty-season case for both indices.

## What did not work / what was not verified

- **The literature values were not checked against the sources** (no access from the
  sandbox). The Gubler-Thomas rules (70-85 °F, 6 h, 3 days, +20/−10/−10 at 95 °F for 15 min,
  0-100, classes 0-30/40-50/60-100) and the Broome coefficients
  (−2.647866, −0.374927, 0.061601, −0.001511) were reproduced from knowledge. The coefficients
  are marked `[to be verified]` in the code and docs. The UC IPM class meanings are marked as
  paraphrased from memory.
- **Citations not verified:** the authors and venue of Gubler et al. (1999) (already
  `[ověřit autory]` in plan §7), the UC IPM guideline date, Baldacci (1947) and Sentelhas et
  al. (2008). No DOIs are given.
- **No real data.** All tests use synthetic series. The RH ≥ 90 % wetness proxy, the 1 h
  interruption limit and the 2.5 × 1825 s gap cap are untuned project defaults.
- The index values have not been compared with observed disease in the vineyards.

## Decisions and deviations from the brief

1. **Sample duration at a gap.** The brief says each sample represents the time until the next
   one, "capped at a configurable maximum". Here a step **above** the cap is a data gap: the
   sample counts only the **nominal** interval, not the cap, and the gap ends any run. This
   avoids crediting, for example, 76 min to a sample that is followed by a 10 h outage.
   Default cap: 2.5 × 1825 s, which bridges one missing sample including clock drift.
2. **Heat rule as a duration.** "≥ 95 °F for ≥ 15 min" is implemented as valid samples ≥ 35 °C
   representing ≥ 15 min (`min_heat_duration_min`). With ~30-minute sampling this equals the
   brief's "at least one valid sample ≥ 35 °C", and it stays correct with denser sampling.
3. **Undetermined days** (no qualifying run and temperature coverage below
   `min_daily_coverage`) leave the state unchanged. While waiting the streak is neither
   counted nor reset. Once active there is no +20 and no −10, but observed heat still costs
   10 points. A low-coverage day that already shows a ≥ 6 h run counts as favourable.
4. **Index at onset = 60** (3 × 20). **Heat and hours apply independently** on the same day
   (net +10 or −20). **Heat is ignored before onset.** The index stays active once started.
   All of these are documented interpretation choices.
5. **Default periods** are April 1 - October 31 for both models (project default; the
   literature starts at budbreak or bloom). The period is configurable as `season`.
6. **Daily curves** start at the first day with samples in the period, not at the period
   start.
7. **Broome W includes bridged dry interruptions** (span from the first wet sample to the end
   of the last). A period counts on the local date of its last wet sample.
8. **Broome value without events is 0.0** when the period has data, and `None` without data.
   No literature class limits exist, so `risk_bands` is empty by default and
   `classification` is `None`.
9. **Broome coverage** uses days where both `temp_coverage` and `rh_coverage` reach the
   threshold (own helper; `ClimateIndex._season_days` checks temperature only).
10. `details` only allows flat scalars, so the Broome events are flattened into `event_NNN_*`
    keys. The structured list is available from `BotrytisBroome.infection_events()`.

## Out of scope

- **Duplicated sample-duration logic.** `sivin.analytics.disease.sampling`
  (`SampleDurations`, `RunFinder`) will be duplicated by the hour-based indices of WP-2.2
  (`heat_hours`, `frost`, `vpd`), which have their own copy. Proposal: move one
  implementation to `sivin.core` (e.g. `sivin/core/durations.py`) in an integration WP and let
  both packages use it.
- **`ClimateIndex._season_days` / `DailyWeather.complete_days`** filter on temperature coverage
  only. Humidity-based indices (here Botrytis; in WP-2.2 `dew_point`, `vpd`) need an RH-aware
  variant. Proposal: a `variables` argument, e.g. `_season_days(ctx, season, ("temp", "rh"))`.
- **`IndexResult.details`** cannot hold lists or records. Per-event outputs (Botrytis
  wetness events, later frost events) have to be flattened. Proposal: an optional
  `events: tuple[Mapping[str, ...], ...]` field, or a separate events file in the site contract
  (§2.6), if the web should show them.
- `DiseaseIndex._result` / `_model_days` / `_daily_series` would suit other index packages
  too (a generic result builder on `ClimateIndex`).

## Open questions for the owner

1. **Configuration and CLI (for WP-1.7/3.2).** Proposed config section
   `analytics.indices.<index_id>` holding the params of each index (`GublerThomasParams`,
   `BotrytisBroomeParams`, built with `index_registry.create(id, mapping)`). Proposed CLI:
   `sivin indices compute --season 2026 [--index powdery_mildew_gt]`.
2. **Gubler-Thomas rules to confirm from the original text:** (a) does the index start at 60
   or at 0 after the 3 onset days; (b) can a day lose more than 10 points (non-favourable +
   heat); (c) does the index restart after falling to 0?
3. **Budbreak / bloom dates:** should the disease periods start at a phenological date (from a
   phenology diary or the `budburst` index of WP-2.1) instead of April 1?
4. **Botrytis risk classes:** are there local or advisory limits for Y that should be
   configured, or should the web show Y without classes?
5. **Wetness proxy tuning:** is a leaf-wetness sensor (or rain gauge) planned at one site, so
   that the RH threshold and interruption limit can be calibrated?

## Review

Verdict: _pending_ (round 1)

| Severity | File:line | Finding | Status |
|---|---|---|---|
