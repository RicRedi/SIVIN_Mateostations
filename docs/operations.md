# Operations: the daily pipeline and the GitHub Pages deployment

The workflow [`.github/workflows/pipeline.yml`](../.github/workflows/pipeline.yml) (WP-4.1)
collects the sensor data once a day, keeps them on the `data` branch and deploys the map portal
to GitHub Pages. There is no server and no database (MIGRATION_PLAN §2.3): opening the portal
never starts anything, it only downloads the JSON files of the last deployment.

> **Not verified yet.** The workflow was linted with actionlint and its decision steps were run
> locally against a local git repository and synthetic data, but it has **never run on GitHub**
> and never against the real portal. Use the [first-run checklist](#first-run-checklist).

## How a daily run works

```
 cron 04:00 UTC ─┐                     ┌─────────────────────── collect (contents: write) ────────────────────────┐
 cron 05:00 UTC ─┼─► gate ── 06:00 in ─►│ checkout main + data branch ─► sivin run ─► job summary ─► judge exit code │
 Run workflow ───┘    Prague today?     │   (create orphan              (fetch, ingest,  (sivin report)   0,1,4: commit │
                      no: stop          │    branch if missing)          QC, indices,                     + push data   │
                                        │                                site data)                       3,5,…: fail   │
                                        └──────────────────────────────────────────────┬───────────────────────────┘
                                                                                       ▼ data commit (SHA)
                     ┌──────────── build-site (contents: read) ─────────────┐    ┌──── deploy ────┐
                     │ checkout main + that data commit ─► sivin build-site ─┼──► │ deploy-pages   │──► GitHub Pages
                     │ (incremental) ─► site/data → web/public/data          │    │ (github-pages) │
                     │ ─► vite build (VITE_DEMO_DATA=false) ─► Pages artifact │    └────────────────┘
                     └───────────────────────────────────────────────────────┘
```

1. **Schedule.** GitHub's cron is in UTC, and 06:00 in Prague is 04:00 UTC in summer (CEST)
   and 05:00 UTC in winter (CET). The workflow has both crons; the **gate** job lets through
   only the cron that is 06:00 local time on that day: it reads today's UTC offset of
   Europe/Prague (`TZ=Europe/Prague date +%z`) and compares `6 − offset` with the cron that
   fired (`github.event.schedule`). Exactly one run per day, also on the days of a
   daylight-saving change (the change happens at 01:00 UTC, before both crons). Comparing the
   cron rather than the current hour (`TZ=Europe/Prague date +%H`, logged for information) keeps
   this true when GitHub starts a scheduled run late: a run delayed past the full hour would
   otherwise be skipped, and the other cron could run twice. Manual runs always pass the gate.
2. **collect** checks out `main` (the code, `config/sivin.yaml`, `sensors/`) and the `data`
   branch into `.data-branch/`, copies its `data/` and `site/` into the working directory, so
   every path is exactly as in a local checkout, installs `sivin` (`pip install ".[ingest]"`,
   Python 3.12) and runs

   ```
   sivin --log-level INFO run [--skip-fetch]
   ```

   with `SIVIN_USER` and `SIVIN_PASSWORD` from the repository secrets. Chrome and chromedriver
   come from the runner image (`$CHROMEWEBDRIVER`, [ingest.md](ingest.md)). `sivin run` fetches,
   ingests, checks, computes the indices of the current season and builds `site/data`
   incrementally, then appends one run record ([cli.md](cli.md#sivin-run)). The log level is
   always INFO: the more verbose level is never used in Actions.
3. **Job summary.** `sivin report --format markdown --run latest --since <start> --outcome
   <code>` writes the summary of this run to the job page (see [below](#reading-the-job-summary)).
   It runs whatever happened before; with `--since` it never shows yesterday's record for a
   run that wrote none.
4. **Exit code.** 0 and 1 continue; 4 (portal unavailable) continues with the stored data and
   marks the run with a warning; anything else (3, 5, 130, …) fails the job **after** the
   summary was written, and nothing is committed or deployed.
5. **Commit.** The changed files are copied back into `.data-branch/` and committed as
   `github-actions[bot]` with a message like `data: run of 2026-10-05, 94 new rows from 4
   files, 0 failures (exit code 0)`, then pushed with a plain `git push` (never forced). No
   change, no commit. A rejected push (someone else pushed to `data` meanwhile) fails the job
   and nothing is lost; run the workflow again.
6. **build-site** checks out `main` and exactly the data commit of this run, runs `sivin
   build-site` (incremental: every sensor is reused from the committed `site/data` and its
   build state, so it only refreshes the manifest and repairs missing files), replaces the
   synthetic demo fixture `web/public/data/` with `site/data/`, builds the web with
   `VITE_DEMO_DATA=false` (no "demo data" badge) and `SITE_BASE=/<repository name>/`, and
   uploads the Pages artifact. Web and data of the same commit are always deployed together
   (required since WP-3.2, see its hand-off note).
7. **deploy** publishes the artifact with `actions/deploy-pages` to the `github-pages`
   environment.

Only one run at a time (`concurrency: pipeline`, never cancelled). A run started while another
is running waits; if a third one arrives, GitHub cancels the waiting one (only one waits).

**Permissions.** The workflow grants nothing by default. `collect` gets `contents: write` (to
push `data`), `build-site` `contents: read`, `deploy` `pages: write` and `id-token: write`.
The secrets reach only two steps of `collect`, as environment variables; `sivin` replaces their
values by `***` in everything it prints and writes ([cli.md](cli.md#exit-codes), *Logging and
secrets*), including the job summary. Never add `set -x` to a step that has them.

### The `data` branch

An orphan branch (no common history with `main`), written only by the workflow. The first run
creates it with a `README.md` and a `.gitignore`.

```
README.md
.gitignore                         ignores data/downloads/, data/quarantine/, temporary files
data/raw/<sensor_id>/<YYYY>.csv     measurement store (storage.md)
data/runs/<YYYY-MM-DD>.jsonl        one record per run (files, rows, validation, failures)
data/derived/events/<id>.json       QC events
data/derived/indices/<season>.json  index results
data/derived/site-build-state.json  incremental site build state (site.md), never deployed
site/data/...                       the published site data (site.md)
```

**`site/data` is committed with the data** so that the incremental build has its previous
output (without it every run would be a full build, WP-3.2) and so that any commit of `data` can
be deployed as it is (rollback, below). The `.gitignore` of `main` ignores `/data/` and
`/site/`; the `.gitignore` of the `data` branch does **not**.

**Not committed:**

- `data/downloads/`: every run downloads the full exports again; their content is in the store
  and their names are in the run record.
- `data/quarantine/` (**decision of WP-4.1**): `sivin ingest` moves a rejected export there with
  its `<file>.report.json`. On the `data` branch every daily run would add another dated copy
  of a persistently bad export (a fresh runner starts empty), so the public history would grow
  without bound. Instead the rejected files are listed in the job summary and the run record,
  and the validation reports (`*.report.json`: rule, severity, message, row — no credentials,
  no machine paths) are kept for **14 days** as the run artifact `run-summary-<run id>-<attempt>`
  together with the summary. The rejected export itself is not uploaded (artifacts get only the
  summary and the reports); to inspect it, download the export once from the portal or run
  `sivin fetch` / `sivin ingest --quarantine-mode copy` locally.

## One-time setup (owner)

1. **Make the repository public** (Settings → General → Danger Zone → Change visibility). Data
   are public by decision of 2026-10-05; Pages from a private repository needs a paid plan.
2. **Pages source = GitHub Actions** (Settings → Pages → Build and deployment → Source:
   *GitHub Actions*). This creates the `github-pages` environment that the `deploy` job uses.
3. **Secrets** `SIVIN_USER` and `SIVIN_PASSWORD` (Settings → Secrets and variables → Actions →
   New repository secret). Values of at least 4 characters (shorter ones cannot be redacted,
   [cli.md](cli.md#exit-codes)).
4. Nothing else: the workflow sets its own token permissions, so the repository default
   "Workflow permissions: read" is fine. Branch protection on `main` does not affect the
   pipeline (it pushes only to `data`); do not protect `data` against pushes by Actions.

## First-run checklist

The workflow file must be on the default branch before the *Run workflow* button appears.

1. Actions → **pipeline** → *Run workflow* with **skip_fetch** ticked. Expected: `collect`
   creates the `data` branch (notice "Branch 'data' does not exist yet"), the summary says
   "No rows were added", `build-site` and `deploy` succeed. The portal is then online at
   `https://<owner>.github.io/<repository>/` with the registry but no measurements (site data
   with an empty manifest; verified locally, but how the web shows an empty manifest was not
   checked in a browser).
2. *Run workflow* without options. Expected: the summary lists one export file per sensor and
   the rows added per sensor; exit code 0 or 1. If it says `DATA_SOURCE_UNAVAILABLE` (4), check
   the secrets and the job log (login, chromedriver). Commit on `data`:
   `data: run of …, N new rows from M files, …`.
3. Open the portal: the "demo data" badge is gone, the sensors have values, the chart shows the
   real series. Check one value against the portal.
4. *Run workflow* again without options. Expected: about 0 new rows (only samples measured since
   the previous run), rows mostly `identical_skipped`; `site/data` mostly reused.
5. The next morning: exactly one scheduled run, started after 06:00 Prague time (one of the
   two crons ends in the gate with "Not the 06:00 local cron today").
6. Report to the agents what differed (portal behaviour, export names, timings).

## Running it by hand

Actions → **pipeline** → *Run workflow* (branch: the default branch), or with the GitHub CLI:

```console
$ gh workflow run pipeline.yml                          # like the daily run
$ gh workflow run pipeline.yml -f skip_fetch=true       # no portal: re-process and redeploy
$ gh workflow run pipeline.yml -f full_site_build=true  # rebuild all site data
$ gh run watch                                          # follow it
```

- **skip_fetch** does not log in: the stored data are checked again, the indices and the site
  are rebuilt and deployed. Use it after editing the registry or the off-site log, or when the
  portal is down.
- **full_site_build** runs `sivin run --skip-site` and then `sivin build-site --full`: every
  sensor is rebuilt, ignoring the build state (the result is byte-identical to an incremental
  build; use it if the site data look inconsistent).

The pipeline always runs the code of the default branch (`main`).

## Reading the job summary

Open the run (Actions → pipeline → the run) and scroll to the summary. It shows:

- **Outcome** — the exit code of `sivin run` and what it means;
- the start (UTC and Prague time) and duration;
- a table: export files processed, files rejected, rows added, other failures, warning kinds;
- **Rows added per sensor** — new rows, filled values, conflicting and replaced values;
- **Input validation findings** — counts per `<severity>:<rule>` ([data-format.md](data-format.md));
- **Rejected files** — the reason; the report is in the run artifact;
- **Failures** — devices not downloaded, sensors or indices that failed (`fetch …`, `qc …`,
  `indices …`, `site …`);
- **Derived results not updated** — events files whose QC failed (the previous result is kept);
- **Export files** — the processed files;
- **Warnings** — QC warnings over each sensor's whole stored record, one row per sensor and
  kind, most recent first: `low_battery` (change the battery), `unlogged_off_site` (the data
  look like an indoor period that the off-site log does not cover: add an entry to
  `sensors/offsite_log.yaml` if the sensor was indeed off site), `irregular_sampling`, `gap`, …

The same report is available locally: `sivin report` (text) or `sivin report --format markdown`;
`--run 2026-10-05` selects the last run of that UTC day.

### Exit codes and what to do

| Code | Job | Meaning | What to do |
|---|---|---|---|
| 0 `OK` | green | everything worked | nothing |
| 1 `PARTIAL_FAILURE` | green, warning | a file rejected, a device not downloaded, a sensor or index failed; everything else was processed and published | read *Rejected files* / *Failures*; one-off failures (a timeout) fix themselves on the next run |
| 4 `DATA_SOURCE_UNAVAILABLE` | green, warning | the portal could not be used (secrets missing, login failed, portal or browser unreachable); the stored data were processed and published again | check the secrets; if the portal changed, see below; the data are safe |
| 3 `SETUP_ERROR` | **red** | invalid `config/sivin.yaml`, sensor registry or off-site log: nothing processed, nothing committed, the site stays as it was | the job log names the file, entry, line and field; fix it on `main` (`sivin sensors check` locally) and run the workflow |
| 5 `INTERNAL_ERROR` | **red** | a bug (the traceback is in the job log, credentials redacted) | report it; nothing was committed |
| 130, other | **red** | interrupted or unexpected | run again; report if it repeats |

A red `collect` job means nothing was committed and nothing deployed: the portal keeps the
previous data, and after 36 h the web marks the sensors as stale (`site.stale_after_s`).

## When the portal changes or fails

- **Symptoms:** exit code 4 (login, device list) or 1 with `fetch <device>: …` failures
  (export button, download timeout) on every run.
- **The data are safe:** a portal failure never deletes stored data; the run still processes
  and publishes what is stored.
- **Diagnose locally:** `sivin fetch --headed` shows the browser; [ingest.md](ingest.md) lists
  the error types and the configuration keys (`ingest.portal.selectors`,
  `ingest.portal.timeouts`) to adjust. A changed export format shows up as *Rejected files* with
  the validation findings; the report in the run artifact names the rule
  ([data-format.md](data-format.md)).
- Fix the configuration (or the code) on `main`, then run the workflow by hand.

## Editing the sensor registry and the off-site log

Both files live on `main` and are edited there, for example directly in the GitHub web editor:

- `sensors/sensors.geojson` — add, move or retire a sensor ([sensors.md](sensors.md));
- `sensors/offsite_log.yaml` — periods when a sensor was not in the vineyard
  ([sensors.md](sensors.md), MIGRATION_PLAN §2.8).

Check them locally first with `sivin sensors check` if you can. After the commit, either wait
for the next daily run or start one with **skip_fetch**. A change of either file (or of the
configuration) changes the shared inputs of the site build, so the next run rebuilds all site
data and the change is visible on the portal after that run (e.g. a new off-site period appears
as a grey band, its samples drop out of the indices). An invalid file stops the run with exit
code 3 and nothing is published until it is fixed — by design, better no update than wrongly
flagged data.

## Recovering and rolling back the `data` branch

Never force-push `data`; every change is a new commit, so everything can be undone.

- **Undo one bad run** (e.g. a wrong import): revert its commit and push.

  ```console
  $ git fetch origin data && git switch data
  $ git log --oneline -5                    # find the commit "data: run of …"
  $ git revert <sha> && git push origin data
  ```

  Then run the workflow with **skip_fetch** to redeploy. Note that the next run with fetch
  imports the portal's exports again: rows that are still in the export come back (the store
  only adds and fills, [storage.md](storage.md)). To keep them out, fix the cause first (the
  off-site log, `MANUAL_EXCLUDE`, or the parser).
- **Return to an older state:** `git checkout <good sha> -- data site`, commit, push, then
  run with **skip_fetch**.
- **Lost or broken `site/data` or build state:** run with **full_site_build**.
- **Redeploy an older state without changing `data`:** re-run the `build-site` and `deploy`
  jobs of an older workflow run (Actions → that run → *Re-run jobs*); `build-site` checks out the
  data commit of that run (with the code of the current `main`).
- **Start over** (destructive, only if the history is truly unusable): delete the `data` branch
  on GitHub; the next run creates it again from the portal exports. Measurements that are not
  in the portal's exports any more are then lost — keep a copy (`git clone --branch data`)
  first.

## Scheduled workflows and the 60-day rule

GitHub disables scheduled workflows of a **public** repository after 60 days without
repository activity; a disabled workflow shows a banner in the Actions tab and is re-enabled
with *Enable workflow* (or `gh workflow enable pipeline.yml`).

**Not verified:** whether the daily pushes of `github-actions[bot]` to the `data` branch count
as activity. GitHub's documentation does not define "activity" precisely, and it could not be
tested here. Every successful run commits to `data` (the derived files carry the run time, so
there is always a change), which may well keep the repository active, but do not rely on it:

- check the Actions tab after about two months without commits to `main`;
- any commit to `main` (e.g. an off-site log entry) certainly counts as activity;
- if the workflow does get disabled, a small keep-alive step (re-enabling the workflow through
  the API with `actions: write`) can be added; that is a proposal for the owner, not part of
  WP-4.1.

## Costs and limits

- **Actions minutes:** standard GitHub-hosted runners are free for public repositories. A run
  takes a few minutes (installing Python and Node dependencies dominates while there are few
  sensors); the job timeouts are 5 (gate), 45 (collect), 20 (build-site) and 10 (deploy) minutes.
- **Schedule:** scheduled runs can start late when GitHub is under load (the full hour is the
  busiest time), and under very high load a scheduled run can be dropped. The gate tolerates
  delays; a dropped run is simply missing for that day, and the next one catches up as long as
  the portal's export still covers the missed samples (the one real export seen so far covered
  seven months; whether every export always holds the whole history is not verified).
- **Pages:** a published site may be at most 1 GB, with a soft bandwidth limit of 100 GB per
  month. The site data were about 7 MB for 4 sensors and one year (WP-3.2); far below the limit.
- **Repository size:** each year file of the store and the published monthly/daily files of
  the current period are rewritten daily; git stores the versions as compressed deltas. Expect
  the `data` branch to grow by some tens of MB per year with tens of sensors
  ([storage.md](storage.md#growth-estimate)). If it ever becomes large, the history of `data`
  can be squashed by the owner (a deliberate, one-off rewrite agreed beforehand).
- **Artifacts:** the run summary and quarantine reports are kept for 14 days; the Pages artifact
  is handled by GitHub.
