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

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
