# WP-4.1 — Automation: daily pipeline and GitHub Pages deployment

## Summary

`.github/workflows/pipeline.yml` runs the whole pipeline once a day at 06:00 Europe/Prague (two
UTC crons, 04:00 and 05:00, and a gate job that lets exactly one through) and on demand
(`workflow_dispatch` with `skip_fetch` and `full_site_build`). Job `collect` checks out `main`
and the orphan `data` branch (created on the first run with its own README and `.gitignore`),
runs `sivin --log-level INFO run`, writes the job summary with the new command `sivin report`,
maps the exit code (0/1 continue, 4 continue with a warning, anything else fails after the
summary without pushing) and commits the store, run records, derived files, site build state
and `site/data` to `data` as `github-actions[bot]` (never forced, no empty commits). Job
`build-site` checks out the data commit of this run, runs `sivin build-site` (incremental),
replaces the demo fixture with the real site data and builds the web with `VITE_DEMO_DATA=false`
and the Pages base path; job `deploy` publishes it with `actions/deploy-pages`. `sivin report`
(`--format markdown|text`, `--run latest|YYYY-MM-DD`, `--since`, `--outcome`) summarises a run
record and the current QC warnings (incl. `low_battery` and `unlogged_off_site`), redacted.
actionlint runs in CI. `docs/operations.md` is the owner's manual.

## Changed files

- `.github/workflows/pipeline.yml` (new) — the workflow.
- `.github/workflows/ci.yml` — new job `workflows`: `actionlint` (pinned `actionlint-py==1.7.12.25`;
  shellcheck of the runner image).
- `src/sivin/app/summary.py` (new) — `RunSummaryService`, `RunRecordFinder`, `RunSelection`,
  `WarningCollector`, `RunSummary`, `WarningGroup`, `DerivedFailure`, `RunOutcome`/`ExitStatus`,
  `FailureKind` + `classify_failure`, `SummarySettings` (frozen pydantic, `extra="forbid"`).
- `src/sivin/app/summary_formats.py` (new) — `SummaryFormat` ABC (template method over the
  primitives heading/text/table/items) registered in `summary_format_registry`
  (`NamedRegistry` of `sivin.storage.registry`): `MarkdownSummary` (`markdown`), `TextSummary`
  (`text`); `markdown_text` escaping.
- `src/sivin/app/factory.py` — `ServiceFactory.summary_service()`.
- `src/sivin/cli/commands/summary.py` (new), `src/sivin/cli/main.py` — command `sivin report`.
- `tests/app/test_summary.py`, `tests/cli/test_report.py`,
  `tests/workflows/test_pipeline_workflow.py` (new).
- `docs/operations.md` (new), `README.md` (one "Operations" paragraph), this note.

### Public API

```text
sivin report [--format markdown|text] [--run latest|YYYY-MM-DD] [--since ISO] [--outcome CODE]
  exit 0; 2 for an unknown format or an invalid --run/--since; 3 outside a project or with an
  invalid configuration. Writes nothing.

RunSummaryService(finder, warnings, display_timezone, settings=None, redact=None)
    .summarise(selection: RunSelection, outcome: RunOutcome | None = None) -> RunSummary
summary_format_registry.create("markdown" | "text").render(summary) -> str
```

## How it was verified

In `/home/user/wt/wp-4.1` (Python 3.12 `.venv`):

- `make lint` → ruff check: all checks passed; ruff format: 295 files already formatted.
- `make type` → `Success: no issues found in 179 source files`.
- `make test` / `make cov` → **1939 passed**; total coverage 99.83 %. New/changed code:
  `app/summary.py` 100 %, `app/summary_formats.py` 100 %, `cli/commands/summary.py` 100 %,
  `cli/main.py` 100 %, `app/factory.py` 99 % (the one missed line, 143, is pre-existing).
- `actionlint 1.7.12` with `shellcheck 0.11.0` (installed from PyPI into a scratch venv, not into
  the project) over all three workflows → no findings.
- `tests/workflows/test_pipeline_workflow.py` parses the workflow and checks: two crons, the
  dispatch inputs, concurrency, permissions per job, no `DEBUG`/`set -x`, every `sivin` call at
  `--log-level INFO`, exactly one `git push` and no `force`, actions pinned to a major version,
  timeouts, secrets only in the env of the two `collect` steps that need them, artifact paths
  (no downloads), `VITE_DEMO_DATA=false`, the base path, deploy environment. It also
  **executes** with bash: the gate (summer/winter × both crons, delayed runs, manual runs, with a
  fake `date`), the exit-code judgement (0, 1, 4 publish; 2, 3, 5, 130, empty do not), and the
  data-branch step against a local bare repository (orphan creation with README/.gitignore,
  checkout of an existing branch).
- Local end-to-end simulation (scratch script, not committed): the shell steps of `collect`
  and `build-site` extracted from the YAML and run in order against a local bare "origin", with
  the real `sivin` on SYNTHETIC exports: first run creates `data` and commits
  (`data: run of 2026-10-05, 94 new rows from 1 files, 0 failures (exit code 0)`), second run
  incremental site build and commit, a `full_site_build` run (`--skip-site` + `build-site --full`),
  the `build-site` step reusing every sensor from the committed state; exit 4 (no credentials)
  → summary `DATA_SOURCE_UNAVAILABLE`, warning, publish; exit 3 (broken off-site log) →
  summary "No run record of this run", no publish; a first run on an empty store commits a
  site with manifest, latest and registry only.
