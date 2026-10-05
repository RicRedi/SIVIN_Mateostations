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
(`--format markdown|text|json`, `--run latest|YYYY-MM-DD`, `--since`, `--outcome`) summarises a run
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
  (`text`) as `DocumentFormat`s, and `JsonSummary` (`json`, counts for the commit message);
  `markdown_text` escaping (also `$` and bare links).
- `src/sivin/app/factory.py` — `ServiceFactory.summary_service()`.
- `src/sivin/cli/commands/summary.py` (new), `src/sivin/cli/main.py` — command `sivin report`.
- `tests/app/test_summary.py`, `tests/cli/test_report.py`,
  `tests/workflows/test_pipeline_workflow.py` (new).
- `docs/operations.md` (new), `README.md` (one "Operations" paragraph), this note.

### Public API

```text
sivin report [--format markdown|text|json] [--run latest|YYYY-MM-DD] [--since ISO] [--outcome CODE]
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
5. **Checkout of the default branch.** (Round 2: replaced by the triggering ref, see Review.) Both jobs checked out `github.event.repository.default_branch`
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

## Round 2 (review findings)

All nine findings are fixed (Status column below). Changes:

- `pipeline.yml`: base path from `GITHUB_REPOSITORY` with an `::error::` guard; no
  `github.event.repository` (checkouts use the triggering ref); job-level concurrency in three
  groups (deviation from "one shared group", reason in the table and in a workflow comment);
  commit step enforces the exclusions independent of the branch `.gitignore` (rules now in the
  workflow env `DATA_BRANCH_GITIGNORE`: `/data/downloads/`, `/data/quarantine/`, `*.tmp`,
  `.env`), takes the counts from `sivin report --format json --since <start>` with a fallback
  message, and explains a rejected push; `build-site` copy-in under `set -euo pipefail`.
- `sivin report --format json` (`JsonSummary`); `SummaryFormat.render` is now abstract and the
  shared document template lives in `DocumentFormat` (Markdown, text).
- `markdown_text`: `$` escaped, URLs and `www.` addresses as inline code.
- `docs/operations.md`: rollback with `git restore --source=<good sha> --staged --worktree --
  data site`, concurrency semantics, base path, commit exclusions and message, manual runs use
  the chosen branch, checklist step 5 "open the portal after the scheduled run".
- Tests: bash runs of the build step (valid/empty/slash-less `GITHUB_REPOSITORY`, fake `npm`),
  of the commit step (deleted `.gitignore` → only store/derived/site files committed; unusable
  report → message without counts; concurrent push → `::error::`, exit 1), and of the
  documented rollback command; JSON format and link/math escaping.
- Local simulation (scratch, as in round 1): `.gitignore` removed from `data`, then a run with a
  rejected export → committed tree without `data/downloads` and `data/quarantine`, `.gitignore`
  written again, message `data: run of 2026-10-05, 94 new rows from 2 files, 1 rejected, 0
  other failures (exit code 1)`; `build-site` step OK.

Gates after round 2 (in `/home/user/wt/wp-4.1`): `make lint` → all checks passed; `make type`
→ no issues in 179 source files; `make cov` → **1951 passed**, total 99.83 %;
`app/summary.py`, `app/summary_formats.py`, `cli/commands/summary.py` 100 %; actionlint
1.7.12 + shellcheck 0.11.0 → no findings.

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer agent, 2026-10-05. Reviewed `ea87c92...d21cdee` by reading and by
local simulation; nothing was run on GitHub or against the portal.

### Gates (observed in `/home/user/wt/wp-4.1`)

- `make lint` → ruff check: all checks passed; ruff format: 295 files already formatted.
- `make type` → `Success: no issues found in 179 source files`.
- `make test` → 1939 passed. `make cov` → 1939 passed, total 99 %; `app/summary.py` 100 %,
  `app/summary_formats.py` 100 %, `cli/commands/summary.py` 100 %, `app/factory.py` 99 %
  (missed line 143 is pre-existing).
- `actionlint 1.7.12` (+ `shellcheck-py`, throwaway venv in `/tmp/claude-0/review-4.1`) over all
  workflows → no findings.

### Own checks

- **Cron gate:** the gate script extracted from the YAML was executed with a fake `date` for every
  day of 2026, both crons (`0 4 * * *`, `0 5 * * *`) and start delays of 0, 30, …, 180 min:
  exactly one `run=true` per day and delay, always for the cron that is 06:00 in Prague
  (365 days, 0 deviations; DST days 2026-03-29 and 2026-10-25 included).
- **Local end-to-end** (bare repo as origin, shallow clone as the runner, the step scripts
  extracted from the YAML, the real `sivin`, SYNTHETIC export from `tests/app/project.py`):
  first run creates the orphan `data` branch with README/.gitignore and pushes; second run
  commits on top (shallow fetch is fine); a run with a SYNTHETIC 2-day export commits
  `94 new rows from 1 files`; the `build-site` step on the pushed SHA reuses the sensor and
  fills `web/public/data`; a concurrent push to `data` between checkout and commit makes the
  plain `git push` fail (non-fast-forward, step exit 1, nothing forced).
- `sivin build-site` works from a plain `pip install .` (no `ingest` extra, no selenium).
- `sivin report` with a malformed run-log line (skipped with a warning), without `data/runs`
  (prints the no-record text), with odd event documents (non-dict events, non-string fields,
  `|`/`<b>` in the sensor id) → exit 0, well-formed table. Redaction-before-escaping is tested
  with a password containing `_*|` (`tests/cli/test_report.py:125`), and it is applied in the
  service before any format escapes (`summary.py:550-566`).

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | .github/workflows/pipeline.yml:305 | `SITE_BASE: /${{ github.event.repository.name }}/` is very likely empty on the daily `schedule` runs (the schedule event payload carries `schedule`/`workflow`, not `repository`; not verifiable here). Verified locally: with an empty name, `SITE_BASE=//` and Vite emits `src="//assets/index-….js"` (protocol-relative URL to host `assets`) → every scheduled deploy would publish a blank site; manual runs would be fine, so the first-run checklist would not catch it until the next morning. | fixed (round 2): base path from `GITHUB_REPOSITORY` (`${GITHUB_REPOSITORY#*/}`) in the build step, which fails with `::error::` for an empty/invalid value; no event payload anywhere (`github.event.repository` absent, tested); bash test with a fake `npm` for valid, empty and slash-less values |
| minor | .github/workflows/pipeline.yml:115-121, 205-217 | Exclusion of `data/downloads/` and `data/quarantine/` relies only on the `.gitignore` committed once to the `data` branch; the copy-out copies the whole `data/` and runs `git add -A`. Verified: after removing `.gitignore` from `data`, the next run committed `data/downloads/MeteoData_….csv` and the quarantined files to the public branch. | fixed (round 2): the commit step removes `data/downloads`, `data/quarantine`, `*.tmp`, `.env` from the copy, adds with exclude pathspecs, `git rm --cached --ignore-unmatch` on the same paths, rewrites a missing `.gitignore` (rules in the workflow env `DATA_BRANCH_GITIGNORE`, also `*.tmp` and `.env`); pytest runs the step with the branch `.gitignore` deleted and asserts the committed tree; the local simulation (deleted `.gitignore`, rejected export in quarantine) committed neither |
| minor | .github/workflows/pipeline.yml:27-29 | Workflow-level `concurrency` also covers the no-op gate run. GitHub keeps one pending run per group and cancels the older pending one, so the no-op cron an hour later (or any later trigger) cancels a real run (scheduled or manual) still waiting behind a long run. | fixed (round 2) with a deviation: concurrency on the jobs after the gate, but three groups (`pipeline-data`, `pipeline-pages`, `pipeline-deploy`) instead of one shared group: with one group, the next job of a finished run (queued when its predecessor ends) would cancel the pending `collect` of a newer run — the same problem in another place. Semantics in a workflow comment and docs/operations.md; tested |
| nit | .github/workflows/pipeline.yml:84, 256 | `ref: ${{ github.event.repository.default_branch }}` has the same empty-on-schedule issue; harmless (checkout falls back to the triggering ref = default branch), but fix together with the major. | fixed (round 2): no `ref:` (triggering ref; schedule = default branch); documented for manual runs |
| nit | .github/workflows/pipeline.yml:225 | A rejected push fails with git's generic hint only; an `::error::` line ("data branch changed meanwhile, re-run the workflow") would match docs/operations.md step 5. | fixed (round 2): `::error::` with cause and what to do; tested with a concurrent push in a local repository |
| nit | .github/workflows/pipeline.yml:278-282 | In `build-site` the copy-in of the data commit runs under `set +e`, so a failed `cp` is ignored. | fixed (round 2): `set -euo pipefail`; only `sivin build-site` is allowed to fail (`|| code=$?`) |
| nit | .github/workflows/pipeline.yml:211-215 | Commit-message counts come from the last line of the newest run-log file without the `--since` check of the summary; a malformed last line fails the commit step via `jq`. | fixed (round 2): counts from the new `sivin report --format json --run latest --since <start>`; any failure (no record, bad JSON, jq) falls back to `data: run of <date> (exit code N)`; tested |
| nit | src/sivin/app/summary_formats.py:252 | `markdown_text` does not neutralise GFM autolinks (bare `https://…`, `www.…`) or `$…$` math; texts come from the pipeline's own messages, so low risk. | fixed (round 2): `$` escaped; `scheme://…` and `www.…` rendered as inline code (not linked); tests |
| nit | docs/operations.md:254 | `git checkout <good sha> -- data site` keeps files added after `<good sha>` (e.g. a new year file); `git rm -r -q data site && git checkout <good sha> -- data site` restores the state exactly. | fixed (round 2): `git restore --source=<good sha> --staged --worktree -- data site` from a clean tree; pytest runs the documented command and checks that a later file is removed and the tree equals `<good sha>` |

