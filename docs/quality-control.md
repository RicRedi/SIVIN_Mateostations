# Quality control and transition detection

Package `sivin.quality` (WP-1.5, WP-1.8) checks the measurements of one sensor, sets
[`QcFlag`](../src/sivin/core/flags.py) bits in the `qc` column and reports events (off-site
periods, gaps, steps, warnings). The binding design is
[MIGRATION_PLAN.md §2.7](../MIGRATION_PLAN.md#27-kvalita-dat-validace-vstupu-párování-a-přechody)
and [§2.8](../MIGRATION_PLAN.md#28-log-mimo-vinici-sensorsoffsite_logyaml).

**Source of truth for `PRE_DEPLOYMENT` (owner decision of 2026-10-05):** the hand-maintained
[off-site log](sensors.md#off-site-log) `sensors/offsite_log.yaml`. By default every sensor is
assumed to measure in the vineyard; samples inside a logged period get `PRE_DEPLOYMENT`. The
deployment detector still runs, but by default only in **advisory** mode: it warns about
indoor-like periods the log does not cover and sets no flags. Its flagging behaviour (WP-1.5)
is available with `deployment.mode: enforce`.

All numeric thresholds below are **project defaults for ~30 min data, not values quoted from
literature**, unless the table says otherwise. They are marked *[to be tuned]* and must be
checked against real data once it is available (owner questions Q1–Q3). The methodology of the
range, step (rate-of-change) and persistence tests follows Zahumenský (2004).

## Contents

- [Flags and events](#flags-and-events)
- [Pipeline order](#pipeline-order)
- [Off-site log](#off-site-log)
- [Checks](#checks)
- [Deployment detection](#deployment-detection)
- [Configuration](#configuration)
- [Limitations](#limitations)
- [Implementation](#implementation)
- [References](#references)

## Flags and events

| Flag | Set by | Excluded from indices by default |
|---|---|---|
| `MISSING` (1) | `missing` | yes |
| `OUT_OF_RANGE` (2) | `range` | yes |
| `SPIKE` (4) | `spike` | yes |
| `STEP` (8) | `step` | no (informative) |
| `STUCK` (16) | `persistence` | yes |
| `PRE_DEPLOYMENT` (32) | off-site log (`OffSiteCheck`); the detector only in `enforce` mode | yes |
| `TIMESTAMP_SUSPECT` (128) | `sampling` (also set by the parsers for DST, WP-1.2) | no |

`NEIGHBOR_OUTLIER` (64) needs the sensor alignment of WP-1.6 and `MANUAL_EXCLUDE` (256) is set
by the owner; neither is produced here. Existing flags of the input are kept (all flags are
OR-ed).

Events (`QualityEvent`, `DeploymentEvent`) carry `kind`, `t_utc`, `detail`, `severity`
(`info`/`warning`), `source` (`detected`/`registry`/`log`), an optional `confidence` (0–1) and,
for intervals, `end_utc`. Kinds: `deployment`, `retrieval`, `step`, `gap`,
`irregular_sampling`, `non_positive_interval`, `deployment_mismatch`,
`unconfirmed_transition`, `off_site`, `unlogged_off_site`. `deployment`, `retrieval`, `step`
and `off_site` are the `type` values of the site contract (`events/<id>.json`, plan §2.6,
§2.8); an `off_site` event is an interval `[t_utc, end_utc)` with `end_utc = None` while the
sensor is still off site (`t_end: null` on the web).

**`confidence` is a heuristic evidence score, not a calibrated probability.** For a detected
transition it is the share of the relative criteria that hold (see
[Relative confirmation](#4-relative-confirmation)); for a registry event it is 1. Read it as
"how many independent signs agree", not as "probability that the event is real". The field
keeps the name of the site contract.

The `qc` field is one bit field per row (frozen contract, plan §2.5). A finding in humidity
therefore flags the whole row, temperature included; see [Limitations](#limitations).

## Pipeline order

`QualityPipeline.from_settings(settings, off_site_log=log)` builds the pipeline;
`run(series, known_deployments=())` runs four stages and a final set-aside:

1. **Screening checks on the whole series** — default `missing`, `sampling`, `range`,
   `precip_range`, `precip_counter`, `battery` (the last three since WP-1.7, report events
   only, see [Precipitation and battery](#precipitation-and-battery-wp-19-events-never-row-flags)). These are
   wrong wherever the sensor is. Their `MISSING` and `OUT_OF_RANGE` flags are passed on, so the
   detector ignores a gross error (e.g. a −999 sentinel) instead of seeing a regime change.
2. **Off-site log** (if the pipeline has one) — `PRE_DEPLOYMENT` on every sample inside a logged
   period and one `off_site` event per period ([Off-site log](#off-site-log)).
3. **Deployment detection on the whole series** — in the default `advisory` mode only
   `unlogged_off_site` / `unconfirmed_transition` warnings; in `enforce` mode
   `deployment`/`retrieval` events and `PRE_DEPLOYMENT` for every sample detected indoors
   (combined with the log's flags).
4. **Deployed checks on every continuous stretch without `PRE_DEPLOYMENT`** — default `spike`,
   `step`, `persistence`. Off-site data are not judged by outdoor expectations (a stable office
   temperature is not "stuck"), and the jump at a logged period's boundary is never reported as
   a spike or a step, because no stretch spans it.

5. **Set-aside** (WP-1.7) — every enabled check that implements `set_aside` (protocol
   `ValueSetAside`; today `precip_range`) replaces the values it rejects by `NaN` in
   `QualityResult.series`; `QualityResult.values_set_aside` counts them. Rows and flags are
   unchanged, so daily sums and the site export never see an implausible precipitation value.

Without a log entry and with the advisory detector, an office stay counts as vineyard data: its
boundaries are typically reported as `step` (informative, not excluded) next to the
`unlogged_off_site` warning. With `detect_deployment: false` only the log decides.

## Off-site log

`OffSiteCheck` (`sivin/quality/checks/offsite.py`) receives the validated `OffSiteLog`
(package `sivin/registry/offsite/`, format and validation in [sensors.md](sensors.md#off-site-log)).
It flags a sample `PRE_DEPLOYMENT` exactly when `from <= t < to` for one of its sensor's
periods (`to = null`: until further notice); local times of the log are converted to UTC when
the log is loaded, so a period across a daylight-saving change flags exactly the right samples.
Every period that overlaps `[first sample, last sample]` of the series becomes one `off_site`
event (source `log`, `detail` = `"<reason>: <note>"`) with the period's own bounds, also when it
starts before the series. The check is not in `check_registry`, because it needs the log as a
collaborator; the pipeline creates it.

The result (`QualityResult`) holds the flagged series, all events in time order, the number of
rows per single flag (`flag_counts`) and the detector details (segments, regimes, features).

## Checks

Every check is a subclass of `QualityCheck` registered under a name in `check_registry`; its
settings are a frozen pydantic model (`extra="forbid"`). A new check is a new registered class.
All checks use the real timestamps of the series; they never assume a regular grid. `NaN`
values are skipped by every check except `missing`.

Notation: $x_i$ value, $t_i$ time of sample $i$ (s), $\Delta t_i = t_i - t_{i-1}$,
$\Delta t_0$ the nominal interval (`time.expected_interval_s`, 1830 s).

### `missing` — missing values → `MISSING`

A row is missing if **any** checked variable is `NaN` (`rule: any`, default) or if **all** are
(`rule: all`).

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `variables` | `[temp_c, rh_pct]` | — | both measured variables |
| `rule` | `any` | — | owner decision 2026-10-05 (whole-row validity): if one variable is missing, the whole measurement is invalid |

### `range` — plausible values → `OUT_OF_RANGE`

Temperature is flagged outside $[\max(T^{phys}_{min}, T^{clim}_{min}),\ \min(T^{phys}_{max},
T^{clim}_{max})]$, humidity outside $[h_{min}, h_{max}]$. A climatological limit set to `null`
falls back to the physical one.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `temp_physical_min_c` / `temp_physical_max_c` | −50 / 60 | °C | project default *[to be verified against the sensor data sheet]* |
| `temp_climate_min_c` / `temp_climate_max_c` | −30 / 42 | °C | project default for South Moravia *[to be verified against station records]* |
| `rh_min_pct` / `rh_max_pct` | 0 / 100 | % | physical limits of relative humidity |

`range` checks temperature and humidity only; precipitation and battery voltage have their own
checks below.

### Precipitation and battery (WP-1.9): events, never row flags

Since owner decision Q9 (2026-10-05) a series also carries `precip_mm` (precipitation in the
interval since the previous sample), `precip_total_mm` (the device's cumulative counter) and
`battery_v`. The row validity rule concerns temperature and humidity only, so **a problem in
one of these columns must not invalidate the temperature and humidity of its row**. A
`QcFlag` cannot express that: the `qc` field is one bit field per row (frozen contract,
plan §2.5) and every excluding flag (`OUT_OF_RANGE`, …) removes the whole row from indices
and charts. The three checks therefore **never set flags** (their `CheckOutcome.flags` are all
zero) and report events instead:

| Check | Event kind | Severity | Effect on the data |
|---|---|---|---|
| `precip_range` | `precip_out_of_range` | warning | `QualityPipeline` applies `PrecipRangeCheck.set_aside` (WP-1.7): exactly those `precip_mm` values become `NaN` in `QualityResult.series`; the event text only says that temperature and humidity are unaffected |
| `precip_counter` | `precip_counter_reset` | info | none |
| `precip_counter` | `precip_counter_mismatch` | warning | none (which of the two columns is wrong cannot be told) |
| `battery` | `low_battery` | warning | none |

**Why set-aside values and not a new flag or a per-column flag.** A new `QcFlag` bit that is
not in the exclusion mask would keep temperature and humidity valid, but every consumer of
`precip_mm` would then have to remember to mask it, and the flag set is a frozen contract.
Replacing only the implausible precipitation value by `NaN`
(`MeasurementSeries.with_values`, allowed for auxiliary columns only) keeps the row and its
flags untouched, needs no contract change and makes every later consumer (daily sum, web)
correct without knowing about the check; the event records what was removed. Temperature and
humidity are never replaced, only flagged. Since WP-1.7 `QualityPipeline` applies `set_aside`
of every enabled check that has one, after all flags are set (stage 5 of
[Pipeline order](#pipeline-order)).

Runs: consecutive affected samples form one event from the first to the last of them
(`end_utc`); samples without a value in that column neither end nor extend a run
(`runs_of`).

#### `precip_range` — implausible precipitation per interval

A present `precip_mm` outside $[P_{min}, P_{max}]$ is implausible.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `precip_min_mm` | 0 | mm | physical limit: an amount of precipitation cannot be negative |
| `precip_max_mm` | 50 | mm per sample interval (nominal 1830 s) | project default *[to be tuned]*; far above the largest value of the first real export (0.9 mm), meant to catch device or transfer errors, not heavy rain; not from literature |

#### `precip_counter` — interval values against the cumulative counter

In the first real export (sensor 77799986, plan §0.6.1) the interval value of a sample equals
the counter increase since the previous sample, up to 0.1 mm: e.g. the lines
`2025-12-19 13:36:46;…;0,0;323,6;…` and `2025-12-19 14:07:16;…;0,3;324,0;…` give an interval
value of 0.3 mm and an increase of 0.4 mm (both columns have 0.1 mm resolution). With
$\Delta C_i = C_i - C_{j}$, where $C_j$ is the previous present counter value:

- **reset** if $\Delta C_i < -\varepsilon$: `precip_counter_reset` (info), not an error;
  that step is not compared;
- **compared** if the previous row has a counter value, $t_i - t_{i-1} \le \Delta t_{max}$,
  $p_i$ and $C_i$ are present and the step is no reset;
- **mismatch** if compared and $|p_i - \Delta C_i| > \varepsilon$.

After a longer gap the counter also contains the precipitation of the missing samples, so such
steps are not compared. The 139-day gap of the real export changes the counter by 0 mm.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `tolerance_mm` ($\varepsilon$) | 0.15 | mm | 0.1 mm export resolution plus margin; differences of 0.1 mm occur in the real export; project default *[to be tuned]* |
| `max_interval_s` ($\Delta t_{max}$) | 2745 | s | 1.5 × the nominal interval of 1830 s (one regular step with jitter); project default *[to be tuned]* |

With these defaults the real excerpt `tests/fixtures/exports/real/` gives no event; with
$\varepsilon$ = 0.05 mm it gives exactly the 0.1 mm difference above (tested).

#### `battery` — low battery

A present `battery_v` below `low_battery_v` is a low reading. With 0.1 V resolution and daily
temperature swings, a battery near the threshold flaps (3.3 ↔ 3.2 V), so the check uses
**hysteresis** (`low_battery_episodes`): an episode starts at the first low reading and ends
only at a reading of at least `low_battery_v + recovery_margin_v` (3.4 V by default); readings
in between keep it open. Each episode gives one `low_battery` warning from its first to its last
low reading, with their number and the lowest voltage. A low battery says nothing about the
measurement of that moment, so nothing is flagged or removed.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `low_battery_v` | 3.3 | V | project default *[to be tuned]*; the real export reads 3.0–3.7 V (3.0 V in its two oldest lines, which gives one event); the voltage at which the device stops measuring is unknown *[to be verified against the device data sheet]* |
| `recovery_margin_v` | 0.1 | V | one step of the export resolution, so a reading that only returns to the threshold does not end an episode; project default *[to be tuned]*; 0 disables the hysteresis |

#### Wiring (WP-1.7)

The three checks are in the default `quality.screening_checks` since WP-1.7, and the pipeline
applies the set-aside of `precip_range` (see [Pipeline order](#pipeline-order)). Their
settings are `quality.check_settings.precip_range`, `.precip_counter` and `.battery` in
`config/sivin.yaml` (see [configuration.md](configuration.md)). Enabling them changes no flag of
any row (tested in `tests/quality/test_precip_battery.py`).

Implementation: `sivin/quality/checks/precip.py` (`PrecipRangeCheck`, `PrecipCounterCheck`,
`CounterSteps`), `sivin/quality/checks/battery.py` (`BatteryCheck`), `runs_of` in
`sivin/quality/checks/range_check.py`; tests in `tests/quality/test_precip_battery.py`.

### `spike` — isolated departure that returns → `SPIKE`

With $d^- = x_i - x_{i-1}$, $d^+ = x_{i+1} - x_i$ (previous and next *valid* samples), rate
limit $r$ and $\tau^\pm = \max(\Delta t^\pm, \Delta t_{min})$ in hours, sample $i$ is a spike if

$$
d^- d^+ < 0, \qquad |d^-| > r\,\tau^-, \qquad |d^+| > r\,\tau^+, \qquad \Delta t^\pm \le \Delta t_{max}.
$$

The threshold grows with the actual interval, so a longer interval tolerates a larger change;
$\Delta t_{min}$ keeps closely spaced samples from getting a tiny threshold, and a neighbour more
than $\Delta t_{max}$ away cannot confirm a spike. A row gets `SPIKE` if either variable spikes.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `temp_max_rate_c_per_h` | 8 (≈ 4.07 °C per 1830 s) | °C/h | project default *[to be tuned]*; method Zahumenský (2004) |
| `rh_max_rate_pct_per_h` | 40 (≈ 20.3 % per 1830 s) | %/h | project default *[to be tuned]* |
| `min_interval_s` | 1830 | s | nominal interval; follows `time.expected_interval_s` unless set (WP-1.7) |
| `max_interval_s` | 5490 | s | project default, 3 × nominal interval |

### `step` — sudden persistent level shift → `STEP` + `step` event

For consecutive valid samples with $|x_k - x_{k-1}| \ge J$ and $\Delta t_k \le \Delta t_{max}$,
let $m^-$ be the median over $[t_{k-1} - W, t_{k-1}]$ and $m^+$ over $[t_k, t_k + W]$ (each
needs at least `min_window_samples`). Sample $k$ is a step if

$$
\operatorname{sign}(m^+ - m^-) = \operatorname{sign}(x_k - x_{k-1}), \qquad
|m^+ - m^-| \ge f\,|x_k - x_{k-1}|, \qquad
|x_{k-1} - x_{k-2}|,\ |x_{k+1} - x_k| \le a\,|x_k - x_{k-1}|.
$$

A spike returns, so its medians agree and it is not a step. A sensor step happens within one
interval; a weather front spreads over several, so the last condition (neighbouring intervals
change by at most a share $a$ of the jump) keeps fronts such as −10 °C within 1 h (two jumps of
about −5 °C) unflagged. A gradual change (−8 °C in 2 h) has small single-interval jumps and is
not examined at all. **Known limitation:** a front faster than one sampling interval (≥ 5 °C
within one 1830 s interval) cannot be told from a sensor step and is flagged `STEP`; the flag is
informative and does not exclude data.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `temp_min_jump_c` | 5 | °C | project default *[to be tuned]* |
| `rh_min_jump_pct` | 25 | % | project default *[to be tuned]* |
| `window_s` | 10 800 (3 h) | s | project default |
| `min_window_samples` | 3 | count | project default |
| `persistence_fraction` | 0.5 | — | project default |
| `max_adjacent_fraction` | 0.4 | — | project default |
| `max_interval_s` | 5490 | s | project default, 3 × nominal interval |

### `persistence` — unchanged value → `STUCK`

Valid values are scanned left to right; a run grows while $\max - \min \le \varepsilon$. A run
whose first and last samples are at least $D$ apart gets `STUCK` on all its samples — unless at
least `saturation_share` of the run's samples have a relative humidity at or above
`rh_saturation_pct`. In fog or a temperature inversion both readings legitimately stay constant
for many hours, so the exemption applies to temperature runs too. The temperature duration is
12 h, longer than a calm isothermal night.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `temp_tolerance_c` | 0.05 | °C | half of an assumed 0.1 °C resolution *[to be verified]* |
| `temp_min_duration_s` | 43 200 (12 h) | s | project default *[to be tuned]*; method Zahumenský (2004) |
| `rh_tolerance_pct` | 0.5 | % | half of an assumed 1 % resolution *[to be verified]* |
| `rh_min_duration_s` | 43 200 (12 h) | s | project default *[to be tuned]* |
| `rh_saturation_pct` | 97 | % | project default; `null` disables the exemption |
| `saturation_share` | 0.5 | — | project default |

### `sampling` — gaps and irregular intervals → `TIMESTAMP_SUSPECT` + events

Each interval $\Delta t_i$ is

- **non-positive** if $\Delta t_i \le 0$ (impossible in a valid `MeasurementSeries`; checked
  for raw arrays by `classify_intervals`),
- a **gap** if $\Delta t_i > k\,\Delta t_0$ → `gap` event from $t_{i-1}$ to $t_i$, no flag,
- **regular** if $|\Delta t_i - n\,\Delta t_0| \le \varepsilon\,\Delta t_0$ with
  $n = \max(\operatorname{round}(\Delta t_i / \Delta t_0), 1)$ ($n \ge 2$ = missed samples),
- **irregular** otherwise → `TIMESTAMP_SUSPECT` on sample $i$.

Irregular and non-positive intervals are summarised in one warning event each.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `expected_interval_s` | 1830 | s | always set from `time.expected_interval_s` (WP-1.7); the median step of the first real export |
| `gap_factor` | 3 | — | project default *[to be tuned]* |
| `tolerance_fraction` | 0.25 | — | project default, tolerates clock drift *[to be tuned]* |

## Deployment detection

A sensor is switched on in the office (stable temperature, small daily range, steady and fairly
dry air), carried into the vineyard (a level change, a much larger daily range, humidity that
follows the daily cycle) and possibly brought back for service and redeployed.
`DeploymentDetector` finds these transitions in six steps and then hands the result to the
policy of its `mode`:

| `mode` | Flags | Events |
|---|---|---|
| `advisory` (default) | none | `unlogged_off_site` warning ("possible unlogged off-site period …, add it to sensors/offsite_log.yaml") for every applied indoor interval that the log does not cover; `unconfirmed_transition` warnings whose time the log does not cover |
| `enforce` (WP-1.5) | `PRE_DEPLOYMENT` on every detected indoor row | `deployment`/`retrieval` transitions, `deployment_mismatch` and `unconfirmed_transition` warnings |

A detected interval counts as **covered** when one logged period of the sensor — touching or
overlapping periods merged (e.g. transport followed by office) — contains it after widening the
logged period by `log_tolerance_s` (default 6 h, project default *[to be tuned]*) on both sides.
For the office stay at the start of the data the interval starts at the first sample. In
advisory mode transitions and `deployment_mismatch` warnings are not reported: they describe
flags that this mode does not set. The modes are `DetectionPolicy` subclasses registered per
mode (`AdvisoryPolicy`, `EnforcePolicy`).

The `unlogged_off_site` warning is written for the owner: times in local time of
`display_timezone` (default Europe/Prague, the zone of the log) with UTC in brackets, followed
by ready-to-paste values with offset, e.g.

```text
possible unlogged off-site period 2026-04-14 01:44 CEST (2026-04-13 23:44 UTC) - 2026-04-17
01:44 CEST (2026-04-16 23:44 UTC) (<detection detail>); if the sensor was not in the vineyard,
add an entry to sensors/offsite_log.yaml with from: "2026-04-14T01:44+02:00" and
to: "2026-04-17T01:44+02:00"
```

**Guiding principle: when the evidence is not clear, do not exclude data.** Wrongly flagging
vineyard data `PRE_DEPLOYMENT` is worse than missing a short service visit. Every step below
therefore needs positive evidence before samples are flagged, and incomplete evidence produces a
warning event instead of flags.

### 1. Change points in level and variance

Rows without temperature and rows flagged by `ignore_mask` (default
`MISSING | OUT_OF_RANGE | MANUAL_EXCLUDE`) are not used. Humidity is used as a second variable if
at least `min_rh_fraction` of the usable rows have it; otherwise the detector works on
temperature alone.

Within a segment each variable $v$ is modelled as independent Gaussian with its own mean and
variance. For a segment $[a, b)$ with $m = b - a$ samples and maximum-likelihood variance
$\hat\sigma^2_v(a, b)$, twice the negative maximised log-likelihood is, up to terms that cancel,

$$
C(a, b) = m \sum_v \ln\!\left(\hat\sigma^2_v(a, b) + \sigma^2_{v,0}\right),
$$

where $\sigma^2_{v,0}$ is a variance floor (quantised indoor data can have zero variance).
Splitting at $\tau$ gains the log-likelihood-ratio statistic of one change in mean and variance

$$
G(\tau) = C(a, b) - C(a, \tau) - C(\tau, b) = 2 \ln \Lambda(\tau).
$$

With prefix sums $S_1(j) = \sum_{i<j} x_i$ and $S_2(j) = \sum_{i<j} x_i^2$,
$\hat\sigma^2(a, b) = \frac{S_2(b) - S_2(a)}{m} - \left(\frac{S_1(b) - S_1(a)}{m}\right)^2$, so
each $C$ costs O(1) and one scan over all $\tau$ of a segment is O(m) (data are centred first
for numerical stability).

**Binary segmentation** (greedy, largest gain first) splits the segment whose best split has the
largest gain, as long as that gain reaches the penalty

$$
\beta = c\,(p + 1)\ln n,
$$

with $p = 2 \times$ (number of variables) parameters per segment, $+1$ for the location, $n$
samples and factor $c$ (1 = Schwarz/BIC weight, Schwarz 1978), and at most `max_change_points`
times. Both sides of a split must last at least `min_segment_s` and contain at least 3 samples.
This is the change-point family of CUSUM-type likelihood tests (Page 1954) and penalised-cost
segmentation (Killick et al. 2012 give the optimal, linear-time PELT search; here the simpler
binary segmentation of Scott & Knott 1974 is used to avoid a new dependency).

**Local search.** The search does not run over the whole history, because then $\ln n$ and the
cap on change points would make the result depend on the series length. It runs in windows of
fixed length $W$ (`window_s`, 30 days) that start every $S$ seconds (`stride_s`, 15 days) **on a
grid anchored at the Unix epoch**: window $k$ covers $[kS, kS + W)$, so a window sees the same
data whether the series is one or five years long. The change points of all windows are pooled;
of two change points closer than `min_segment_s` the one with the larger gain is kept. Outdoor
weather is not i.i.d. Gaussian, so outdoor data produce many change points; that is expected —
the following steps decide which of them matter.

### 2. Absolute rules: indoor-like segments

For a stretch of samples `RegimeClassifier` computes robust features:

- median temperature $\tilde T$ (°C);
- daily temperature spread $s$: the median over consecutive 24-h windows (counted from the
  stretch start; windows with fewer than `min_window_samples` samples skipped, the whole
  stretch if none is left) of $P_{95} - P_5$ — percentiles so that one spike does not matter;
- median relative humidity $\tilde h$ (%) and daily humidity spread $r$ (%), computed like $s$.

A stretch is **indoor-like** if all absolute criteria hold (humidity criteria only with
humidity):

$$
T_{room,min} \le \tilde T \le T_{room,max}, \qquad s \le s_{max}, \qquad
\tilde h \le h_{max}, \qquad r \le r_{max}.
$$

The room band is wide (5–35 °C) so that an unheated store or a hot office is still indoor-like;
the steady-humidity criterion $r \le r_{max}$ is what separates an office from a cloudy summer
day, whose humidity still follows the daily temperature cycle. Consecutive indoor-like segments
form an **indoor run** (a candidate office stay or service visit).

### 3. Exact boundaries and transport

Each boundary of a run is **refined**: within at most `min_segment_s` of the first estimate and
between the neighbouring runs, the position with the largest $G(\tau)$ wins. The minimum
segment duration thus limits the search but not the final boundary. The radius is measured
from the last sample before and the first sample after the boundary, so a gap in the data at
the boundary does not shrink the search to one side.

**Transport trimming (optional, off by default: `transport.enabled: false`).** When enabled, a
**transport transient** (the sensor in a car between office and vineyard) is moved to the
indoor side, so that it becomes `PRE_DEPLOYMENT`. Starting at the boundary on the outdoor
side, samples are moved while their temperature lies outside both reference ranges,

$$
T \notin \left[\min(P_5^{in}, P_5^{out}) - m,\ \max(P_{95}^{in}, P_{95}^{out}) + m\right],
$$

for at most `transport.max_duration_s` (3 h). The outdoor reference is the day of outdoor data
after the maximum transport duration, the indoor reference the day of indoor data next to the
boundary. A transient within the reference ranges (a car at 20 °C) is not detectable and stays
on the side the likelihood put it.

*Trade-off.* With trimming, a 35 °C car phase becomes `PRE_DEPLOYMENT` and the deployment is
placed at the arrival in the vineyard. But if the weather changes within the outdoor reference
day (a warm afternoon followed by rain), real vineyard samples fall outside the reference range
and up to 3 h of them are excluded (review round 2: deployment +1 to +6 samples late in a
heavy-rain scenario at 21 °C). Without trimming no vineyard sample is lost, and the car phase
(typically ≤ 3 samples) usually stays on the outdoor side (review: boundary 3 samples before
arrival), where the `range`, `spike` and `step` checks may flag it. Following the rule "when in
doubt, do not exclude data", trimming is off by default. Whether trimming is on or off, the
indoor comparison windows keep `transport.max_duration_s` away from the boundary.

### 4. Relative confirmation

Each boundary is confirmed by comparing **local windows next to it**: up to
`contrast.window_s` (2 days) of the run on the indoor side — ending (or starting) one maximum
transport duration away from the boundary, so that a transient cannot distort it — and up to
2 days of outdoor data on the other side (not crossing another run). With features $I$ (indoor
window) and $O$ (outdoor window) there are four relative criteria ("votes"):

$$
\begin{aligned}
\text{spread ratio:}\quad & s_O \ge k_s \max(s_I, s_0) \\
\text{level difference:}\quad & |\tilde T_O - \tilde T_I| \ge \Delta T \\
\text{humidity excess:}\quad & \tilde h_O - \tilde h_I \ge \Delta h \\
\text{humidity spread ratio:}\quad & r_O \ge k_r \max(r_I, r_0)
\end{aligned}
$$

A boundary is **confirmed** if the indoor window is indoor-like, the outdoor window is not
(absolute), **and** at least $\min(V, \text{available votes})$ votes hold (relative; $V = 2$, so
temperature-only data need both temperature votes). Examples on synthetic data: an overcast
winter deployment has no spread contrast but a large level and humidity difference; a 12 °C
unheated store or a 30 °C office have a much smaller daily range and drier, steadier air than
outdoors; a cloudy summer day amid clear days is not indoor-like ($r > r_{max}$) and is never
confirmed.

The four votes are two correlated pairs (spread ratios: the daily cycle; level difference and
humidity excess: the step), so two votes can be one physical signal counted twice.

The event `confidence` is the share of available votes that hold (0.5–1 for a confirmed
transition). It is a transparent heuristic, **not a calibrated probability**.

### 5. Which runs count as indoor

- a run at the **start of the data** counts if its deployment is confirmed (office stay);
- a run **between outdoor data** counts only if both its retrieval and its redeployment are
  confirmed (service visit);
- a run at the **end of the data** (retrieval without a later redeployment) never counts: it
  would exclude all later data on uncertain grounds;
- a run covering **all data** (sensor still in the office) has nothing to compare with and does
  not count.

A run with some but not all needed boundaries confirmed produces an `unconfirmed_transition`
warning and no flags. A confirmed deployment is reported as `deployment`, a confirmed retrieval
as `retrieval`, at the first sample of the new regime; the detail gives the local numbers, e.g.
`indoor → outdoor: level -13.6 °C, daily spread x11.4, humidity +33 %, votes 4/4`.

Level shifts *within* the outdoor regime are reported by the `step` check, not by the detector.

### 6. Known deployments and `PRE_DEPLOYMENT`

Known deployment times (e.g. `placement.from` of the sensor registry, plan §2.4) override
detection **only near themselves** (`known_tolerance_s`, 6 h):

1. a detected deployment within the tolerance of a known time is moved to the known time
   (source `registry`, confidence 1). The registry is ground truth: if the known time is
   *later* than the detected deployment, the samples in between (classified outdoor by
   detection, at most `known_tolerance_s`) become `PRE_DEPLOYMENT`, and a `deployment_mismatch`
   warning names the excluded duration;
2. a detected deployment with no known time within the tolerance is still applied, with a
   `deployment_mismatch` warning — e.g. a service visit missing in the registry (returning to
   the same placement adds no `placement.from`);
3. a known time *inside* the detected office stay at the start of the data ends that stay at
   the known time (data after a known deployment are never `PRE_DEPLOYMENT` unless a detected
   retrieval with a later redeployment brackets them), with a warning; a known time inside a
   detected service visit keeps the visit, with a warning;
4. a known time not matched by a detected deployment becomes a registry `deployment` event
   without flags. Only the *first* known time warns, and only if data exist before it (they
   look like vineyard data and are not flagged). A later known time follows an earlier
   placement — a **relocation** — and raises no warning.

In `enforce` mode every row inside an applied indoor interval — the office stay before the
first deployment and each confirmed service visit — gets `PRE_DEPLOYMENT`; rows without values
take the state of their timestamp. In `advisory` mode these intervals only feed the warnings.

| Setting | Default | Unit | Origin |
|---|---|---|---|
| `change_points.min_segment_s` | 86 400 (1 day) | s | project default; also the shortest detectable stay, the change-point separation and the refinement radius |
| `change_points.window_s` / `stride_s` | 30 / 15 days | s | project default |
| `change_points.penalty_factor` | 1 | — | BIC weight (Schwarz 1978) |
| `change_points.max_change_points` | 30 per window | count | project default |
| `change_points.temp_variance_floor_c2` | 0.01 | °C² | (0.1 °C)², project default |
| `change_points.rh_variance_floor_pct2` | 0.25 | %² | (0.5 %)², project default |
| `change_points.min_rh_fraction` | 0.5 | — | project default |
| `regime.room_min_c` / `room_max_c` | 5 / 35 | °C | project default *[to be tuned]* |
| `regime.indoor_max_daily_spread_c` | 4 | °C | project default *[to be tuned]* |
| `regime.indoor_max_rh_pct` | 75 | % | project default *[to be tuned]* |
| `regime.indoor_max_rh_spread_pct` | 8 | % | project default *[to be tuned]* |
| `regime.min_window_samples` | 12 | count | about a quarter of a day at 1830 s |
| `contrast.min_spread_ratio` / `spread_floor_c` | 2 / 0.5 | — / °C | project default |
| `contrast.min_level_difference_c` | 5 | °C | project default |
| `contrast.min_rh_excess_pct` | 15 | % | project default |
| `contrast.min_rh_spread_ratio` / `rh_spread_floor_pct` | 2 / 2 | — / % | project default |
| `contrast.min_votes` | 2 | count | project default |
| `contrast.window_s` / `min_window_samples` | 2 days / 24 | s / count | project default |
| `transport.enabled` | false | — | off: trimming can exclude real vineyard data (see step 3) |
| `transport.max_duration_s` | 10 800 (3 h) | s | project default |
| `transport.margin_c` | 3 | °C | project default |
| `transport.reference_s` / `min_reference_samples` | 1 day / 12 | s / count | project default |
| `mode` | `advisory` | — | owner decision 2026-10-05 (`enforce` = WP-1.5 behaviour) |
| `log_tolerance_s` | 21 600 (6 h) | s | project default *[to be tuned]*, advisory coverage by the log |
| `display_timezone` | Europe/Prague | — | zone of the times in the advisory warning (the log's zone) |
| `known_tolerance_s` | 21 600 (6 h) | s | project default *[to be tuned with Q3]* |
| `ignore_mask` | 259 | bit mask | `MISSING \| OUT_OF_RANGE \| MANUAL_EXCLUDE` |

## Configuration

Since WP-1.7 the settings are the `quality` section of `config/sivin.yaml`
(`QualityPipelineSettings`) and the log location is the `offsite_log` section
(`OffSiteLogSettings`); every key is listed in [configuration.md](configuration.md), and
`sivin config show` prints the resolved values of every enabled check. Example:

```yaml
quality:
  screening_checks: [missing, sampling, range, precip_range, precip_counter, battery]
  deployed_checks: [spike, step, persistence]
  check_settings:
    range: { temp_climate_min_c: -30.0, temp_climate_max_c: 42.0 }
  detect_deployment: true
  deployment:
    mode: advisory            # advisory | enforce
    log_tolerance_s: 21600
    known_tolerance_s: 21600
    change_points: { min_segment_s: 86400, window_s: 2592000, stride_s: 1296000 }
    regime: { room_min_c: 5.0, room_max_c: 35.0, indoor_max_rh_spread_pct: 8.0 }
    contrast: { min_votes: 2, window_s: 172800 }
    transport: { enabled: false, max_duration_s: 10800 }

offsite_log:                  # OffSiteLogSettings (sivin.registry.offsite)
  file: sensors/offsite_log.yaml
  timezone: Europe/Prague
```

`check_settings.sampling.expected_interval_s` and `deployment.display_timezone` are set from
`time.expected_interval_s` and `time.display_timezone`; giving them here with another value is
a configuration error. `sivin qc` loads the registry and the log
(`OffSiteLogStore().load(file, registry, timezone)`; an invalid log stops the run) and passes
it to `QualityPipeline.from_settings(..., off_site_log=log)` (see [cli.md](cli.md)).

## Limitations

- **Not verified on real data.** All tests use the synthetic generator in
  `tests/quality/synthetic.py`, and the review used an independent synthetic generator; the
  thresholds are project defaults to be tuned once real exports (Q1) and known deployment dates
  (Q3) are available. Detection and false-alarm rates measured on synthetic data describe
  failure modes, not field error rates.
- **One flag field per row.** A humidity finding (`range`, `spike`, `persistence`) also
  excludes the row's temperature, because the contract has a single `qc` column (plan §2.5).
- **Short indoor stays** (shorter than `min_segment_s`, default one day) are not detected, and
  stays of about one day only partly (owner question Q2). Their rows count as vineyard data.
- **Office stays without contrast** are not flagged: a sensor whose data are all indoor (still in
  the office) or an office whose daily range exceeds 4 °C (e.g. a sunny window sill) is not
  recognised. Known deployment times then still produce registry events and warnings.
- **Transport** stays on the side the likelihood puts it by default (trimming is off); a car
  phase then usually counts as vineyard data. With trimming on, it is moved to the indoor side
  only if it lies outside both temperature ranges (± 3 °C) and lasts at most 3 h, at the risk of
  excluding up to 3 h of real vineyard data after a weather change.
- **Offices that are not recognised, without a warning.** Besides the sunny window sill, the
  absolute rules miss a humid basement (RH ≈ 80 %, above `indoor_max_rh_pct` = 75 %) and an
  office with a strong night setback (16 → 22 °C, daily spread above
  `indoor_max_daily_spread_c` = 4 °C): 0/15 detected each on the reviewer's second generator,
  and no warning is raised. Their rows enter the indices (a January office adds about 12
  growing degree days per day). Raising the spread threshold to 6 °C found only 4/15 setback
  offices and raised false transitions from 0.40 to 0.60 per sensor-year.
- **The "steady humidity" assumption.** Cloudy days are kept from looking indoor because outdoor
  humidity either exceeds 75 % or follows the daily temperature cycle (daily RH spread > 8 %).
  Where overcast weather is dry and humidity stays steady, outdoor stretches look indoor and
  create false service visits. On the reviewer's second generator: 0.30 false transitions per
  sensor-year (mean 11 `PRE_DEPLOYMENT` rows per year, max 94 ≈ 2 days) with ordinary weather,
  but 3.5 per sensor-year with up to 1340 rows (≈ 28 days) excluded in a dry-overcast stress
  variant. The assumption must be checked on real exports before service-visit
  `PRE_DEPLOYMENT` flags are trusted.
- **Summer offices merging with overcast days.** In summer an overcast day with RH ≤ 75 % can be
  indoor-like itself and merge with an adjacent office stay; the merged run's boundary then
  fails the relative confirmation, the office stay is not flagged and only an
  `unconfirmed_transition` warning remains (reviewer's second generator: 2/15 three-day summer
  offices missed; 3/15 first offices missed in a service-plus-front scenario).
- **The 2-of-4 votes are two correlated pairs.** The temperature and humidity spread ratios both
  measure the daily cycle; the level difference and the humidity excess both measure the step.
  "2 of 4" can therefore be one physical signal counted twice. It is a heuristic, like the
  confidence derived from it.
- **The off-site log is only as good as its entries.** A stay the owner did not log is counted
  as vineyard data; the advisory detector warns about it only when it would have detected it in
  `enforce` mode (all limitations below apply), so a missing warning is no proof that the log
  is complete.
- **Known deployments override detection only near themselves.** Data before the first known
  deployment are flagged only if an office stay is detected; a registry time that the data do
  not confirm produces a warning, not flags. A registry time up to `known_tolerance_s` (6 h) *later* than the
  detected deployment does exclude the samples in between (registry as ground truth); this is
  always reported by a `deployment_mismatch` warning with the excluded duration.
- **Very fast fronts** (≥ 5 °C within one sampling interval) are flagged `STEP` (informative).
- **Persistence** uses greedy left-to-right runs; a run that starts in the middle of an earlier
  run within the tolerance can be split. Runs in saturated air (fog) are never `STUCK`, so a
  humidity sensor stuck at 100 % is not detected while it reads saturation, and a temperature
  sensor that sticks during fog (≥ 50 % of the run at RH ≥ 97 %) is not detected either.
- **Greedy binary segmentation** is not guaranteed optimal (PELT would be); boundary refinement
  and the relative confirmation make the reported boundaries insensitive to that in the tested
  cases.

## Implementation

| Concept | Module | Tests |
|---|---|---|
| `QualityCheck`, `CheckOutcome`, `check_registry` | `sivin/quality/checks/base.py` | `tests/quality/test_base_and_events.py` |
| checks `missing`, `range`, `spike`, `step`, `persistence`, `sampling` | `sivin/quality/checks/*.py` | `tests/quality/test_checks.py` |
| checks `precip_range`, `precip_counter`, `battery` | `sivin/quality/checks/{precip,battery}.py` | `tests/quality/test_precip_battery.py` |
| `GaussianSegmentCost`, `BinarySegmentation` | `sivin/quality/changepoint.py` | `tests/quality/test_changepoint_regime.py` |
| `WindowedChangePoints` (local search) | `sivin/quality/windows.py` | `tests/quality/test_changepoint_regime.py` |
| `RegimeClassifier` (absolute rules) | `sivin/quality/regime.py` | `tests/quality/test_changepoint_regime.py` |
| `TransitionContrast` (relative confirmation) | `sivin/quality/contrast.py` | `tests/quality/test_changepoint_regime.py` |
| `BoundaryRefiner`, `TransportTrimmer` | `sivin/quality/boundaries.py` | `tests/quality/test_changepoint_regime.py` |
| `RegimeSegmenter`, `IndoorRun` | `sivin/quality/segmentation.py` | `tests/quality/test_changepoint_regime.py`, `tests/quality/test_deployment.py` |
| `KnownDeploymentReconciler`, `indoor_mask` | `sivin/quality/timeline.py` | `tests/quality/test_deployment.py` |
| `DeploymentDetector`, `DeploymentResult`, `DetectorMode`, `AdvisoryPolicy`, `EnforcePolicy`, `LoggedCoverage` | `sivin/quality/deployment.py` | `tests/quality/test_deployment.py`, `tests/quality/test_offsite.py` |
| `OffSiteCheck` | `sivin/quality/checks/offsite.py` | `tests/quality/test_offsite.py` |
| `OffSitePeriod`, `OffSiteLog` / `LocalTimeReader` / `StrictLogLoader` / `OffSiteLogStore` | `sivin/registry/offsite/{model,local_time,strict_yaml,store}.py` (re-exported by `sivin.registry.offsite`) | `tests/registry/test_offsite.py` |
| `QualityEvent`, `DeploymentEvent` | `sivin/quality/events.py` | `tests/quality/test_base_and_events.py` |
| `QualityPipeline`, `QualityResult`, `ValueSetAside` | `sivin/quality/pipeline.py` | `tests/quality/test_pipeline.py`, `tests/quality/test_precip_battery.py` |
| synthetic generator | `tests/quality/synthetic.py` | `tests/quality/test_pipeline.py` |

## References

DOIs verified in WP-L.1 (see [literature verification](literature-verification.md)).

- Killick, R., Fearnhead, P., Eckley, I. A. (2012). Optimal detection of changepoints with a
  linear computational cost. *Journal of the American Statistical Association*, 107(500),
  1590–1598. https://doi.org/10.1080/01621459.2012.737745
- Page, E. S. (1954). Continuous inspection schemes. *Biometrika*, 41(1/2), 100–115.
  https://doi.org/10.1093/biomet/41.1-2.100
- Schwarz, G. (1978). Estimating the dimension of a model. *The Annals of Statistics*, 6(2),
  461–464. https://doi.org/10.1214/aos/1176344136
- Scott, A. J., Knott, M. (1974). A cluster analysis method for grouping means in the analysis
  of variance. *Biometrics*, 30(3), 507–512. https://doi.org/10.2307/2529204
- Zahumenský, I. (2004). *Guidelines on Quality Control Procedures for Data from Automatic
  Weather Stations.* World Meteorological Organization, Geneva. (No DOI.) The thresholds of
  the checks above are project defaults, not values from this guideline; the guideline's own
  limits (e.g. a 2 °C step limit for air-temperature samples taken every 6–12 s, persistence
  of 0.1 °C over 60 min) refer to much denser sampling than ours.
