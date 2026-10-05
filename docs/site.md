# Static site data (`sivin build-site`, WP-3.2)

`sivin build-site` writes the JSON files the web portal ([web.md](web.md)) reads, exactly per the
site data contract, [MIGRATION_PLAN §2.6](../MIGRATION_PLAN.md) (`schema_version: 1`), with the
`off_site` intervals of §2.8 and the optional precipitation and battery fields of WP-1.9.
`sivin run` builds the site as its last step ([cli.md](cli.md)).

```
sivin build-site [--out DIR] [--season YEAR ...] [--full]
```

Default output: `<paths.site_dir>/data` = `site/data`. The code is in `src/sivin/site/`
(`SiteBuilder` and one writer class per file kind) and `src/sivin/app/site.py` (wiring).

## Inputs

- **Measurements through quality control.** Every published sensor is read from the store with
  `QualityService.checked` — QC over the sensor's whole record, with the off-site log
  (`PRE_DEPLOYMENT`) and the precipitation set-aside — never as raw store data. In `sivin run`
  the QC results of the `qc` step are reused.
- **Indices** come from `IndicesService` (a dry-run instance: it writes no file under
  `data/derived/`), with the parameters of `analytics.indices`.
- **Published sensors** are the registry sensors that have stored data. Retired (and inactive)
  sensors are published with their whole history; the manifest carries their `status` so the
  web can grey them out. A sensor with stored data but no registry entry has no position or
  label: it is left out with a warning. A registry sensor without data is only in
  `sensors.geojson`.
- Times and masks: `time.display_timezone` (local days), `time.expected_interval_s` (daily
  coverage), `analytics.exclude_mask` (valid samples), `analytics.auxiliary_exclude_mask`
  (daily precipitation and battery).

Nothing from the run records, no error text and no absolute path is published.

## Output

```
site/data/manifest.json
site/data/sensors.geojson
site/data/latest.json
site/data/series/<sensor_id>/raw/<YYYY-MM>.json
site/data/series/<sensor_id>/daily.json
site/data/events/<sensor_id>.json
site/data/indices/<season>.json
site/data/.build-state.json        # incremental build state (not part of the contract)
```

**Encoding.** UTF-8 JSON, compact (no spaces), one line plus a final line break. Keys are
written in the order of the contract (§2.6), sensors sorted by id, so the same data always give
the same bytes. Missing values are `null`. Times in the data are **Unix seconds UTC**, whole
seconds (rounded down; the store keeps whole seconds); `generated_at` and `computed_at` are ISO
8601 UTC with `Z`.

**Rounding** (`sivin.site.columns`):

| Values | Decimals | Why |
|---|---|---|
| temperature °C, humidity %, precipitation mm, battery V (raw and daily) | 2 (0.01) | the provider's precision (temperature and battery 0.01, humidity and precipitation 0.1); keeps every raw value exactly and removes float noise of daily means |
| shares 0-1: daily `coverage`, index `coverage` | 3 | 0.001 of a day = 86 s, below one sampling interval |
| index `value` (in the unit of the index) | 2 | display precision |
| event `confidence` 0-1 | 2 | display precision |

### `manifest.json`

`schema_version` (1), `generated_at`, `display_timezone`, then:

- `variables`: `temp_c` (°C), `rh_pct` (%), `precip_mm` (mm) and `battery_v` (V) with labels
  `cs`/`de`/`en` (`sivin.site.labels.VARIABLES`). The web looks labels up by id; extra entries
  do no harm.
- `sensors`: per published sensor `first_t`, `last_t` (first and last sample), `raw_months`
  (UTC months with a raw file) and **`status`** (`active`, `inactive`, `retired`; optional in
  the web contract).
- `seasons`: the seasons with an indices file.
- `indices`: every registered index with `id`, `unit`, `doc` (`docs/indices/<id>.md`) and
  `label` (`sivin.site.labels.INDEX_LABELS`; an index without a label is shown under its id and
  a warning is logged; a test checks that every registered index has one).

### `sensors.geojson`

The registry file `paths.sensors_file`, copied byte for byte.

### `latest.json`

