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

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
