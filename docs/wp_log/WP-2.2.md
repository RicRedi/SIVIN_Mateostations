# WP-2.2 — Ripening quality and risk indices

## Summary

The new package `sivin.analytics.ripening` holds the eight indices of MIGRATION_PLAN §3.2. Each
is a `ClimateIndex` subclass registered under its plan id: `cool_night`, `dtr_ripening`,
`heat_hours`, `tropical_days_nights`, `frost`, `winter_freeze`, `dew_point` and `vpd`. Each
has a frozen pydantic parameter model with a description, unit and source for every field.
Hour-based metrics (`heat_hours`, `frost`, VPD hours) are duration-weighted by one reusable
class, `SampleDurations`. Each sample stands for the time until the next sample, capped, and an
interval that crosses local midnight is split there. This fixes the legacy
`frost_events_count` row-count bug: `frost` returns hours. Dew point (Magnus,
Alduchov & Eskridge 1996, legacy coefficients configurable) and VPD (FAO-56) are pure functions.
Every index has a `docs/indices/<id>.md` page.

## Changed files

- Package: `src/sivin/analytics/ripening/`
  - `__init__.py`: registers the indices on import and re-exports them.
  - `params.py`: `MonthDayValue`, `PeriodParams`, `SampleDurationParams`.
  - `durations.py`: `SampleDurations`, `masked_values`.
  - `psychrometry.py`: `dew_point_c`, `non_positive_humidity`,
    `saturation_vapour_pressure_kpa`, `vapour_pressure_deficit_kpa`, `MagnusCoefficients`.
  - `thresholds.py`: `Comparison`, `Threshold`, `UpperBoundClasses`.
  - `common.py`: `RipeningIndex` base, `nan_to_none`.
  - One module per index: `cool_night.py`, `dtr.py`, `heat_hours.py`,
    `characteristic_days.py`, `frost.py`, `winter_freeze.py`, `dew_point.py`, `vpd.py`.
- Tests: `tests/analytics/ripening/{conftest,test_formulas,test_durations,test_daily_indices,test_hour_indices}.py`.
- Docs: `docs/indices/{cool_night,dtr_ripening,heat_hours,tropical_days_nights,frost,winter_freeze,dew_point,vpd}.md`,
  `docs/wp_log/WP-2.2.md`.

### Public API

```python
# sivin.analytics.ripening (importing it registers the 8 indices)
CoolNightIndex / CoolNightParams              # "cool_night", °C, classes very_cool/cool/temperate/warm_nights
DtrRipeningIndex / DtrRipeningParams          # "dtr_ripening", °C; params.start_date (e.g. véraison), .window(year)
HeatHoursIndex / HeatHoursParams              # "heat_hours", h; .band_hours(ctx, selection) -> DataFrame
CharacteristicDaysIndex / CharacteristicDaysParams / DayCategory   # "tropical_days_nights", d
FrostIndex / FrostParams                      # "frost", h; params.after_date (e.g. budburst) -> critical_*
WinterFreezeIndex / WinterFreezeParams        # "winter_freeze", d; winter ending in ctx.year
DewPointIndex / DewPointParams                # "dew_point", °C
VpdIndex / VpdParams                          # "vpd", kPa
SampleDurations(params: SampleDurationParams, timezone)
    .durations_s(series) / .pieces(series, values) / .hours_by_day(series, values, condition, days=None)
    .sum_hours(pieces, condition, days=None)  # staticmethod
masked_values(series, column, exclude_mask) -> ndarray (NaN where excluded/missing)
dew_point_c(temp_c, rh_pct, coefficients=ALDUCHOV_ESKRIDGE_1996); LEGACY_MAGNUS; MagnusCoefficients
saturation_vapour_pressure_kpa(temp_c); vapour_pressure_deficit_kpa(temp_c, rh_pct)
```

### Common behaviour of all eight indices

- Days are the complete local days from `ClimateIndex._season_days`.
  `dew_point` and `vpd` also require `rh_coverage >= min_daily_coverage`
  (`RipeningIndex._with_complete_humidity`), because `complete_days()` checks temperature only.