Per sensor the **last valid sample**: both temperature and humidity present and no flag of
`analytics.exclude_mask` (the whole-row rule of §0.5): `t`, `temp_c`, `rh_pct`, `qc` (only
informative flags can be set) and `stale`. A sensor without any valid sample (for example
77799986, off site for its whole export) is left out; the map shows it grey.

**Staleness:** `stale` is `true` when `generated_at − t > site.stale_after_s`, default
**36 h** (129 600 s): the pipeline runs once a day at 06:00 local time (Q5), so a healthy
sensor's last sample is at most about 24 h old; 36 h tolerates one late or failed run before
the map greys a sensor out. A sample exactly 36 h old is not stale.

### `series/<id>/raw/<YYYY-MM>.json`

One file per **UTC** calendar month with samples (`2026-07` = `[2026-07-01T00:00Z,
2026-08-01T00:00Z)`, owner decision 2026-10-05). Columns `t`, `temp_c`, `rh_pct`, then the
optional `precip_mm` and `battery_v`, then `qc`. Every sample of the QC'd series is written,
flagged ones included — the web hides them by their `qc` (display mask 311), e.g. off-site
samples carry `PRE_DEPLOYMENT` (32). Values set aside by QC (implausible precipitation) are
`null`. `precip_mm` and `battery_v` are written only for a month in which at least one value is
present (older data and devices without them omit the fields; the web tolerates that).
`precip_total_mm` (the device counter) is not published.

### `series/<id>/daily.json`

`DailyWeather` of the QC'd series, one row per local calendar day (`time.display_timezone`)
from the first to the last sample, days without valid samples included (values `null`,
coverage 0): `date`, `temp_min`, `temp_mean`, `temp_max`, `rh_min`, `rh_mean`, `rh_max`,
`coverage`, then the optional

- `precip_sum_mm` and **`precip_n_samples`** — the daily sum and the number of interval values
  in it. `precip_n_samples` **is published** (decision of WP-3.2): the precipitation sum does
  not follow the temperature/humidity coverage (WP-1.9), so without the count a sum over half a
  day would look like a full day (a full day has about 86 400 s / 1830 s ≈ 47 values). It is an
  optional column of the web contract.
- `battery_min_v`.

Each optional group is written only when some day has a value.

### `events/<id>.json`

`{"sensor_id": ..., "events": [...]}`, written for every published sensor (possibly with an
empty list). QC reports many event kinds; `site.events` selects the published ones. Each keeps
its kind as `type`; `source` is `log`, `detected` or `registry`; `confidence` is 0-1 or `null`;
`detail` is the QC text.

