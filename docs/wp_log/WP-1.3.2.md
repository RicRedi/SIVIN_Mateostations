# WP-1.3.2 — Downloads in headless Chrome, longer wait, headed option

## Summary

Owner-approved follow-up of WP-1.3 / WP-4.1 (2026-11-26). Every daily GitHub Actions run since
October 2026 logged in, listed the 4 devices, pressed the Excel button and then ended in
`DownloadTimeoutError` after 30 s, with an empty download directory, no file in
`~/Downloads` and the browser still on the device page (WP-1.3.1 diagnostics). Chrome ran with
`--headless=new` and download preferences only; the legacy script never ran headless.
This WP (1) explicitly allows downloads into `download_dir` through the Chrome DevTools
Protocol after the browser starts (`Browser.setDownloadBehavior`, falling back to
`Page.setDownloadBehavior`), in headless and headed mode, never raising when CDP is missing;
(2) raises the default `download_wait_s` from 30 s to 120 s; (3) adds a manual workflow input
`headed` that runs `sivin run --headed` under `xvfb-run -a`; (4) adds a `::warning::`
annotation on exit code 1 that names how many devices got no download. **None of this is
verified against the real portal or on GitHub Actions.**

## Changed files

- `src/sivin/ingest/portal/driver.py` — new `CdpDriver` (runtime-checkable `Protocol` with
  `execute_cdp_cmd`), new `CdpDownloadPermission(download_dir)` with `commands()` and
  `grant(driver) -> str | None`; constants `BROWSER_DOWNLOAD_COMMAND`,
  `PAGE_DOWNLOAD_COMMAND`, `ALLOW_DOWNLOADS`. `ChromeDriverFactory` takes an optional
  `permission` (default: one for `settings.download_dir`) and calls `grant()` on the started
  driver in `create()`. The profile preferences are unchanged.
- `src/sivin/ingest/portal/settings.py` — `PortalTimeouts.download_wait_s` default 30.0 → 120.0,
  description updated. Nothing else.
- `docs/configuration.md` — regenerated with `ConfigReference().markdown(heading_level=4)`
  (one row changed).
- `.github/workflows/pipeline.yml` — `workflow_dispatch` input `headed` (boolean, default
  false); the run step passes `HEADED`, appends `--headed` and wraps `sivin` in `xvfb-run -a`
  only when it is `true` (scheduled runs: input empty → headless as before); a headed run on a
  runner without `xvfb-run` stops with `::error::`. New step *Warn about devices without a
  download* (`if: always() && steps.run.outputs.code == '1'`, between *Job summary* and
  *Judge the exit code*): `jq` reads `data/runs/*.jsonl`, takes the newest record with
  `started_at` ≥ the run step's start (fractional seconds dropped before comparing; broken lines
  skipped), counts failures starting with `fetch ` and prints
  `::warning::No export was downloaded for N device(s); …`; if no record can be read it prints a
  generic *Partial failure* warning instead. Exit-code semantics and the judge step are
  unchanged.
- `tests/ingest/portal/test_driver.py` — 8 new tests (fake driver with `execute_cdp_cmd`):
  Browser domain success with exact parameters and no warning, fallback to the Page domain,
  both failing → one WARNING with the exact text and no exception, driver without CDP → WARNING,
  `create()` grants in headless and headed mode and keeps the prefs, `create()` with a non-CDP
  driver, injected permission.
- `tests/ingest/portal/test_settings.py` — default expectation 30.0 → 120.0.
- `tests/workflows/test_pipeline_workflow.py` — input set includes `headed`; 11 new tests:
  the run step executed with fake `sivin`/`xvfb-run` (headed → `xvfb-run -a sivin --log-level
  INFO run --headed`; `false` and empty → `sivin --log-level INFO run`; headed without
  `xvfb-run` → `::error::`, no call, no outputs), the warning step's condition and position, and
  the warning step executed with synthetic run records (2 fetch failures in this run's record
  among an earlier record, a broken line, a rejected file and a QC failure → "2 device(s)";
  no fetch failure → silent; no file / empty file / only an older record → generic warning).
- `docs/ingest.md` — component row, step 1 (CDP permission, fallback, log lines, unverified),
  settings table and intro (120 s), diagnostics reading guide (*Headless only*, CDP warning),
  troubleshooting (`headed` input).
- `docs/operations.md` — run command with `headed`, step 4 (the new warning), *Running it by
  hand* (`-f headed=true`, what it does, `xvfb-run` unverified), exit-code table (row 1),
  *Costs and limits* (4 failing devices × 2 attempts × 120 s ≈ 16 min of the 45 min timeout).