- `coverage` and `complete` come from that selection.
- `value` is `None` when there is no usable day.
- `details["n_days"]` is always set, and `daily` is a per-day series where meaningful.
- No index uses a proxy, so `estimated` is `False` everywhere.

## How it was verified

All commands were run in `/home/user/wt/wp-2.2` with a uv venv: Python 3.12, pandas 3.0.6,
numpy 2.5.3, pydantic 2.13.5, ruff 0.16.10, mypy 2.4.0.

- `make lint` → `All checks passed!`, `51 files already formatted`.
- `make type` → `Success: no issues found in 34 source files`.
- `make test` → `268 passed` (87 of them in `tests/analytics/ripening`).
- `make cov` → `TOTAL 1449 0 250 1 99%`, `Total coverage: 99.94%`.
  - Ripening package: every module at 100 % except `vpd.py` at 99 %. The one partial branch is
    a configured daytime window that contains no samples.
- Hand-computed checks (the arithmetic is in the test comments):
  - Dew point: 20 °C / 50 % → 9.2611 °C (Alduchov & Eskridge) and 9.2543 °C (legacy
    coefficients). At RH = 100 %, $T_d = T$.
  - $e_s(20) = 2.3383$ kPa and VPD(30 °C, 20 %) = 3.3945 kPa.
  - Cool Night Index: mean of 10, 13 and 16 °C → 13.0 → `cool_nights`.
  - DTR: 9.333 °C on the fixed window, 9.0 °C from an explicit start date.
  - Heat hours: 8 / 6 / 2 h for the optimum, heat-stress and extreme bands.
  - Frost: 8 h frost, 2 h hard frost, 2 frost nights; critical after Apr 15: 2 h.
  - Characteristic days: 2 / 1 / 3 / 2 / 1.
  - Winter freeze: 2 damage days and 1 severe day over 151 days.
- Acceptance:
  - `frost` returns hours, not rows (`test_returns_hours_not_rows`): 12 rows → 6 h.
  - Irregular sampling does not change hour results (`test_irregular_sampling_*` in
    `test_durations.py` and `test_hour_indices.py`).
  - The 25 h fall-back day gives 25 observed hours.
- Every index is tested on an empty series and on data outside its period: value `None`,
  coverage 0, not complete.
- Coordinator request: a whole day without humidity is not used by `dew_point` or `vpd`
  (`test_day_without_humidity_is_not_used` in both classes).

## What did not work / what was not verified

- No real sensor data were used; every test value is synthetic.
- No DOI is given; every reference is marked `[DOI not verified]` (doi.org is not reachable).
- **Cool Night Index classes:** I am confident of the boundaries 12 / 14 / 18 °C from Tonietto
  & Carbonneau (2004). Which side of each boundary is inclusive is `[to be verified]` against
  the original table. The code assigns a value on a boundary to the cooler class.
- **Thresholds not checked against their sources** (`[to be verified]`):
  - `heat_hours`: 20–30 °C, > 30 °C and > 35 °C come from plan §3.2. I did not check them
    against Mori et al. (2007) or Greer & Weedon (2012); those papers are cited as background
    only.
  - `frost`: the hard-frost threshold of −2 °C is a plan value. I copied no stage-specific
    critical temperatures from Poling (2008).
  - `winter_freeze`: −15 / −20 °C are plan values; Zabadal et al. (2007) is background, and
    its author list is still marked unverified.
- **ČHMÚ source document:** I cite no specific ČHMÚ document for the characteristic-day
  definitions (30 / 20 / 25 / 0 / 0 °C), and mark the source `[to be verified]`.
- **Project defaults without literature** (`[to be tuned]`):
  - VPD threshold 2.0 kPa.
  - `max_sample_duration_s` 3650 s (2 × 1825 s).
  - DTR window Aug 1 – Sep 30.
  - Period Apr 1 – Oct 31 for `frost`, `dew_point` and `vpd`.
  - Dormant season Nov 1 – Mar 31.
