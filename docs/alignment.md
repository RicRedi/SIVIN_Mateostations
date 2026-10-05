# Time alignment of sensors

Package `sivin.alignment` (WP-1.6, MIGRATION_PLAN §2.7, second meaning of "pairing data from
different sensors"). Matching an export file to its sensor is the other meaning and is handled by
`SensorId` and the sensor registry.

## Why alignment is needed

The sensors sample about every 1825 s (30 min 25 s, the value in the legacy configurations and
`sampl_freq_basic.py`). Their clocks are not synchronised and not stable:

- every sensor starts at its own instant, so its samples are offset from the others';
- the interval is not exactly 30 min, so the samples drift against wall-clock half hours
  (25 s per sample for a 1825 s interval) and against each other when the intervals differ;
- samples are missing, flagged by quality control, or `NaN`.

Timestamps of two sensors therefore practically never coincide, and a comparison "sensor A vs
sensor B at 14:30" needs a rule that decides which value of each sensor represents 14:30. The
aligner applies that rule to N sensors at once and returns a wide `time x sensor` table per
variable.

## Time grid

A `TimeGrid` is the regular sequence of UTC instants

$$g_m = g_0 + m\,\Delta, \qquad m = 0, 1, \dots, \quad g_m \le g_\text{end}$$

with step $\Delta$ (`step_s`, default 1800 s = 30 min). `GridPolicy` derives $g_0$ and
$g_\text{end}$ from the data: every grid point is a multiple of $\Delta$ since the Unix epoch
(`hh:00`, `hh:30` UTC for the default), so grids built from different data sets coincide. The
span is chosen by a registered `SpanRule`:

| `span` | Covers | Snapping |
|---|---|---|
| `union` (default) | from the earliest first to the latest last usable sample of any sensor | outwards: floor of start, ceiling of end |
| `overlap` | from the latest first to the earliest last usable sample (sensors with data only) | inwards: ceiling of start, floor of end; no grid if empty |

A sample is *usable* if its row is a complete measurement (both `temp_c` and `rh_pct` present,
the whole-row rule of `MeasurementSeries.complete_mask`, owner decision 2026-10-05) and its `qc`
flags do not intersect the exclusion mask. The rule is checked on the values, so it also holds
for store data that carry no `MISSING` flag yet (WP-1.7). The grid span uses the usable rows.

All times are UTC (`datetime64[ns, UTC]`). Daylight-saving transitions of Europe/Prague therefore
play no role: a sensor sampling every 30 min across a transition is a regular UTC series, and the
grid has neither a missing nor a repeated hour (tested for both 2026 transitions).

## Strategies

Every variable of every sensor is aligned separately, on the usable rows only: excluded rows and
rows with a missing variable are never paired. Under the whole-row rule a row whose humidity is
`NaN` contributes no temperature either (before WP-1.7 it did, unless it carried `MISSING`).
Strategies are vectorised (`numpy.searchsorted`), with no Python loop over samples.

### `nearest_within_tolerance` (`NearestWithinTolerance`)

For grid point $g$ and usable sample times $t_i$ with values $v_i$:

$$i^* = \arg\min_i |t_i - g| \quad \text{(ties: the earlier sample)}, \qquad
v(g) = \begin{cases} v_{i^*} & |t_{i^*} - g| \le \tau \\ \text{invalid} & \text{otherwise} \end{cases}$$

- Values are measured values, never modified. The offset $|t_{i^*} - g|$ in seconds is kept in
  `AlignedPanel.offsets_s(variable)` for diagnostics.
- The tolerance is derived from the sensors' sampling, not from the grid:

  $$\tau = \frac{T}{2} + m$$

  with the expected sampling interval $T$ (`expected_interval_s`, default 1825 s) and a jitter
  margin $m$ (`margin_s`, default 20 s, [to be tuned]), i.e. 932.5 s. In an uninterrupted record
  no instant is farther than $T/2$ from a sample, so every grid point gets a value.
  `tolerance_s` overrides the derived value explicitly. The bound is inclusive.
- **One sample can serve two neighbouring grid points.** The sensors sample more slowly
  (1825 s) than the grid (1800 s), so there are about 240 fewer samples than grid points per
  year; the samples slip by 25 s per step and once every ~73 grid points one sample is the
  nearest for two of them. With $\tau = \Delta/2 = 900$ s (`tolerance_s: 900`, "never reuse a
  sample" except exactly half-way) that grid point stays empty instead, at a different time for
  every sensor: worked examples in `tests/alignment/test_strategies.py`
  (`test_nearest_slip_of_1825_s_sampling_on_1800_s_grid`,
  `test_nearest_default_tolerance_covers_the_slip`). The offsets table shows reuse.

### `linear_interpolation` (`LinearInterpolation`)

For grid point $g$ with usable neighbours $t_l \le g \le t_r$ (values $v_l$, $v_r$):

$$v(g) = v_l + (v_r - v_l)\,\frac{g - t_l}{t_r - t_l}, \qquad \text{valid only if } t_r - t_l \le \Delta_\text{max}$$

- A sample exactly at $g$ is taken as is.
- Never extrapolates: grid points before the first or after the last usable sample are invalid.
- A gap longer than $\Delta_\text{max}$ (`max_gap_s`) stays empty.
- No offset table (the value does not come from a single sample).

## Parameters

Proposed configuration section `alignment` (model `sivin.alignment.AlignmentConfig`; wiring into
`config/sivin.yaml` is part of WP-1.7). The exclusion mask is `analytics.exclude_mask`.
`params` is a read-only mapping validated by the chosen strategy's parameter model; the grid
step must be at least 1 s and a whole number of nanoseconds.

| Key | Default | Unit | Origin |
|---|---|---|---|
| `strategy` | `nearest_within_tolerance` | — | project choice |
| `params.tolerance_s` | unset (derived: `expected_interval_s / 2 + margin_s` = 932.5 s) | s | explicit override |
| `params.expected_interval_s` | 1825 | s | legacy configs, `sampl_freq_basic.py` (same as `time.expected_interval_s`) |
| `params.margin_s` | 20 | s | project choice [to be tuned on real data]: clock jitter |
| `params.max_gap_s` | 2737.5 (= 1.5 × 1825) | s | project choice [to be verified on real data]: bridges neighbouring samples with room for jitter, not a missing sample |
| `grid_step_s` | 1800 | s | MIGRATION_PLAN §2.7 (30 min) |
| `span` | `union` | — | project choice |

```yaml
alignment:
  strategy: linear_interpolation
  params: {max_gap_s: 2737.5}
  grid_step_s: 1800
  span: overlap
```

## Output: `AlignedPanel`

| Member | Returns |
|---|---|
| `variable(name)` | `DataFrame`, index `timestamp_utc` (UTC), one `float64` column per sensor id (string); `NaN` where invalid |
| `validity(name)` | same shape, `bool` |
| `offsets_s(name)` | same shape, seconds; `None` for interpolation |
| `complete_rows(name)` | rows of `variable(name)` where every sensor is valid |
| `pairwise_differences(name, pairs=None)` | long frame `timestamp_utc, sensor_a, sensor_b, delta_<name>` = A − B where both are valid; all pairs in column order, or only the ordered `pairs` given; sensor labels categorical |
| `sensors`, `variables`, `times`, `strategy_id`, `is_empty` | metadata |

**Memory of `pairwise_differences`.** One row per pair and valid grid point, about 18 bytes
(8 time, 8 difference, 1 + 1 categorical code). All pairs grow as $N(N-1)/2$: a synthetic year
of 30 sensors gives 7.6 M rows, 137 MB of result (peak ~410 MB while building, 2 s in this
sandbox); 100 sensors would be about 11 times more. Consumers that need only neighbours (QC)
should pass `pairs`.

Columns are ordered by sensor id regardless of input order. Any N ≥ 1 works without code
changes. If no grid can be derived (no usable data, or no overlap) the panel has zero rows.

## Recommended use per downstream task

| Task | Strategy | Span | Why |
|---|---|---|---|
| Neighbour QC (`NEIGHBOR_OUTLIER`, WP-1.5 follow-up) | `nearest_within_tolerance`, optionally a smaller `tolerance_s` | `overlap` | compares measured values only, never interpolated ones; `offsets_s` shows how far apart in time the compared samples are; `pairwise_differences(name, pairs=neighbours)` gives A − B directly |
| Spatial analysis (WP-2.4) | `linear_interpolation` | `overlap` | values represent the same instant; `complete_rows` gives snapshots where all sensors are valid |
| Comparison charts | `nearest_within_tolerance` (raw values) or `linear_interpolation` (smooth) | `union` | nothing is dropped; invalid cells become gaps |

Daily climate indices do not need alignment: they use each sensor's own `DailyWeather`.

## Assumptions and limitations

- Linear interpolation in time assumes the variable changes roughly linearly between two samples
  about 30 min apart. Rapid changes (fronts, sunrise on a sensor screen) are smoothed.
- Nearest-sample values can be up to the tolerance away from the grid instant; at the default
  that is 932.5 s (about 15.5 min). Differences between sensors then include a temporal component, which is why
  the offsets are reported.
- The defaults of `margin_s` and `max_gap_s` are project choices, not taken from literature,
  and have not been tuned on real exports (none available to this workpackage).
- Sample timestamps are taken as given. Clock *errors* (a sensor's clock being wrong in absolute
  terms) cannot be detected or corrected by alignment.

## Implementation

| Class | Module | Tests |
|---|---|---|
| `TimeGrid`, `GridPolicy`, `SpanRule`, `UnionSpan`, `OverlapSpan` | `sivin/alignment/grid.py` | `tests/alignment/test_grid.py` |
| `AlignmentStrategy`, `NearestWithinTolerance`, `LinearInterpolation`, `SampleSet`, `AlignedValues` | `sivin/alignment/strategies.py` | `tests/alignment/test_strategies.py` |
| `SensorAligner` | `sivin/alignment/aligner.py` | `tests/alignment/test_aligner.py` |
| `AlignedPanel` | `sivin/alignment/panel.py` | `tests/alignment/test_aligner.py`, `test_panel_config_registry.py` |
| `AlignmentConfig` | `sivin/alignment/config.py` | `tests/alignment/test_panel_config_registry.py` |
| `ClassRegistry` | `sivin/alignment/registry.py` | `tests/alignment/test_panel_config_registry.py` |

A new strategy is a subclass of `AlignmentStrategy` with `strategy_id`, a `params_model` and
`align()`, decorated with `@strategy_registry.register`; a new span rule likewise with
`SpanRule` and `@span_registry.register`.

```python
from sivin.alignment import LinearInterpolation, GridPolicy, OverlapSpan, SensorAligner

aligner = SensorAligner(LinearInterpolation(), GridPolicy(step_s=1800.0, span=OverlapSpan()))
panel = aligner.align(series_list)          # list of MeasurementSeries, one per sensor
snapshots = panel.complete_rows("temp_c")   # time x sensor, all sensors valid
```

## References

No literature is cited: nearest-neighbour selection and linear interpolation are elementary
methods, and the parameter defaults are project choices documented above.