Suggested fixes:

1. (major) Derive the base path without the event payload, e.g. in the build step
   `SITE_BASE="/${GITHUB_REPOSITORY#*/}/" npm run build`, or take `base_path` from
   `actions/configure-pages` (also correct with a custom domain); use `github.event.repository.default_branch`
   nowhere, or drop `ref:` (schedule and dispatch from `main` already check out `main`). Adjust
   `tests/workflows/test_pipeline_workflow.py:280`.
2. (minor) Enforce the exclusion in the workflow: after `cp -a data "$DATA_WORKTREE/data"`,
   `rm -rf "$DATA_WORKTREE/data/downloads" "$DATA_WORKTREE/data/quarantine"` (paths from config
   or constants), or rewrite the branch `.gitignore` on every run, or `git add` explicit paths;
   add it to the workflow test.
3. (minor) Put `concurrency: {group: pipeline, cancel-in-progress: false}` on `collect`,
   `build-site` and `deploy` (or on `collect` plus a `pages` group on deploy) instead of the
   workflow, so no-op gate runs never enter the group; document the remaining "one pending"
   behaviour.

### Security checklist

- Secrets only in `collect` → `Run the pipeline` and `Job summary` (the latter needs them for
  the redactor), via `env`; no `set -x`, no DEBUG, every `sivin` call at `--log-level INFO`.