- Parity of `tropical_days_nights` with the legacy `calculate_tropical_extremes` was not
  checked by running the legacy code. The definitions are the same (≥ 30 / ≥ 20 °C on
  calendar-day extremes), but `DailyWeather` uses local Europe/Prague days and only complete
  days count.

## Decisions and deviations

1. **Duration model:** samples are read as a zero-order hold.
   - Sample *i* lasts `min(t_{i+1} − t_i, max_sample_duration_s)`.
   - The last sample of the series lasts `min(last_sample_duration_s, max)`.
   - Durations are taken over all rows, so an excluded or missing value leaves its own
     interval uncounted and does not stretch its predecessor.
   - Intervals are split at local midnight. Because `max_sample_duration_s` is limited to 6 h,
     an interval crosses at most one midnight.
2. **Hour metrics count complete days only.** This applies `min_daily_coverage` the same way as
   the daily indices. Partial days do not contribute hours.
3. **Headline value of the multi-figure indices:**

   | Index | `value` | Other figures in `details` |
   |---|---|---|
   | `heat_hours` | heat-stress hours (> 30 °C) | other bands |
   | `tropical_days_nights` | number of tropical days | other counts |
   | `frost` | frost hours ≤ 0 °C over the whole period | `critical_*` from `after_date` |
   | `vpd` | mean daily maximum VPD | hours above threshold, optional daytime mean |
   | `dew_point` | mean of daily mean dew points | mean depression |
4. **`winter_freeze` crosses New Year with two `Season`s.** One is the previous year's
   `dormant_start`..Dec 31, selected with `_season_days` on `replace(ctx, year=year-1)`. The
   other is Jan 1..`dormant_end` of the season year. Season *N* means the winter that ends in
   year *N*.
5. **`dtr_ripening.start_date`:** an explicit date replaces only the start; the end stays
   `period_end`. The date must lie in `ctx.year`, otherwise `ValueError`. Because a start date
   belongs to one season, the integration creates one instance per season.
6. **`frost` period** defaults to the growing season, Apr 1 – Oct 31. Earlier spring frosts
   after an unusually early budburst would need `period_start` moved earlier.
7. **Month-day parameters** are `MonthDay` values. They accept `"MM-DD"` strings and
   `{month, day}` mappings, and serialise back to `"MM-DD"`.
8. **RH edge cases:**
   - `RH <= 0` gives no dew point (`NaN`), is counted in `n_rh_non_positive` and logged as a
     warning.
   - `RH < 0` gives a `NaN` VPD.
   - `RH > 100 %` passes through unchanged and gives a negative VPD.
9. **No `ThermalTimeModel`:** none of the eight indices accumulates thermal time, so the class
   suggested in the common rules was not needed here.

## Out of scope

- **`SampleDurations` should move to `sivin.core`** (e.g. `sivin.core.durations`). WP-2.3
  (Gubler-Thomas, Broome) is expected to carry its own copy until integration. Merging them is
  a contract change for the owner or WP-1.7.
- **Day completeness for humidity indices:** `DailyWeather.complete_days()` and
  `ClimateIndex._season_days` look at temperature coverage only. This WP filters
  `rh_coverage` inside the package. A `variables=("temp", "rh")` option on `_season_days`
  would serve WP-2.3 too.
- **`Season` cannot cross New Year.** A `Season.crossing_new_year` or a `DateWindow` value
  object in `sivin.core.season` would replace the workaround in `winter_freeze`.
- **`ThresholdClassifier` duplication:** WP-2.1 is building its own classification helpers
  (`thermal/classification.py`). `UpperBoundClasses` here could be unified with them later.
- **No legacy changes:** `vineyard_analyst.py` (`frost_events_count`, the 0.0001 RH
  replacement) is untouched. Its replacement is planned for WP-5.2.

## Open questions for the owner

