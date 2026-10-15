# SIVIN Meteostations

Data collection, quality control, climate indices and a public map portal for weather stations
in South Moravian vineyards (Dolní Věstonice). The stations measure air temperature and relative
humidity about every 30 minutes; precipitation and battery voltage are taken over as well.

**Portal:** <https://ricredi.github.io/SIVIN_Mateostations/>

**Author:** Richard Redina (195715@vut.cz), Brno University of Technology; International Clinical
Research Center, Brno. GitHub: [RicRedi](https://github.com/RicRedi)

## How it works

The data provider (`lemon.e-service.cz`) has no API, so the measurements are downloaded as
Excel/CSV exports with an automated browser. There is no server and no database:

```
provider portal ─► sivin fetch ─► ingest (parse, validate) ─► store (CSV on branch `data`)
                                                                   │
        web portal (GitHub Pages) ◄─ sivin build-site ◄─ indices ◄─ quality control
```

- A GitHub Actions workflow (`.github/workflows/pipeline.yml`) runs the whole chain every day at
  06:00 Europe/Prague and on demand. It keeps the measurements on the `data` branch and deploys
  the portal to GitHub Pages.
- The web page only reads pre-generated static JSON. Opening it never starts a workflow.
- The measured data are public; portal credentials are only in repository Secrets (`SIVIN_USER`,
  `SIVIN_PASSWORD`) or a local `.env`.

## What it does

- **Ingest:** Excel and CSV exports of the provider, validated (schema, timestamps, local time
  Europe/Prague converted to UTC); rejected files go to quarantine with a report.
- **Quality control:** missing values, range, spike, step, stuck sensor, sampling, precipitation
  and battery checks; a manually kept off-site log (`sensors/offsite_log.yaml`) marks periods
  when a sensor was not in the vineyard. A row missing temperature or humidity is invalid as a whole.
- **Sensor registry:** `sensors/sensors.geojson` with position history, municipality and vineyard
  track (two-level grouping), variety and status (`active` / `retired`).
- **Alignment:** pairing of series from several sensors with different clocks for comparison.
- **Climate indices** (each with a mathematical description and literature in
  [docs/indices/](docs/indices/)): growing degree-days / Winkler, Huglin, BEDD, growing-season
  temperature, Cool Night Index, diurnal range during ripening, heat hours, tropical days and
  nights, frost, winter freeze, budburst, GFV and GSR phenology models, dew point, VPD, botrytis
  (Broome) and powdery mildew (Gubler-Thomas) risk.
- **Map portal:** map of the sensors (OpenStreetMap, clustering of nearby markers), sensor picker
  with search grouped by municipality → vineyard track, comparison of up to 8 sensors in one
  temperature/humidity chart, sensor card with latest values and a button that copies the GPS
  position for navigation.

Not yet done (see [MIGRATION_PLAN.md](MIGRATION_PLAN.md) §4): indices on the web portal
(WP-3.4), admin mode for editing the registry and the off-site log on the web (WP-3.3),
publication plots and animations (WP-5.1) and removal of the legacy scripts (WP-5.2).

## Quick start

Requirements: Python 3.12, Chrome or Chromium (only for `sivin fetch`), Node 22 (only for the
web portal).

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev,ingest,viz]"   # or: make install
cp .env.example .env                 # fill in SIVIN_USER and SIVIN_PASSWORD
.venv/bin/sivin sensors check        # registry and off-site log
.venv/bin/sivin run                  # fetch -> ingest -> QC -> indices -> site data
.venv/bin/sivin run --skip-fetch     # the same without the provider portal
```

Main commands: `fetch`, `ingest`, `qc`, `indices`, `run`, `build-site`, `report`, `sensors`,
`config`. Options and exit codes: [docs/cli.md](docs/cli.md). All settings are in one file,
`config/sivin.yaml`: [docs/configuration.md](docs/configuration.md).

Local data are written to `data/` (ignored by git); in production they live on the `data` branch.

### Web portal

```bash
cd web && npm ci
npm run dev        # http://localhost:5173/SIVIN_Mateostations/ with synthetic demo data
```

Details: [docs/web.md](docs/web.md).

## Development

```bash
make lint type test     # ruff, mypy --strict, pytest
make cov                # tests with coverage (fails under 85 %)
cd web && npm run lint && npm run typecheck && npm test && npm run build
```

Standards and workflow: [CONTRIBUTING.md](CONTRIBUTING.md). Work is split into workpackages
(one branch and one pull request each) described in [MIGRATION_PLAN.md](MIGRATION_PLAN.md);
hand-off notes and reviews are in [docs/wp_log/](docs/wp_log/). Rules for AI agents working in
this repository: [CLAUDE.md](CLAUDE.md).

## Repository layout

```
src/sivin/        Python package (cli, app services, ingest, quality, registry, alignment,
                  analytics, storage, site, config, core contracts)
tests/            pytest suite with synthetic fixtures
web/              map portal (TypeScript, Vite, Leaflet, uPlot)
config/sivin.yaml configuration of the package
sensors/          sensor registry and off-site log (+ JSON schemas)
docs/             architecture, data formats, operations, indices and literature
.github/workflows ci.yml, web.yml (checks), pipeline.yml (daily run and deployment)
```

## Documentation

| Topic | Page |
|---|---|
| Architecture and data flow | [docs/architecture.md](docs/architecture.md) |
| Daily pipeline, GitHub Pages, Secrets, recovery | [docs/operations.md](docs/operations.md) |
| Command line and exit codes | [docs/cli.md](docs/cli.md) |
| Configuration reference | [docs/configuration.md](docs/configuration.md) |
| Downloading from the provider portal | [docs/ingest.md](docs/ingest.md) |
| Export and storage formats | [docs/data-format.md](docs/data-format.md), [docs/storage.md](docs/storage.md) |
| Sensor registry and off-site log | [docs/sensors.md](docs/sensors.md) |
| Quality control | [docs/quality-control.md](docs/quality-control.md) |
| Pairing of sensors | [docs/alignment.md](docs/alignment.md) |
| Climate indices and literature | [docs/indices/](docs/indices/), [docs/literature-verification.md](docs/literature-verification.md) |
| Static site data and web portal | [docs/site.md](docs/site.md), [docs/web.md](docs/web.md) |

## Legacy scripts

The original scripts in the repository root (`chrome_driver.py`, `vineyard_analyst.py`,
`one_variable_plot.py`, `two_variable_plot.py`, `rolling_stats.py`, `sampl_freq_basic.py`,
`generate_animation.py`) and their YAML files are superseded by the `sivin` package and kept only
as reference until WP-5.2 removes them. The plotting scripts are replaced by WP-5.1.

## License and attribution

Created by Richard Redina, Brno University of Technology, for academic and research use in
viticulture and agricultural monitoring. No open-source license has been chosen yet.