- Permissions: workflow `{}`; gate `{}`, collect `contents: write`, build-site `contents: read`,
  deploy `pages: write` + `id-token: write`. Least privilege. (Nit-level remark, not a finding:
  the collect checkout persists the write token in `.git/config` during `pip install` and
  `sivin run`; acceptable for first-party code.)
- No `pull_request_target`; no `${{ github.event.* }}` / `${{ inputs.* }}` inside `run:`
  scripts (all through `env`).
- Artifact: only `run-summary.md` (redacted) and `data/quarantine/*.report.json`; no downloads.
- `git push origin HEAD:refs/heads/data` is never forced; verified rejection on divergence.
- `.env` is never under `data/` and is not copied.
- Pages artifact = `web/dist` only; the build state lives in `data/derived/` and is not copied
  into `web/public/data`.

### Correctness checklist

- Exit codes: 0/1/4 publish, 2/3/5/130/empty fail after the summary (`Judge` step), job fails
  in `Fail on a broken run`; with `full_site_build` the higher of run/build-site code wins. OK.
- Orphan creation from a shallow clone and first run on an empty origin: OK (simulated).
- Copy-in/out: both under `set -e` in `collect`; a failed `cp` stops before `git add`, so no
  partial copy is committed. OK.
- `build-site` checks out `needs.collect.outputs.data_sha` (the pushed or unchanged HEAD). OK.

### Docs

`docs/operations.md` is sufficient for the one-time setup and the first run (visibility, Pages
source, secrets, checklist, manual runs, exit-code table, recovery). The base-path issue above
would make step 5 of the checklist (the next morning) the first place it shows; after the fix,
add to step 5 "open the portal after the scheduled run".

### Deviations assessment

1. **Cron gate (compare the fired cron with today's offset):** accept. Strictly better than the
   plain hour check; verified for all of 2026 with delays up to 3 h. A dropped scheduled run
   still means no run that day (documented).
2. **`site/data` committed to `data`:** accept. Needed for the incremental build on a fresh
   runner and makes every `data` commit deployable; growth is deltas of JSON.
3. **Copy in/out instead of a config override:** accept; paths stay identical to local runs.
4. **Quarantine not committed (reports as 14-day artifact):** accept the decision, but enforce it
   in the workflow (minor finding above), not only via the branch `.gitignore`.
5. **Checkout of the default branch:** accept the intent; implement without the event payload
   (nit above).
6. **`sivin report` in `cli/commands/summary.py`:** accept.
7. **Keep-alive for the 60-day rule (open question 3):** recommend no keep-alive now; the daily
   bot commits are likely activity, and the docs say how to notice and re-enable. Revisit only if
   the banner ever appears.