1. **Proposed configuration for WP-1.7:** a section `analytics.indices.<index_id>` with the
   parameter models of this package (e.g. `analytics.indices.frost.after_date`,
   `analytics.indices.heat_hours.sampling.max_sample_duration_s`), created through
   `index_registry.create(index_id, params)`. A possible CLI command is
   `sivin indices --season 2026 [--index frost]`.
2. **Modelled dates from WP-2.1:** should the integration pass the modelled véraison
   (`gfv`) as `dtr_ripening.start_date` and the modelled budburst as `frost.after_date` per
   sensor and season?
3. **Project defaults to confirm or tune:**
   - VPD threshold (2.0 kPa).
   - Frost period (growing season).
   - DTR window (Aug 1 – Sep 30).
   - `max_sample_duration_s` (3650 s).
4. **Headline value for the web cards:** is the `value` chosen for each multi-figure index
   right (see decision 3)?
5. **Contract additions** (WP-0.1 contracts, not changed here):
   - `SampleDurations` in core.
   - Humidity-aware `_season_days`.
   - A season type that crosses New Year.

## Review

Verdict: APPROVE (round 1)

Reviewer: independent review session. Every number below was run or computed by hand in this
review; scripts are in `/tmp/claude-0/review-2.2/` (outside the repo).

**Gates (run by the reviewer in `/home/user/wt/wp-2.2`):**
- `make lint type test`: lint clean, mypy strict clean, `268 passed`.
- `make cov`: `TOTAL 1449 0 250 1 99%`, `Total coverage: 99.94%`. Every ripening module is at
  100 % except `vpd.py` at 99 % (partial branch 137->139).

**Scope:** `git diff --stat bcde7d9...HEAD` touches only `src/sivin/analytics/ripening/**`,
`tests/analytics/ripening/**`, the eight `docs/indices/*.md` files of this WP and this note.
No shared file is changed. There are no `type: ignore` comments in `src/`. The one in the tests
checks that a frozen model rejects assignment. There are no `print` calls.

**Science checks (against literature I know with certainty):**
- Cool Night Index (Tonietto & Carbonneau 2004, Agric. For. Meteorol. 124, 81–97):
  - The definition, the mean September T_min, is correct.
  - The classes are correct: CI+2 ≤ 12, CI+1 12–14, CI-1 14–18, CI-2 > 18 °C.
  - Putting a value on a boundary into the cooler class (`<=`) matches the usual reading of the
    table. Keeping it `[to be verified]` is still fine.
- Magnus form, Alduchov & Eskridge (1996): a = 17.625 and b = 243.04 °C are correct, and so is
  the dew-point inversion T_d = bγ/(a−γ).
- FAO-56 eq. 11: e_s = 0.6108·exp(17.27T/(T+237.3)) kPa is correct, and so is e_a = e_s·RH/100.
- ČHMÚ characteristic days are correct:
  - tropical day T_max ≥ 30 °C;
  - summer day T_max ≥ 25 °C;
  - frost day T_min < 0 °C;
  - ice day T_max < 0 °C;
  - tropical night T_min ≥ 20 °C.
  The calendar-day approximation for the tropical night is documented.
- Background citations:
  - The heat bands, frost thresholds and winter thresholds are presented correctly. Each is a
    "MIGRATION_PLAN §3.2 default", and the paper is labelled "background … `[to be verified]`".
    No number is attributed to a paper that might not contain it.
  - Poling (2008) is explicitly not used for numbers.
  - The bibliographic data of Mori et al. (2007), Greer & Weedon (2012), Poling (2008),
    Amerine & Winkler (1944) and Tonietto & Carbonneau (2004) match my knowledge.

**Hand recomputations (all match the code):**
- Dew point:
  - 20 °C / 50 %: γ = ln 0.5 + 17.625·20/263.04 = 0.646953, so T_d = 243.04·0.646953/16.978047 =
    9.2611 °C. The code gives 9.261107.
  - −10 °C / 80 %: γ = −0.223144 − 0.756308 = −0.979452, so T_d = −12.7951 °C. The code gives
    −12.795104.
