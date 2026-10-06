# SIVIN Meteostations: measured data

This branch holds the measurements and pipeline results of the SIVIN vineyard weather
sensors. It has no common history with `main` and is written only by the workflow
`.github/workflows/pipeline.yml` (see `docs/operations.md` on `main`).

- `data/raw/<sensor_id>/<YYYY>.csv`: measurement store (docs/storage.md)
- `data/runs/<YYYY-MM-DD>.jsonl`: one record per pipeline run
- `data/derived/`: QC events, index results, incremental site build state
- `site/data/`: the static site data deployed to GitHub Pages (docs/site.md)

The data are public by decision of the owner.
