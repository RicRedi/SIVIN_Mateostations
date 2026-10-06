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

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent reviewer agent, 2026-10-06. Reviewed `git diff origin/main...HEAD` (commits
bf9dfd2, 83759d3, 8a8032c) against the WP-1.3.1 brief. Not run against the real portal or a
real Chrome.

### Gates observed

- `make lint` → ruff: all checks passed; 301 files already formatted.
- `make type` → mypy --strict: no issues found in 182 source files.
- `make test` → 2022 passed.
- `make cov` → `diagnostics.py` 100 % (159 stmts, 24 branches), `client.py` 100 %, `settings.py`
  100 %.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | src/sivin/ingest/portal/diagnostics.py:53, :290-300 | A dead chromedriver makes `collect()` raise `urllib3.exceptions.MaxRetryError`, which is not in `DIAGNOSTIC_ERRORS`; the whole report, including the already collected directory listings, is replaced by `diagnostics unavailable (MaxRetryError)`. | open |
| minor | src/sivin/ingest/portal/diagnostics.py:338-343 | Entry classification duplicates `DownloadWatcher._is_complete`/suffix-prefix logic instead of reusing it; "too small" (< `min_export_size_bytes`, the cause of `DownloadIncompleteError`) is not marked. | open |
| minor | src/sivin/ingest/portal/diagnostics.py:349-354 | Notice search makes up to three WebDriver round trips per matching element (`is_displayed`, `text` twice) with no cap before filtering; a broad selector such as `[role='status']` on a large page costs many calls, and one stale element discards all notices. | open |
| nit | docs/ingest.md:234 | Says `absent` when the default dir equals `download_dir`; the code prints `same as the download directory` (the deviation is fine, the doc is out of date). | open |
| nit | src/sivin/ingest/portal/diagnostics.py:317 | `Path.is_dir()` returns `False` on `PermissionError` of a parent, so an unreadable path is reported as `absent`, not `unavailable (PermissionError)`. | open |
| nit | src/sivin/ingest/portal/diagnostics.py:378-381 | `public_url` keeps `;params` in the path (e.g. `/x;jsessionid=ABC`) and the whole of non-hierarchical URLs (`data:…`). Unlikely for this DotVVM portal; mention or strip `;…` too. | open |

**major — dead chromedriver.** Verified with a throwaway script: a `WebDriver` whose
`RemoteConnection` points to a closed port (`http://127.0.0.1:9`) raises
`urllib3.exceptions.MaxRetryError` (MRO: `RequestError → PoolError → HTTPError → Exception`, not
`OSError`, not `WebDriverException`) from `driver.title` within 5 ms. `DownloadDiagnostics.collect`
then raises it; with a `.crdownload` file in the download directory the listing is lost. The
client's `except Exception` guard keeps the original `DownloadTimeoutError` (good), but the log
shows only `diagnostics unavailable (MaxRetryError)`, i.e. exactly the evidence the WP exists
for (download directory) is missing when chromedriver died, and the class docstring ("never
raises for browser … errors") is wrong for that case. A crashed Chrome with a living
chromedriver gives a `WebDriverException` and is handled correctly.
Fix: add `urllib3.exceptions.HTTPError` to `DIAGNOSTIC_ERRORS` (urllib3 is Selenium's transport;
or catch `Exception` inside `_attempt`/`_notices` and document why), and add a test with a
driver raising it that asserts the directory line is still present.

**minor — duplicated classification.** `_kind` re-implements the watcher's
`endswith(partial_suffixes)` / `startswith(ignored_prefixes)` rules; if the watcher's rules
change, the diagnostics will silently mark files differently from what the watcher did.
Suggest a public `DownloadWatcher.classify(name, size_bytes)` (or a small shared classifier)
used by both, which can also return `too small` for `DownloadIncompleteError`.

**minor — notice cost.** Suggest `find_elements` → slice to a named cap (e.g.
`MAX_NOTICE_CANDIDATES`) before `is_displayed`, read `element.text` once, and catch the stale
error per element so one stale element does not drop the others.

Not a finding (checked): bare `raise` inside the `except` re-raises the original exception
object with its traceback; the session test confirms 2 attempts and the same failure reason.
URL user info, query and fragment are stripped (`https://u:p@host/x?t=1#f` → `https://host/x`).
Notice and title texts are arbitrary page text, but log records already pass the global
`RedactingFilter` (`SIVIN_USER`/`SIVIN_PASSWORD`), so a page echoing the login is masked.
Logged file names are export names (public sensor ids) and `~/Downloads` entries of the runner.
Report is four lines, entries capped at 10, notices at 3, texts at 200 characters. No hung-driver
timeout exists in `driver.py` (Selenium's default socket timeout is `None`); that is pre-existing
and applies to the whole client, so it is out of scope here.

### Deviations assessment

- `except Exception` around `collect()` in the client: accepted — it is the last guard that the
  download error is never replaced, the name of the failure is logged, and the test shows no
  chained context. It does not replace fixing the major above (the guard keeps the error but
  loses the report).
- URL user info stripped, title truncated, directories listed as `name/ (directory)`: accepted,
  all in the spirit of the brief.
- `same as the download directory` instead of `absent`: accepted (more accurate); update
  `docs/ingest.md:234`.
- Scope: only files in the brief's scope changed (`src/sivin/ingest/portal/**`,
  `tests/ingest/portal/**`, `docs/ingest.md`, regenerated `docs/configuration.md` for the new
  key, the hand-off note); no shared file touched. `notification_css` is honestly marked
  `[to be verified]`.
