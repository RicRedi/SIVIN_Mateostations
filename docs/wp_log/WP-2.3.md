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
  - `classification` is the class of that season maximum (`low`/`moderate`/`high`).
  - `daily` is the index per local day.
  - `details` has `onset_date`, `current_index_points`, `current_class` (class of the last
    day), `phase` and day counts.
- `botrytis_broome`:
  - `value` is the season maximum of Y (0-1).
  - `daily` is the daily maximum of Y.
  - `details` has the summary keys `n_events`, `wetness_proxy`, `total_wetness_h` and
    `max_infection_probability`, plus the event with the highest Y (`max_event_start_utc`,
    `max_event_duration_h`, `max_event_mean_temp_c`). The full list comes from
    `infection_events(ctx)`.
  - `classification` is `None` unless `risk_bands` are configured.

## How it was verified

All commands were run in `/home/user/wt/wp-2.3` with a uv-created `.venv` (Python 3.12).

- `make lint`: `All checks passed!`, `43 files already formatted`.
- `make type`: `Success: no issues found in 27 source files` (mypy `--strict`, no ignores in
  `src/`).
- `make test`: `213 passed` (181 foundation + 32 new). Round 2: see below.
- `make cov`: every module of `sivin/analytics/disease` is at 100 % (statements and
  branches, 492 statements and 86 branches in total). `TOTAL 1317 0 264 0 100%`.
- Round 2: ROUND2_GATES
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
   counted nor reset, for at most `max_undetermined_carry_days` (default 1, project default
   [to be tuned]) consecutive undetermined days; a longer run resets the streak (round 2). Once active there is no +20 and no −10, but observed heat still costs
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
10. `details` only allows flat scalars, so Broome reports summary keys and the event with the
    highest Y there (round 2; round 1 flattened every event). The structured list is
    available from `BotrytisBroome.infection_events()`.
11. **`max_wetness_h`** (round 2): an optional cap on the W used in the Broome formula
    (default `None`, no cap; project choice), because Y saturates near 1 for W > 24 h.
12. **Midnight split** (round 2, documented, behaviour unchanged): a Gubler-Thomas run that
    crosses local midnight is split per day.

## Out of scope

- **Duplicated sample-duration logic.** `sivin.analytics.disease.sampling`
  (`SampleDurations`, `RunFinder`) will be duplicated by the hour-based indices of WP-2.2
  (`heat_hours`, `frost`, `vpd`), which have their own copy. Proposal: move one
  implementation to `sivin.core` (e.g. `sivin/core/durations.py`) in an integration WP and let
  both packages use it.
- **`ClimateIndex._season_days` / `DailyWeather.complete_days`** filter on temperature coverage
  only. Humidity-based indices (here Botrytis; in WP-2.2 `dew_point`, `vpd`) need an RH-aware
  variant. Proposal: a `variables` argument, e.g. `_season_days(ctx, season, ("temp", "rh"))`.
- **`IndexResult.details`** cannot hold lists or records, so per-event outputs (Botrytis
  wetness events, later frost events) are reduced to summary keys. Proposal for a contract
  change (owner approval, §0.3/3):
  - add an optional field `events: tuple[Mapping[str, float | int | str], ...] = ()` to
    `IndexResult`, with one record per event, for example
    `{start_utc, end_utc, duration_h, mean_temp_c, infection_probability}`;
  - in the site contract (§2.6), extend `indices/<season>.json` with an optional
    `"events": [...]` per sensor and index, using Unix seconds for times like the rest of the
    contract. Alternatively, write `site/data/index_events/<season>/<sensor_id>.json`, so that
    the index summary stays small.
  `BotrytisBroome.infection_events()` already returns the records this field would carry.
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

Verdict: APPROVE (round 1)

Reviewer: independent reviewer agent; nothing below was fixed by the reviewer.

**Gates observed** (in `/home/user/wt/wp-2.3`):

- `make lint`: `All checks passed!`, `43 files already formatted`.
- `make type`: `Success: no issues found in 27 source files`.
- `make test`: `213 passed`.
- `make cov`: every module of `sivin/analytics/disease` is at 100 % (statements and branches);
  `TOTAL 1317 0 264 0 100%`.
- Scope: `git diff --name-only bcde7d9...HEAD` lists only files in the WP-2.3 Files scope and
  the hand-off note. No shared file was touched. `src/sivin/analytics/disease` has no `type: ignore`,
  `Any` or `cast`.