- `docs/wp_log/WP-1.3.2.md` — this note.

`config/sivin.yaml` does not set `download_wait_s`, so it is unchanged. README.md describes
neither the download mechanics nor the workflow inputs; no change needed.

## How it was verified

- `make lint` → ruff check: all checks passed; ruff format: 301 files already formatted.
- `make type` → mypy --strict: no issues found in 182 source files.
- `make test` → 2055 passed (130 warnings, pre-existing kinds).
- `make cov` → total 99.83 % (required 85 %); `driver.py` 100 % (129 statements, 26
  branches), `settings.py` 100 %.
- The workflow's new shell logic was executed by the tests with bash and the local `jq`
  (`/usr/bin/jq`), with fake `sivin` and `xvfb-run` executables.

## What did not work / what was not verified

- **Not verified against the real portal and not run on GitHub Actions.** Whether the CDP
  permission makes headless downloads work, and whether 120 s is enough, is unknown until the
  next scheduled run. The log line `Downloads allowed into … via Browser.setDownloadBehavior`
  (INFO) or `Could not allow downloads via CDP (…)` (WARNING) will tell whether the command was
  accepted.
- `Browser.setDownloadBehavior` is sent through chromedriver's `execute_cdp_cmd` (page target
  session); that chromedriver accepts a Browser-domain command there is assumed from Selenium
  usage, not checked. The fallback covers a rejection.
- `xvfb-run` on `ubuntu-latest` is assumed (it is used by many workflows on that image), not
  verified; the step fails clearly without it.
- **actionlint / shellcheck were not run locally**: neither is installed in this environment,
  and fetching `actionlint-py` with `uvx` was refused by the sandbox's permission policy. CI's
  `actionlint` job will run it; the orchestrator should run it before review if possible.
- The warning counts `fetch <device>: …` failures of the run record (the prefix written by
  `sivin.app.fetch.FetchReport.failures`). It does not know the number of configured devices,
  so it says "N device(s)", not "N of M". A whole-fetch failure (`fetch: …`) is not counted as a
  device (that path normally ends with exit code 4).

## Out of scope

- `src/sivin/app/summary_formats.py` (`JsonSummary`): a `fetch_failures` count in
  `sivin report --format json` would let the workflow use `sivin report` instead of reading the
  run log with `jq`. Not touched (WP-1.10 works in `src/sivin/app/**`).
- The job summary (`sivin report --format markdown`) could state "N of M devices downloaded"
  in its outcome line; same module.

## Open questions for the owner

- After the next scheduled run: if the CDP line is logged but the downloads still time out,
  please start one manual run with `headed=true` (Actions → pipeline → Run workflow) so headless
  vs. windowed Chrome can be compared.
- WP-1.3.2 is not yet in MIGRATION_PLAN §4 (the orchestrator records it).

## Review

Verdict: APPROVE (round 1)

Reviewer: independent reviewer agent, 2026-11-26, worktree `../wt/wp-1.3.2`, commit `145ee5c`.

### Gates (run by the reviewer)

- `make lint` → ruff check: all checks passed; ruff format: 301 files already formatted.
- `make type` → mypy --strict: no issues found in 182 source files.
- `make test` → 2055 passed, 130 warnings (pre-existing pandas deprecation warnings in
  `tests/quality`).
- `make cov` → total 99.83 % (required 85 %); `driver.py` 100 % (129 statements, 26 branches),
  `settings.py` 100 %.
- `actionlint -shellcheck <shellcheck> .github/workflows/*.yml` → exit 0, no findings (this closes
  the worker's "actionlint not run" gap).
- `git status` clean; diff touches only files in the brief's scope (`client.py`, `session.py`,
  `src/sivin/app/**` untouched); `config/sivin.yaml` does not set `download_wait_s`, so leaving it
  unchanged is correct; `docs/configuration.md` matches the generator (the docs test passes).

### Checked beyond the worker's tests

- CDP parameters: `Browser.setDownloadBehavior {behavior: "allow", downloadPath: <abs dir>,
  eventsEnabled: false}`, fallback `Page.setDownloadBehavior {behavior: "allow", downloadPath}`,
  match the brief. `downloadPath` is absolute because `options()` raises on a relative
  `download_dir` before the driver starts. Only the directory is logged; no credentials.