- VPD:
  - e_s(30) = 0.6108·exp(1.938272) = 4.24357 kPa, so VPD at 20 % RH = 0.8·4.24357 = 3.39486 kPa.
    The code gives 3.394452.
  - e_s(20) = 2.33828 kPa matches the code.
- Frost hours with drifting 1826 s sampling (own synthetic night, 2026-04-12):
  - Six samples ≤ 0 °C give 6·1826/3600 = 3.04333 h. Two of them ≤ −2 °C give 1.01444 h.
  - The code gives 3.043333 h and 1.014444 h, with 1 frost night and a minimum of −2.5 °C.
  - With one of the six marked SPIKE, the hand value is 5·1826/3600 = 2.53611 h. The code gives
    2.536111 h.
- DST days with 1825 s sampling from local midnight to past the next midnight:
  - 2026-10-25 gives 25.0 h and 2026-03-29 gives 23.0 h (hand: 25 h and 23 h).
- `winter_freeze` over a leap-year winter (season 2024, 2023-11-01 … 2024-03-31):
  - n_period_days = 30+31+31+29+31 = 152, and the code reports n_days 152 with coverage 1.0.
  - A −16 °C sample on 2024-02-29 and a −21 °C sample on 2023-12-31 give 2 damage days and
    1 severe day.
  - The DST transitions inside the window do not matter, because the selection works on local
    `DailyWeather` days.

**`SampleDurations`: duration logic and comparison with the WP-2.3 copy
(`src/sivin/analytics/disease/sampling.py` on `wp/2.3-disease-models`).** This matters when the
two copies are unified.

| Aspect | WP-2.2 (this branch) | WP-2.3 |
|---|---|---|
| Step ≤ cap | step | step |
| Step > cap | **cap** (3650 s; the sample before a gap is stretched to the cap) | **nominal interval** (1825 s) |
| Default cap | 3650 s = 2·1825 | 4562.5 s = 2.5·1825 |
| Last sample | min(1825, cap) | 1825 |
| Cap validation | 0 < cap ≤ 6 h; cap < `last_sample_duration_s` is accepted silently | cap ≥ nominal |
| Split at local midnight | yes | no (runs only) |
| Excluded or missing row | interval uncounted (unknown), predecessor not stretched | same: durations measured on all rows; invalid samples end a run |
| Gap flag (`followed`) | none | yes; needed for runs |

Concrete differences:
- A step of 4000 s gives 3650 s here and 4000 s in WP-2.3.
- A step of 7200 s gives 3650 s here and 1825 s in WP-2.3.
- One missed sample with +2 s clock drift (step 3652 s) loses 2 s here and nothing in WP-2.3.