**Independent checks** (throwaway scripts in `/tmp/claude-0/review-2.3/`, outside the repo):

- `SampleDurations` and `RunFinder` on irregular steps with drift and two gaps
  (offsets 0, 1830, 3640, 5470, 10500, 12330, 14150, 15990, 30000, 31820 s; cap 4562.5 s).
  Hand result for the durations: 1830, 1810, 1830, 1825 (gap), 1830, 1820, 1840, 1825 (gap),
  1820, 1825 (last sample). With sample 6 out of band and no bridging, the runs are
  0-3 = 7295 s, 4-5 = 3650 s, 7 = 1825 s and 8-9 = 3645 s. With bridging up to 1900 s, the
  run 4-7 is 7315 s with 1840 s of interruption. The code gives exactly these values.
- Gubler-Thomas over 30 days of 1827 s sampling (drifting clock), 7 h per day in the band.
  The index goes 0, 0, 60, 80, 100, ...; the longest run is 7.105 h (the represented time,
  up to the first sample out of band). Onset is on day 3.
- A night run in the band from 21:00 to 03:00 local gives 0 favourable days. The run is split
  at midnight into about 3 h + 3 h (see finding 2).
- Outage: 1 favourable day, then 11 days without data, then 2 favourable days. Onset happens
  on the 14th day with index 60 (see finding 1).
- Botrytis over the DST-end night (Oct 24/25): an RH ≥ 90 % period from 21:00 to 06:00 local with
  one bridged dry sample gives W = 10.14 h, which includes the extra DST hour. The period is
  counted on its end date (Oct 25), and `estimated=True`. A period that starts on Oct 31 and
  ends on Nov 1 is dropped, and the value is 0.0.