- Warning step executed outside the repo (`/tmp/claude-0/review-1.3.2/`) with bash and jq against
  hand-written synthetic records: `failures` as a string, numeric `started_at`, non-string
  failure items, a JSON array line, a newer record in another day's file, empty `STARTED`, no
  `data/runs/` at all, and `jq` missing from `PATH`. Every case exits 0 with either the count
  warning or the generic warning; none can fail the step, so the `Judge the exit code` step
  (default `success()` condition) and the publish decision are unaffected. Exit-code semantics
  unchanged.
- Run records are written only by `sivin run` and `sivin ingest`; `build-site --full` (the
  `full_site_build` path) writes none, so it cannot shadow the run's record.
- Headed/scheduled logic: scheduled runs get an empty `HEADED` → plain `sivin` (headless);
  `xvfb-run -a sivin … run --headed` passes the child's exit code; `--headed` is an option of
  `sivin run` (`src/sivin/cli/commands/pipeline.py`). Quoting: all expansions quoted, args via a
  bash array; shellcheck clean.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | `.github/workflows/pipeline.yml:86` (`timeout-minutes: 45`), `docs/operations.md:337` | Job timeout vs. growing sensor count. | open |
| minor | `src/sivin/ingest/portal/driver.py:118` | `grant()` catches only `WebDriverException`. | open |
| nit | `.github/workflows/pipeline.yml:226` | `sort_by(.started_at)` sorts strings. | open |
| nit | `.github/workflows/pipeline.yml:231` | Duplicate generic warning. | open |

1. **Timeout scaling (minor).** Input: every device fails to download (today's situation). Per
   device: 2 attempts × (120 s download wait + 3 s + 2 s settle + navigation/element waits up to
   15 s each) ≈ 4.5–5 min, not the 4 min used in `docs/operations.md` ("about 16 min" for 4
   devices is an underestimate; ≈ 18–20 min is realistic). With checkout/install/QC/site
   (~5 min) the 45 min `collect` timeout is reached at roughly 8–9 simultaneously failing
   devices. Wrong behaviour then: the job is cancelled inside *Run the pipeline*, `code` is never
   written, Judge skips publishing, and the data of devices that *did* download are lost for that
   day (red run, no record). Fine for today's 4 sensors, but it does not scale with the planned
   growth. Suggested fix (follow-up, not blocking): a total fetch time budget in the client
   (stop retrying when it is exhausted) or derive `timeout-minutes` from the device count; at
   minimum correct the estimate in `docs/operations.md` to include the page waits and state the
   device count at which the timeout must be raised.
2. **Narrow exception (minor).** Input: `execute_cdp_cmd` raising something other than
   `WebDriverException` (e.g. a `urllib3`/`ConnectionError` from a dying chromedriver, or a
   `KeyError` from an unusual response). Wrong behaviour: the exception escapes `create()`, the
   just-started Chrome is never quit (leaked process), contrary to "never raise". Unlikely in
   practice because `isinstance(driver, CdpDriver)` covers the "no CDP" case. Suggested fix:
   catch `Exception` in `grant()` (logging the type, as now), or quit the driver in `create()`
   if `grant()` raises.
3. **String sort (nit).** Input: two records in the same second, `…:05Z` and `…:05.5Z`. `'.' <
   'Z'`, so the fractional one sorts first and `last` picks the other (verified). Practically
   unreachable (two runs in one second). Suggested fix: `sort_by(.started_at | utc)` or sort on
   the parsed value. Related: the step parses the whole `data/runs/` history every run (one file
   per day); harmless now, could be limited to today's/yesterday's file.
4. **Duplicate warning (nit).** When the run record cannot be read, the new step prints
   "Partial failure (exit code 1) …" and Judge prints its own "Partial failure (exit code 1): see
   the job summary." Two near-identical annotations; cosmetic.

### Deviations assessment

- `CdpDriver` as a runtime-checkable `Protocol` plus a separate `CdpDownloadPermission` injected
  into `ChromeDriverFactory`: reasonable, testable, matches §1.2 (dependency via constructor,
  named constants). Accepted.
- The warning says "N device(s)", not "N of M", because the record does not hold the configured
  device count; acceptable within the scope restriction (`src/sivin/app/**` belongs to WP-1.10),
  and the out-of-scope note proposes the proper fix.
- Not verified on the real portal or on GitHub Actions (CDP acceptance by chromedriver,
  `xvfb-run` on `ubuntu-latest`); this is stated openly in the hand-off note and cannot be checked
  here. The reviewer did not connect to the portal.
