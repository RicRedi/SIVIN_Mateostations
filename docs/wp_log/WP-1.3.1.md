# WP-1.3.1 — Download diagnostics in the log

## Summary

Follow-up of WP-1.3 requested by the owner on 2026-10-06 after the first live run on GitHub
Actions, where every export ended in `DownloadTimeoutError` and the log could not tell a
provider outage from a fault on our side. When `PortalClient.download_export` fails with
`DownloadTimeoutError` or `DownloadIncompleteError` after pressing the export button, the client
now logs one WARNING block built by the new `DownloadDiagnostics` class and then re-raises the
original exception unchanged (bare `raise`), so `PortalSession`'s retry and failure recording
are untouched. The block lists the download directory (all entries with sizes, unfinished and
ignored ones marked, newest first, capped at 10), Chrome's default `~/Downloads` when it differs,
the browser state (title, URL without user info/query/fragment, `document.readyState`, window
count) and visible portal notices found with a new configurable CSS selector. Collecting never
raises; an unreadable item becomes `unavailable (<ExceptionName>)`. **Not verified against the
real portal.**

## Changed files

- `src/sivin/ingest/portal/diagnostics.py` (new) — `DownloadDiagnostics`, `DownloadReport`,
  `DirectoryListing`, `DirectoryEntry`, `EntryKind`, `BrowserState`, `PortalNotices`,
  `public_url()`, constants `MAX_LISTED_FILES` (10), `MAX_NOTICES` (3), `MAX_TEXT_CHARS` (200).
- `src/sivin/ingest/portal/client.py` — optional constructor argument `diagnostics`; the watcher
  wait in `download_export` logs the block on the two download errors and re-raises.
- `src/sivin/ingest/portal/settings.py` — new `PortalSelectors.notification_css`.
- `tests/ingest/portal/conftest.py` — the fake driver gained `title`, `current_url` (with a
  synthetic token query), `window_handles`, `readyState` via `execute_script` and notice elements.
- `tests/ingest/portal/test_diagnostics.py` (new) — 30 tests.
- `docs/ingest.md` — section *When a download fails*, settings row, component row, symptom row.
- `docs/configuration.md` — regenerated reference (one new row) with
  `ConfigReference().markdown(heading_level=4)`.

## Public API

```python
# sivin.ingest.portal.diagnostics (imports Selenium; not re-exported from the package)
DownloadDiagnostics(settings: PortalSettings, directory: Path,
                    default_download_dir: Path | None = None)   # None -> Path.home()/"Downloads"
    .collect(driver: WebDriver) -> DownloadReport                # never raises for
                                                                 # WebDriverException, OSError,
                                                                 # RuntimeError, ValueError
DownloadReport(download_dir, default_dir: DirectoryListing, browser: BrowserState,
               notices: PortalNotices).format() / __str__        # four indented lines
public_url(url: str) -> str                                      # scheme://host[:port]/path

PortalClient(..., diagnostics: DownloadDiagnostics | None = None)
PortalSelectors.notification_css: str   # default "[role='alert'], [role='status'], .alert,
                                        # .toast, .notification"; "" disables the search
```

Logged text (synthetic, from the tests):

```text
Export of 8615620 77678271 failed (DownloadTimeoutError); diagnostics:
  download dir /…/downloads: 1 entry: MeteoData_8615620 77678271 (VUT)_20260301_223851.xlsx.crdownload (7 B, unfinished)
  Chrome default dir /root/Downloads: absent
  browser: title Synthetic portal; url https://lemon.e-service.cz/meteo:8615620 77678271; readyState complete; windows 1
  portal notices: none visible
```

## How it was verified

- `make lint` → ruff check: all checks passed; ruff format: 301 files already formatted.
- `make type` → mypy --strict: no issues in 182 source files.
- `make cov` (same suite as `make test`) → 2022 passed; total coverage 99.83 %;
  `diagnostics.py` 100 % (159 statements, 24 branches), `client.py` 100 %, `settings.py` 100 %.
- Tests with hand-written expected text: listing order and markers, empty/absent directory,
  cap with `… and 2 more`, default directory listed / same / absent / home missing
  (`RuntimeError`) / unresolvable (`OSError`), unreadable directory (`PermissionError`), file
  vanishing while listed, URL stripping (query, fragment, `user:secret@`, port), unparsable port
  (`ValueError`), a browser failing on every call, notice filtering (hidden, blank), whitespace
  collapsing and truncation to 200 characters, notice cap, empty selector, stale element, the
  full report text.
- Client integration on the fake portal: one WARNING block for `none`, `partial` and `empty`
  behaviours, the original exception type re-raised, token query absent, credentials absent from
  the whole log; a failing `title` does not mask `DownloadTimeoutError`; an unexpected error from
  the collector (`KeyError`) is logged by name only and the original error is raised with no
  chained context; a successful download logs no block.
- Session: with one device never downloading, the run still makes 2 attempts, records the same
  `DownloadTimeoutError: … (2 attempts)` reason, downloads the other two devices, and logs two
  diagnostics blocks.

## What did not work / what was not verified

- **Not run against the real portal or real Chrome.** The browser members used (`title`,
  `current_url`, `window_handles`, `execute_script`, `find_elements`) are standard Selenium
  WebDriver API, but were exercised only on fakes.
- **`notification_css` is a guess.** Generic ARIA roles and common toast classes; the portal's
  real error element is unknown. `none visible` therefore does not prove that the portal showed
  nothing. Marked `[to be verified]` in the field description and in `docs/ingest.md`. A `.alert`
  class may also match permanent, non-error page banners; then the block shows their text.
- **`~/Downloads` as Chrome's fallback** is Chrome's usual default on Linux; it is not read from
  the browser. With a non-default `XDG_DOWNLOAD_DIR` the fallback may be elsewhere.
- In the client tests the default directory is the real `~/Downloads` of the test process; the
  tests do not assert on that line (the unit tests inject it).
- The diagnostics are collected only for the two download errors after the click, as asked; a
  `WebDriverException` or `ExportButtonNotFoundError` earlier in `download_export` logs no block.

## Deviations

- The client catches `Exception` (not only the listed error types) around `collect()`, as the
  last guard that the original download error is never replaced. Inside the collector only
  `WebDriverException`, `OSError`, `RuntimeError` (`Path.home()`) and `ValueError` (unparsable
  URL port) are caught per item.
- Beyond the brief, the URL also loses its user info (`user:pass@`) and the page title is cut
  like the notices; directories inside the download directory are listed as `name/ (directory)`.
- The default directory, when it is the configured one, says `same as the download directory`
  instead of `absent` (more accurate).

## Out of scope

- `PortalSession` could log the diagnostics for other device errors (e.g. `TimeoutException`
  on the tab) too; not requested.
- The client never logs in again after a session expiry (`return_to_folder` only reloads); the
  diagnostics would show the login URL, but recovery would need a change in `client.py`/
  `session.py` beyond this WP.

## Open questions for the owner

- When the provider's export works again: could you export once by hand while it fails (or
  when it next fails) and note which element shows the error message, so
  `selectors.notification_css` can be set precisely?
- Config wiring: the new key lives in `ingest.portal.selectors.notification_css`, already part
  of the wired `ingest.portal` section; no CLI change proposed. `config/sivin.yaml` is not
  changed (selectors are not listed there).

## Review

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