- Broome Y(5 h, 15 °C) = 0.16766 (matches the doc's worked example), Y(0, ·) = 0.0661 and
  Y(48 h, 20 °C) = 0.99992 (saturation, see finding 5).

**Science check.**

- Gubler-Thomas: the band of 70-85 °F, ≥ 6 continuous hours, 3 consecutive days for onset,
  +20 / −10, −10 for ≥ 95 °F during 15 min, the bounds of 0-100 and the classes 0-30 / 40-50 /
  60-100 agree with the UC IPM description as I know it. The citation Gubler et al. (1999),
  *APSnet Features*, also matches my knowledge.
- Onset value 60: this is the common reading, and it is correctly marked `[to be verified]`.
  The same applies to "+20 and heat −10 on the same day" and to "stays active after 0". All
  three are flagged in the docs as interpretation, except for two sentences that present the
  reasoning as fact (finding 3).
- Values of 31-39 and 51-59 cannot occur with the default parameters (all steps are multiples
  of 10). With other parameters, `classify` maps them by lower bounds: 31-39 → low,
  51-59 → moderate. This is acceptable.
- Broome et al. (1995): the logit form, W (wetness duration, h) and T (mean temperature during
  wetness, °C) agree with the coefficients I know (−2.647866, −0.374927, 0.061601,
  −0.001511). They are still marked `[to be verified]`, which is fine. The RH ≥ 90 % proxy is
  documented honestly: it is a project default `[to be tuned]`, `estimated=True`, both bias
  directions are named, and Sentelhas et al. (2008) is cited. That citation is correct to my
  knowledge.
- Counting bridged dry spells in W is a project assumption, and it is stated as one.
- Downy mildew: the 3-10 rule (≥ 10 °C, ≥ 10 mm of rain in 24-48 h, shoots ≥ 10 cm; Baldacci
  1947, marked to be verified) is stated correctly. Rossi et al. (2008) is correctly described
  as a mechanistic primary-infection model driven by hourly rain, leaf wetness, T and RH.

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | src/sivin/analytics/disease/gubler_thomas.py:303 | An undetermined day carries the onset streak without limit, so "3 consecutive days" can span weeks of outage | fixed: `max_undetermined_carry_days` (default 1, [to be tuned]); test with the reviewer's example |
| minor | src/sivin/analytics/disease/powdery_mildew.py:409-419; docs/indices/powdery_mildew_gt.md:80 | A favourable run that crosses midnight is split per local day; the consequence is not documented | fixed: documented as a known limitation (interpretation 6); behaviour unchanged |
| minor | docs/indices/powdery_mildew_gt.md:66, :79 | Two unverified interpretations are justified with statements about "the rules"/"the sources" as if checked | fixed: both reworded as project interpretations [to be verified], also interpretation 3 |
| minor | src/sivin/analytics/disease/botrytis.py:423-435 | `details` grows by 4 keys per event without bound (hundreds per season) | fixed: summary keys plus the max-Y event; full list via `infection_events()`; contract field proposed under Out of scope |
| minor | docs/indices/botrytis_broome.md:131-133 | The fitted W/T range is not given; long RH ≥ 90 % periods saturate Y ≈ 1 | fixed: saturation documented; optional `max_wetness_h` cap (default None); test |
| nit | src/sivin/analytics/disease/botrytis.py:430 | `event_{number:03d}` breaks the lexical order beyond 999 events | moot: per-event keys removed |
| nit | docs/indices/downy_mildew.md:29 | "infection step ... depends on rain splash" mixes up dispersal (rain splash) and infection (leaf wetness) | fixed: dispersal and infection worded separately |
| nit | src/sivin/analytics/disease/powdery_mildew.py:488-495 | `value` (season maximum) and `classification` (last day) describe different days, so the web may show "100, low" | fixed: `classification` is the class of `value`; last day's class in `details["current_class"]` |

**Details and suggested fixes.**

1. **Outage carries the onset streak.**
   - Input: June 1 favourable, June 2-12 without samples, June 13 and 14 favourable.
   - Wrong behaviour: onset on June 14 at 60 points (class high). The literal rule needs 3
     consecutive days.
   - Once the index is active, a long outage also freezes it, for example at 100.
   - The `complete` flag and `n_undetermined_days` show the problem, but the curve itself
     looks normal.
   - Fix: add a parameter such as `max_carried_undetermined_days` (project default, e.g. 1-2).
     Beyond it, reset the streak while waiting, or mark the index as unknown or NaN while
     active. Document the parameter.
2. **Midnight split.**
   - Input: in the band 21:00-03:00 local.
   - Behaviour: two runs of about 3 h, so the day is not favourable.
   - The UC IPM rules are formulated per day, so this may be intended. However, the doc
     (interpretation 6) mentions only the few minutes that spill into the next day.
   - Fix: state the consequence explicitly in the doc. Optionally assign a run to the day on
     which it ends, or to the day that holds most of it. This is rare in South Moravia, which
     is why the finding is only minor.
3. **Wording.**
   - Line 66 says "The rules list both conditions separately", and line 79 says "a rule the
     sources do not state". The sources were not checked in this WP.
   - Fix: rephrase both as "in the descriptions known to us" and keep `[to be verified]`.
4. **Flattened `details`.**
   - With `min_event_duration_h = 0`, every night with a single sample at RH ≥ 90 % is an
     event. A humid South Moravian season can yield 100+ events and 400+ keys per sensor and
     year. The site contract (§2.6) does not use `details` today, so this is not a blocker.
   - The workaround is acceptable for now.
   - Fix: keep summary keys in `details` (`n_events`, plus start, W, T and Y of the event with
     the maximum Y). Expose the full list only via `infection_events()` and the proposed
     contract field (already listed under *Out of scope*).
5. **Range of validity.**
   - The doc correctly calls W > 24 h an extrapolation.
   - It should also say that, with the proxy, multi-day fog or rain spells easily give
     W > 24 h. Y then saturates near 1. Example: W = 48 h at 20 °C gives Y = 0.9999.
   - Fix: add one sentence. Optionally add a configurable `max_wetness_h` cap, documented as a
     project choice.

**Deviations assessment.**

1. Gap semantics (nominal duration instead of the cap): agreed. It is more conservative than
   crediting the cap, and the run is correctly closed at the gap; verified by hand above.
2. Heat as a represented duration ≥ 15 min: agreed; it is equivalent at 30-min sampling and
   correct for denser sampling.
3. Undetermined days: the rule is reasonable and documented, but needs a limit (finding 1).
4. Onset 60, independent heat penalty, heat ignored before onset, and staying active: all are
   acceptable as documented `[to be verified]` choices and are raised as owner questions.
5. April 1 - October 31 period: acceptable as a configurable project default.
6. The curve starts at the first sample: acceptable.
7. W includes bridged interruptions, and a period is counted on its end date: acceptable and
   documented. Counting on the end date avoids the midnight split for Botrytis.
8. Value 0.0 without events, no classes by default: acceptable. The intercept caveat is
   documented.
9. RH-aware coverage helper: correct; the contract gap is noted under *Out of scope*.
10. Flattened events: acceptable as a stop-gap (finding 4).