The QC interaction is correct and conservative. An excluded sample's own interval counts as
unknown and is not attributed to a neighbour (verified above: SPIKE gives 5 samples, not 6).
The midnight split is correct (verified by the tests and the DST runs).

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | `src/sivin/analytics/ripening/durations.py:113` | **Cap semantics differ from WP-2.3.** A sample followed by a gap longer than the cap is stretched to the full cap (3650 s), while WP-2.3 counts only the nominal 1825 s. Example: a sensor stops after a −1 °C sample at 02:00 and the next sample comes at 08:00. This gives 1.01 h of frost here and 0.51 h in WP-2.3. The default cap of exactly 2×1825 s also clips one missed sample by the clock drift. **Fix:** keep the code now; when unifying in core, choose one rule. I recommend WP-2.3's rule: gap → nominal interval, with a cap of about 2.5× nominal. | open |
| minor | `src/sivin/analytics/ripening/frost.py:103,114` | **Inconsistent frost-day threshold.** A "frost night" in `frost` is `T_min <= 0`, while the ČHMÚ "frost day" in `tropical_days_nights` is `T_min < 0`. Example: a day with T_min = 0.0 °C counts as a frost night but not as a frost day. Both are documented, but the two cards will disagree. **Fix:** use `<` (ČHMÚ) for nights, or state the difference on both doc pages. | open |
| minor | `src/sivin/analytics/ripening/frost.py:124` | **`after_date` is not checked against `ctx.year`** (`dtr_ripening.start_date` is). Example: `after_date=2025-04-15` with season 2026 silently makes the whole 2026 period critical. **Fix:** raise `ValueError` as `DtrRipeningParams.window` does. | open |
| minor | `src/sivin/analytics/ripening/dew_point.py:120` | **`NaN` in `details` when no sample gives a dew point.** When every RH on the complete days is ≤ 0, `value` is `None` but `details["mean_depression_c"]` is `NaN`. Verified with 24 samples at RH = 0. Plain `json.dumps` writes `NaN`, which is invalid JSON for the web. **Fix:** apply `nan_to_none` or omit the key. | open |
| minor | `src/sivin/analytics/ripening/psychrometry.py:153` | **RH = 0 is handled inconsistently.** The dew point treats RH ≤ 0 as a sensor error (`NaN` plus a count), but VPD accepts RH = 0 and gives VPD = e_s. Example: 24 samples at 20 °C / 0 % give a VPD index of 2.338 kPa and 23.5 h above the threshold, from what the dew-point index calls an error. **Fix:** use `rh > 0` in both, or document why VPD differs. | open |
| minor | `src/sivin/analytics/ripening/dew_point.py:105`, `vpd.py:158` | **Daily dew-point means and the VPD daytime mean are not duration-weighted.** They are arithmetic sample means, so with irregular sampling a dense stretch weighs more. The effect is small at ~1825 s and is consistent with `DailyWeather`. **Fix:** document it, or weight by `SampleDurations` pieces. | open |
| minor | `src/sivin/analytics/ripening/winter_freeze.py:117` | **Needs data from the previous autumn.** The index reads the previous autumn from `ctx.daily`. If the integration (WP-1.7) builds the context from season-year data only, the autumn part is silently empty: coverage 90/151, `complete=False`. The `IndexContext` docstring says "all available days", so this is correct today. **Fix:** mention it in the WP-1.7 open questions. | open |
| nit | `src/sivin/analytics/ripening/*.py` | Nine modules define `logger`, but only `dew_point.py` uses it. | open |
| nit | `src/sivin/analytics/ripening/params.py:101` | `last_sample_duration_s` may exceed `max_sample_duration_s` and is then capped silently. A validator would make this explicit. | open |

**Headline `value` for web cards:**
- These are sensible: `heat_hours` = hours > 30 °C, `tropical_days_nights` = tropical days,
  `vpd` = mean daily maximum, and `dew_point` = mean dew point (low information but harmless).
- `frost` is questionable. Its value is the frost hours over the whole April–October period, so
  October frosts after harvest count as much as a frost in May. Once `after_date` (modelled
  budburst) is passed, `critical_frost_h` is the risk figure a grower wants on the card.
- Suggestion for the owner (Open question 4): with `after_date` set, make `critical_frost_h` the
  headline, or let the web card show it.

**Deviations assessment:**
1. Duration model (zero-order hold, cap, midnight split, excluded rows not stretched): sound.
   The difference from WP-2.3 is described above.
2. Hour metrics on complete days only: consistent with the daily indices. Accepted. A complete
   day can still miss up to 10 % of its time, which is not rescaled. That is acceptable but
   could be documented.
3. Headline values: acceptable. See the `frost` remark above.
4. `winter_freeze` as the winter ending in the season year, built from two `Season`s: correct,
   including leap years (verified for 152 days). DST does not affect it.
5. `dtr_ripening.start_date` replaces only the start and must lie in `ctx.year`: accepted.
6. `frost` period Apr–Oct: acceptable for South Moravia. It is `[to be tuned]`.
7. `MonthDayValue` serialisation: accepted.
8. RH edge cases: documented. See the RH = 0 inconsistency above.
9. No `ThermalTimeModel`: justified, because no index here accumulates thermal time.

**Tests:** hand-computed and meaningful. The irregular-sampling tests place samples exactly on
the band transitions. That proves invariance under the zero-order-hold definition, which is what
the acceptance criterion requires. My own drifting-sampling and DST runs confirm it.