| QC event kind | Published by default | Shape | Web |
|---|---|---|---|
| `off_site` (off-site log) | yes | interval, `t_end` = end (exclusive), `null` while open | grey band, data hidden ([web.md](web.md#off-site-periods)) |
| `deployment`, `retrieval` (detector, `enforce` mode only) | yes | point (no `t_end`) | dashed line + marker |
| `step` (step check) | yes | point | dashed line + marker |
| `low_battery` (battery check) | yes | interval, `t_end` = last low reading | amber marker at `t`, label with the end; no data hidden |
| `unlogged_off_site` (detector, advisory) | yes | interval, `t_end` = end of the indoor-like period | amber marker at `t`, label with the end; no data hidden |
| `unconfirmed_transition` | no | point | — |
| `gap`, `irregular_sampling`, `non_positive_interval`, `precip_out_of_range`, `precip_counter_reset`, `precip_counter_mismatch`, `deployment_mismatch` | no | interval if it has an end | — (stay in `data/derived/events/`) |

A kind added to `site.events` that the web does not know is skipped by the web with a console
warning (it does not reject the file). In the default advisory mode the detector produces no
`deployment`/`retrieval` events; its findings are `unlogged_off_site` warnings.

### `indices/<season>.json`

`season`, `computed_at` (the `generated_at` of the build that wrote the file) and `sensors`:
sensor → index id → `value`, `unit`, `coverage`, `complete`, `class` and **`estimated`** (`true`
when the index uses a proxy, e.g. leaf wetness from humidity; optional in the web contract).
The index `details` are not published. A sensor without data in the season window is absent;
an index that failed for a sensor is left out of its entry and reported as a failure (exit
code 1). Off-site data are excluded from the indices, so a sensor that was off site the whole
season has `value: null` (or a value with `coverage: 0` for the disease counts) and
`complete: false`; the web must use `complete`.

**Seasons:** `--season YEAR` (repeatable) sets them; by default every calendar year (display
time zone) from the first to the last sample of any published sensor. The output holds exactly
these seasons; indices files of other seasons are removed.

## Incremental build

The output directory keeps `.build-state.json`: a fingerprint of the shared inputs, the seasons,
and per sensor a fingerprint of its store files (`data/raw/<id>/*`, names and contents), the
SHA-256 of every per-sensor file written, its summary (times, months, latest sample, years) and
its index entries.

A build

1. ignores the state if `--full` is given, if it is missing, unreadable or of another format,
   or if the **shared inputs** changed: the configuration (every section except `paths` and
   `ingest`), the registry file, the off-site log file, the `sivin` version or the output format
   version (`SITE_OUTPUT_FORMAT`). Then every sensor is rebuilt;
2. **reuses** a sensor whose store fingerprint is unchanged and whose files are all present
   with their recorded SHA-256 (a deleted or edited output file makes it rebuild) — without
   reading or checking its data;
3. quality-checks and writes the other sensors, computes their indices, and rebuilds every
   sensor when the seasons differ from the last build;
4. writes manifest, registry copy, `latest.json` and the indices files on every build
   (`generated_at` changes), but any file only when its bytes change;
5. deletes files under `series/`, `events/` and `indices/` that are no longer produced (removed
   sensors, months or seasons); other files in the directory are never touched.

The result is **byte-identical** to a full build of the same inputs at the same time
(`tests/site/test_service.py::test_incremental_and_full_builds_are_byte_identical`).

**Failures** never remove published data: a sensor whose QC fails keeps its previous files and
state (with the old fingerprint, so the next build tries again); a new sensor that fails is not
published. Failures are printed and give exit code 1; in `sivin run` they go into the run
record. If the output directory cannot be written, `sivin run` records `site: ...` and goes on.

The state file sits next to the data and is deployed with it; it holds only fingerprints,
relative paths, summaries and index entries — no paths of the machine, no credentials. For the
incremental build to help, the scheduled workflow (WP-4.1) has to keep `site/data` (with the
state) between runs; otherwise every run is a full build, which gives the same files.

## Cross-language contract test

`web/tests/fixtures/python-site/` is produced by the Python pipeline: `sivin run --skip-fetch`
in a temporary project with the repository's registry and off-site log, the trimmed **real**
export of 77799986 (public by owner decision; off site for the whole export) and a
**synthetic** 4-day export of 77678271 across the May/June 2026 month boundary, `generated_at`
fixed to 2026-10-05T04:00:00Z.

- `tests/e2e/test_site.py` rebuilds it and fails when the committed copy differs.
- `web/tests/pythonSite.test.ts` reads every file through the web's validators (no
  `ContractError`, no warning) and the `DataClient` (raw ranges, daily, events, indices) and
  checks the values.

Regenerate after a change of the output (and bump `SITE_OUTPUT_FORMAT` in
`src/sivin/app/site.py` so existing sites are rebuilt in full):

```bash
.venv/bin/python -m tests.site.python_site
```

## Configuration (`site`)

| Key | Default | Meaning |
|---|---|---|
| `site.stale_after_s` | `129600.0` | staleness threshold of `latest.json` in seconds (36 h) |
| `site.events` | `off_site, deployment, retrieval, step, low_battery, unlogged_off_site` | published QC event kinds |

The output directory is `<paths.site_dir>/data`. Reference: [configuration.md](configuration.md).

## Limitations

- Only the trimmed real export of one sensor exists (off site all the time), so the site was
  never built from real vineyard data; the synthetic sensor stands in.
- Large stores: a reused sensor costs one read of its store files (fingerprint) and of its
  output files (SHA-256); a rebuilt sensor is quality-checked over its whole record.
- `sivin run --sensor X` still builds the site of every published sensor (the others are
  reused when unchanged).
