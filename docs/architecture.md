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
| `SensorId` | `sivin.core.ids` | Canonical 8-digit serial (`77678271`). `SensorId.parse` accepts the portal name `8615620 77678271`, the GPX name `77678271 (VUT)` and export file names/paths. The legacy 4-digit suffix (`8271`) is ambiguous and only resolvable through the sensor registry. |
| `QcFlag` | `sivin.core.flags` | `IntFlag` bit field per sample: `MISSING=1, OUT_OF_RANGE=2, SPIKE=4, STEP=8, STUCK=16, PRE_DEPLOYMENT=32, NEIGHBOR_OUTLIER=64, TIMESTAMP_SUSPECT=128, MANUAL_EXCLUDE=256`. `QcFlag.DEFAULT_EXCLUDE` (311) is the default exclusion mask for indices. |
| `MeasurementSeries` | `sivin.core.schema` | Validated, immutable measurements of one sensor: `timestamp_utc` (`datetime64[ns, UTC]`, strictly increasing), `temp_c`, `rh_pct` (`float64`, `NaN` = missing), `qc` (`int32`), optional `source`. `to_frame()` adds `sensor_id` (long format). |
| `LocalTimeConverter` | `sivin.core.timeutil` | Local wall-clock → UTC with deterministic daylight-saving handling. **Input must be in source order, oldest first** (never sorted by local time); decreasing unambiguous rows raise `ValueError`. Each fall-back transition is resolved on its own; only a single backward jump of the wall clock resolves it, anything else (e.g. no jump, several jumps) is a best guess flagged `unresolved`. Nonexistent spring times are shifted by the gap. Ambiguous and nonexistent rows are `suspect`; a suspect row that would duplicate another UTC instant becomes `NaT` + `unresolved`. Callers drop the `NaT` rows before `MeasurementSeries.from_records`. Also local calendar dates and UTC bounds of a local day (23 h / 25 h days). |
| `DailyWeather` | `sivin.core.daily` | Daily min/mean/max of temperature and humidity per local calendar day. Each variable is aggregated over its own valid values (present and not excluded): `temp_n_samples`/`temp_coverage`, `rh_n_samples`/`rh_coverage`. `n_samples` and `coverage` equal the temperature columns; `coverage` (share of the real day length covered by valid samples) is the column of the site contract. |
| `MonthDay`, `Season` | `sivin.core.season` | Periods given by month and day (vegetation season, Huglin period, single months). |
| `ClimateIndex`, `IndexContext`, `IndexResult`, `IndexRegistry` | `sivin.analytics.base` | Extension point for indices: a new index is a subclass registered with `@index_registry.register`; parameters are frozen pydantic models. |
| defaults | `sivin.core.defaults` | Shared default values (time zone, nominal 1825 s interval, coverage thresholds) without heavy imports. |
| `SivinConfig` | `sivin.config` | `config/sivin.yaml` as frozen pydantic models (`extra="forbid"`): sections `paths`, `time`, `analytics`. |
| `ProjectPaths` | `sivin.paths` | Project root discovery; configuration paths are relative to it. |

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