- `npm ci && VITE_DEMO_DATA=false SITE_BASE=/SIVIN_Mateostations/ npm run build` on a scratch
  copy of `web/` with the simulated `site/data` in `public/data` → build OK, `dist/data` holds
  the real site data.

## What did not work / what was not verified

- **The workflow never ran on GitHub** (nothing is pushed; Pages, the environment, secrets,
  OIDC for `deploy-pages`, `$CHROMEWEBDRIVER` on the runner, `github.event.schedule` values,
  push permissions of `GITHUB_TOKEN` to `data` were not exercised). `docs/operations.md` has a
  first-run checklist for the owner.
- **Never against the real portal** (as all agent work).
- **60-day rule:** whether daily bot pushes to the non-default `data` branch count as
  repository activity is not verifiable here and not defined by GitHub's documentation;
  documented as unverified with mitigations (docs/operations.md).
- How the web renders a site with an empty manifest (first run with no data) was not checked in
  a browser.
- Whether each portal export always holds the device's whole history (relevant for catching up
  after a missed day and for "start over") is not known; documented as unverified.
- `actionlint` in CI is configured but has not run in CI.

## Deviations

1. **Gate compares the cron, not only the hour.** The brief says: continue when
   `TZ=Europe/Prague date +%H` is 06. That check skips a scheduled run that GitHub starts more
   than an hour late (both crons would then see 07/08 → no run that day) and lets both through
   if the wrong cron is delayed by an hour (two runs). The gate therefore computes today's
   Prague UTC offset (`TZ=Europe/Prague date +%z`) and continues only for the cron
   `0 (6 − offset) * * *` that fired (`github.event.schedule`); the local hour is still logged.
   Exactly one run per day across DST, also when delayed. Tested with a fake `date`.
2. **The site data are built in `collect` and committed to `data`.** `sivin run` builds
   `site/data` incrementally as its last step (it reuses the QC results), so `collect` commits
   `site/data` together with the build state; without the previous output on the runner every
   run would be a full build (WP-3.2 note), and every `data` commit is then deployable as it is
   (rollback). `build-site` still runs `sivin build-site` as the brief asks, incrementally on
   that commit (every sensor reused; it refreshes the manifest and repairs missing files), but
   its state is not committed. With `full_site_build` the full rebuild happens in `collect`
   (`sivin run --skip-site` + `sivin build-site --full`) so that the committed state is the full
   one; `build-site` then reuses it.
3. **Data branch layout and checkout.** The branch holds `data/` and `site/data/` (as in a
   project checkout). It is checked out as a git worktree in `.data-branch/` and its contents are
   **copied** into `data/` and `site/` of the `main` checkout and back after the run, instead of
   pointing `paths.data_dir` elsewhere with a config override or a symlink: every path (run
   record, quarantine `source_path`, error texts, build state) stays exactly as locally, and no
   configuration differs between local runs and Actions.
4. **Quarantine is not committed** (decision asked for in the brief). With `move` a rejected
   export lands in `data/quarantine/`; since every run downloads the exports again on a fresh
   runner, a persistently bad export would add a new dated copy to the public history every day.
   The `data` branch `.gitignore` ignores `data/quarantine/` and `data/downloads/`; the
   validation reports (`*.report.json`) are uploaded with the summary as a 14-day artifact; the
   rejected exports themselves are not uploaded (brief: "only the run summary and quarantine
   reports, not the downloads").
5. **Checkout of the default branch.** Both jobs check out `github.event.repository.default_branch`
   (= `main`), so a manual run started from another branch still uses the code of `main`.
6. **`sivin report` command name and location.** Command module `cli/commands/summary.py`
   (`cli/commands/report.py` already exists for the plain-text echo helpers); default format
   `text` for local use, the workflow passes `--format markdown`.

## Out of scope

- `docs/cli.md` should list `sivin report` (options, exit codes) and link
  `docs/operations.md`; `docs/architecture.md` could mention the summary service. Not in my
  Files scope; `docs/operations.md` documents the command meanwhile.
- `src/sivin/storage/runlog.py`: a public `RunLog.days()` would let `RunRecordFinder` stop
  globbing `runs/*.jsonl` itself.
- `RunRecord` does not record warnings or the exit code; the summary reads the warnings from
  the derived events files (whole record, not "new in this run"). A future `RunRecord.outcome`
  and per-run warning counts would let the summary say what is new.
- With `full_site_build`, failures of `sivin build-site --full` appear in the job log but not in
  the run record (it was written by `sivin run --skip-site` before). A `sivin run --full-site`
  option (CLI/app change of WP-1.7/3.2) would put them into the record.
- `web/public/data/README.md` (synthetic fixture note) is deleted on the runner together with
  the fixture; nothing to change, mentioned for completeness.

## Open questions for the owner

1. **Configuration section `report`.** `SummarySettings` (`max_items`, default 50, items per
   section of the summary) lives in `sivin.app.summary`; proposed wiring into `SivinConfig` as
   section `report:` by the integration WP. Needed? (The default works without it.)
2. **Quarantine on the `data` branch:** keep the decision above (not committed, reports as a
   14-day artifact), or also upload the rejected export files to the artifact for debugging?
3. **Keep-alive for the 60-day rule:** add a step that re-enables the workflow through the API
   (`actions: write`) if the schedule ever gets disabled, or rely on the daily `data` commits and
   the Actions banner?
4. **Gate deviation** (see Deviations 1): accept the cron comparison instead of the plain hour
   check?
5. **`site/data` committed to `data`** (Deviations 2): accept the extra history (a few hundred
   KB of changed JSON per day with 4 sensors, stored as deltas)?

## Review
Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
