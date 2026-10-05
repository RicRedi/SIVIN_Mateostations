# Architecture

A condensed, English summary of [MIGRATION_PLAN.md §2](../MIGRATION_PLAN.md#2-cílová-architektura-a-kontrakty).
The plan is the binding text; if this page and the plan disagree, the plan is right and this page
is stale.

## Purpose and shape

SIVIN collects temperature and relative-humidity measurements from weather stations in South
Moravian vineyards, checks their quality, computes viticultural climate indices and publishes
everything on a static map portal on GitHub Pages. There is **no database and no server**:

- the measurements live as CSV files on the `data` branch of the repository,
- a scheduled GitHub Actions workflow refreshes them (the data provider has no API, so exports
  are downloaded with an automated browser),
- the web page only reads pre-generated JSON files. Opening the page never triggers a workflow;
  data are at most one cron interval old.

## Data flow

```
data provider portal ──► PortalClient ──► ExportParser ──► InputValidator ──► MeasurementStore
   (Excel export)        (Selenium)       (xlsx / csv)     (schema, time)      (branch `data`)
                                                                                    │
     QualityPipeline (range, spike, step, stuck, deployment) ◄─────────────────────┤
     SensorAligner (common time grid)      ClimateIndex (indices)                   │
                                                  │                                 ▼
                                                  └──────────► SiteBuilder ──► site/data/*.json
                                                                                    │ deploy
                                                         GitHub Pages: web/ (Leaflet + uPlot)
```

1. `PortalClient` logs in, lists devices and downloads one export per sensor.
2. `ExportParser` implementations turn each file into a `MeasurementSeries`; local wall-clock
   timestamps are converted to UTC by `LocalTimeConverter`.
3. `InputValidator` produces a `ValidationReport`; a file with errors is quarantined and never
   written to the store, the run continues with the next file.
4. `MeasurementStore` appends idempotently (`data/raw/<sensor_id>/<YYYY>.csv`).
5. `QualityPipeline` sets `QcFlag` bits and detects deployment events (office → vineyard).
6. `SensorAligner` puts several sensors on a common grid (for neighbour checks and comparison).
7. `ClimateIndex` subclasses compute indices from `DailyWeather` and the raw series.
8. `SiteBuilder` writes the static site data contract (`site/data/`, `schema_version: 1`).

## Shared contracts (WP-0.1)

These live in `sivin.core` and `sivin.analytics.base`; import them from the submodules
(`sivin.core` re-exports nothing, so light modules such as `sivin.config` never load pandas). Every later workpackage builds on them;
changing one is a plan change approved by the owner.

| Contract | Module | Summary |
|---|---|---|
| `SensorId` | `sivin.core.ids` | Canonical 8-digit serial (`77678271`). `SensorId.parse` accepts the portal name `8615620 77678271`, the GPX name `77678271 (VUT)` and export file names/paths, with spaces (`MeteoData_8615620 77678271 (VUT)_20260301_223857.csv`) or with underscores (`MeteoData_8615620_77799986_VUT_20260301_223842.csv`, the spelling of the first real export). The legacy 4-digit suffix (`8271`) is ambiguous and only resolvable through the sensor registry. |
| `QcFlag` | `sivin.core.flags` | `IntFlag` bit field per sample: `MISSING=1, OUT_OF_RANGE=2, SPIKE=4, STEP=8, STUCK=16, PRE_DEPLOYMENT=32, NEIGHBOR_OUTLIER=64, TIMESTAMP_SUSPECT=128, MANUAL_EXCLUDE=256`. `QcFlag.DEFAULT_EXCLUDE` (311) is the default exclusion mask for indices. |
| `MeasurementSeries` | `sivin.core.schema` | Validated, immutable measurements of one sensor: `timestamp_utc` (`datetime64[ns, UTC]`, strictly increasing), `temp_c`, `rh_pct` (`float64`, `NaN` = missing), the auxiliary `precip_mm`, `precip_total_mm`, `battery_v` (`float64`, `NaN` when absent; WP-1.9, schema below), `qc` (`int32`), optional `source`. `to_frame()` adds `sensor_id` (long format). `with_values(column, values)` replaces an auxiliary column only. `valid_mask(mask)` = not excluded by flags; `complete_mask(mask)` = additionally both values present (row validity, below). |
| `LocalTimeConverter` | `sivin.core.timeutil` | Local wall-clock → UTC with deterministic daylight-saving handling. **Input must be in source order, oldest first** (never sorted by local time); decreasing unambiguous rows raise `ValueError`. Each fall-back transition is resolved on its own; only a single backward jump of the wall clock resolves it, anything else (e.g. no jump, several jumps) is a best guess flagged `unresolved`. Nonexistent spring times are shifted by the gap. Ambiguous and nonexistent rows are `suspect`; a suspect row that would duplicate another UTC instant becomes `NaT` + `unresolved`. Callers drop the `NaT` rows before `MeasurementSeries.from_records`. Also local calendar dates and UTC bounds of a local day (23 h / 25 h days). |
| `DailyWeather` | `sivin.core.daily` | Daily min/mean/max of temperature and humidity per local calendar day over the **valid samples** (row validity, below). `n_samples` and `coverage` (share of the real day length covered by valid samples) are row-level; `coverage` is the column of the site contract. The per-variable columns `temp_n_samples`/`temp_coverage`, `rh_n_samples`/`rh_coverage` are kept for API stability and always equal the row-level values. `precip_sum_mm` (sum of `precip_mm`) and `battery_min_v` (minimum of `battery_v`) over the same valid samples, `NaN` without values (WP-1.9). |
| `MonthDay`, `Season` | `sivin.core.season` | Periods given by month and day (vegetation season, Huglin period, single months). |
| `ClimateIndex`, `IndexContext`, `IndexResult`, `IndexRegistry` | `sivin.analytics.base` | Extension point for indices: a new index is a subclass registered with `@index_registry.register`; parameters are frozen pydantic models. |
| defaults | `sivin.core.defaults` | Shared default values (time zone, nominal sampling interval `DEFAULT_SAMPLING_INTERVAL_S` = 1830 s measured on the first real export, the legacy estimate `LEGACY_SAMPLING_INTERVAL_S` = 1825 s, coverage thresholds) without heavy imports. |
| `SivinConfig` | `sivin.config` | `config/sivin.yaml` as frozen pydantic models (`extra="forbid"`): sections `paths`, `time`, `analytics`. |
| `ProjectPaths` | `sivin.paths` | Project root discovery; configuration paths are relative to it. |

### Row validity (owner decision 2026-10-05)

A measurement is one row: a timestamp with a temperature and a humidity. **If one variable is
missing at a given time, the whole measurement is invalid** (plan §0.5, §2.7). The layers apply
the rule in two different ways:

*Checked on the values* (correct for any input, flagged or not):

| Layer | Rule |
|---|---|
| core (`MeasurementSeries.complete_mask`) | `True` only if both values are present and no flag of the exclusion mask is set |
| core (`DailyWeather`) | uses `complete_mask`: a sample counts only with both values, regardless of the `MISSING` flag |
| input validation (`values-present`) | a table in which one variable has no value at all is an ERROR (every row would be invalid) |

*Sets the `MISSING` flag* (the producers of the flag):

| Layer | Rule |
|---|---|
| parsers (`TabularExportReader.assemble`) | a row with `temp_c` **or** `rh_pct` missing gets `QcFlag.MISSING` |
| quality control (`MissingValueCheck`) | default rule `any`: `MISSING` when one variable is `NaN` |

*Relies on the `MISSING` flag* (correct only if the flag is set and the exclusion mask contains
`MISSING`):

| Layer | Location | What happens on unflagged data |
|---|---|---|
| analytics | `analytics/disease/botrytis.py:289-309` | a humidity-only row counts as wet and extends a wetness period |
| analytics | `analytics/disease/powdery_mildew.py:72` | per-sample hours use temperature-only rows |
| analytics | `analytics/ripening/durations.py:60,140,270` | values masked by flags only, `NaN` handled per variable |
| alignment | `alignment/strategies.py:104` | grid points valid for one variable and not the other |
| web | `DISPLAY_EXCLUDE_MASK` (= `DEFAULT_EXCLUDE`, 311) | a `null` without `MISSING` keeps the other value (see `docs/web.md`) |

**Data read from the measurement store come back with `qc = 0`** (the store keeps no flags,
§2.5). The QC pipeline (`QualityPipeline`, with `MissingValueCheck`) must therefore run on store
data **before** analytics, alignment and the site export, or the locations above see unflagged
half-rows. WP-1.7 (integration) wires this order and switches the analytics and alignment
locations above to `MeasurementSeries.complete_mask`, so that they no longer depend on the flag.

The `qc` field stays one flag set per row; the `NaN` of the other variable is not replaced.

### Measurement schema and auxiliary variables (owner decision Q9, WP-1.9)

Columns of `MeasurementSeries.frame` (plan §2.5), in this order:

| Column | Type | Unit | Meaning | Row validity |
|---|---|---|---|---|
| `timestamp_utc` | `datetime64[ns, UTC]` | — | time of the sample, strictly increasing | required |
| `temp_c` | `float64` | °C | air temperature; `NaN` = missing | required for a valid row |
| `rh_pct` | `float64` | % | relative humidity; `NaN` = missing | required for a valid row |
| `precip_mm` | `float64` | mm | precipitation in the interval since the previous sample (export column `Srážky (mm)`) | not part of the rule |
| `precip_total_mm` | `float64` | mm | the device's cumulative precipitation counter (`Celkové srážky (mm)`) | not part of the rule |
| `battery_v` | `float64` | V | battery voltage (`Nabití baterie (V)`) | not part of the rule |
| `qc` | `int32` | — | `QcFlag` bit field | — |
| `source` | string | — | optional; the export the row came from | — |

The three auxiliary columns (`AUXILIARY_COLUMNS`) are optional on input and filled with `NaN`
when absent, so older exports, older store files and other devices keep working. **The row
validity rule concerns temperature and humidity only**: a missing auxiliary value never makes
a row invalid, and the parsers never set `MISSING` for it. Conversely, quality problems of the
auxiliary variables must not invalidate temperature and humidity, so their checks
(`precip_range`, `precip_counter`, `battery`) report events and never set row flags; an
implausible precipitation value is set aside as `NaN` (`PrecipRangeCheck.set_aside`) instead of
flagging the row (see `docs/quality-control.md`). The store writes the columns since WP-1.9 and
still reads files without them (`docs/storage.md`); the web contract has the optional fields
`precip_mm`, `battery_v` (raw months) and `precip_sum_mm`, `battery_min_v` (daily).

Internally all timestamps are UTC. Local time (`Europe/Prague`) is used only when parsing
exports and for daily aggregation and display. Units: °C, %, kPa, m, seconds.

## Storage and site data

- Store (`data` branch): `data/raw/<sensor_id>/<YYYY>.csv`, `data/derived/events/<sensor_id>.json`,
  `data/runs/<YYYY-MM-DD>.jsonl`. Writes are idempotent.
- Site data (`site/data/`): `manifest.json`, `sensors.geojson`, `latest.json`,
  `series/<id>/raw/<YYYY-MM>.json`, `series/<id>/daily.json`, `events/<id>.json`,
  `indices/<season>.json`. Arrays are column-oriented, time is Unix seconds UTC, missing = `null`.
  The exact shapes are in plan §2.6.

## Sensor registry

`sensors/sensors.geojson` is the single source of truth for sensors: canonical id, portal name,
label, site, variety, status and the placement history. The `from` of each placement is the
deployment instant and is the ground truth for the deployment detector (plan §2.4).

## Package layout

| Package | Content | Workpackage |
|---|---|---|
| `sivin.core` | shared contracts above | WP-0.1 |
| `sivin.registry` | `Sensor`, `Placement`, `SensorRegistry`, GPX import | WP-1.1 |
| `sivin.ingest` | `ExportParser` implementations, `InputValidator`, `PortalClient` | WP-1.2, WP-1.3 |
| `sivin.storage` | `MeasurementStore`, run log | WP-1.4 |
| `sivin.quality` | `QualityCheck` implementations, `DeploymentDetector`, `QualityPipeline` | WP-1.5 |
| `sivin.alignment` | `SensorAligner` | WP-1.6 |
| `sivin.analytics` | `ClimateIndex` base and registry (WP-0.1); `thermal`, `ripening`, `disease`, `spatial` | WP-2.x |
| `sivin.site` | `SiteBuilder` | WP-3.2 |
| `sivin.viz` | publication plots and animations | WP-5.1 |
| `sivin.cli` | `sivin` command; the only place that configures logging | WP-0.1, WP-1.7, WP-3.2 |
| `web/` | TypeScript frontend (Leaflet, uPlot) | WP-3.1 |

## Design rules in one paragraph

Domain concepts are classes; extension points are abstract base classes with a registry filled
by class decorators (registries are the only module-level mutable state); collaborators arrive
through constructors; value objects are frozen; nothing runs at import time; small pure formulas
are functions tested in isolation. See plan §1.2 and [CONTRIBUTING.md](../CONTRIBUTING.md).
