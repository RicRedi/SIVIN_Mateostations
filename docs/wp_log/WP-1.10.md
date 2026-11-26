# WP-1.10 — Portal table reader as a fallback source

## Summary

The device page's table *Historie meteorologických dat* is now a second source of a device's
data. `ingest.portal.sources` (default `[export, table]`) lists the sources `PortalSession` tries
per device, in order; a device fails only when every source failed, and the log names the source
that delivered it. The table source asks for the sensor's last stored measurement, reads the
table newest to older at `incremental_page_size` (500) rows per page and stops at the first page
that reaches that measurement; with nothing stored it reads every page at
`full_history_page_size` (5000). Only rows newer than the store are written, as a file in the
exact layout of the portal's CSV export
(`MeteoData_<device> (table)_<YYYYMMDD>_<HHMMSS>.csv`) into the download directory, so parsing,
validation, quarantine, the store and the run record handle it unchanged. Locators and texts
were taken from the page the owner saved; nothing was run in a live browser.

## Changed files

- `src/sivin/ingest/portal/settings.py`: `PortalSource` (`export`, `table`), `PortalSettings.sources`
  (unique, non-empty) and `PortalSettings.table` (`PortalTableSettings`: card/table/paging/button
  locators, paging text pattern, header → export column mapping, timestamp format,
  `source_timezone` (shared from `time.source_timezone`), page sizes, click and page limits, wait
  for rows, file label). New fields only; `download_wait_s` untouched.
- `src/sivin/ingest/portal/table.py` (new): `RawTable`, `PagingStatus`, `MeteoTable` protocol,
  `TableRow`, `TableReading`, `TableRowParser`, `TableReader` (page selection, stop rule,
  filtering, de-duplication). No Selenium.
- `src/sivin/ingest/portal/table_page.py` (new): `PortalTablePage` (Selenium): wait for rows,
  read a page with one script call, read the paging text, change the page size, next page.
- `src/sivin/ingest/portal/table_file.py` (new): `TableCsvWriter`.
- `src/sivin/ingest/portal/sources.py` (new): `DeviceSource` ABC + `device_source_registry`,
  `ExportSource`, `TableSource`, `SourceContext`, `LastTimestamps` protocol, `NoStoredData`.
- `src/sivin/ingest/portal/client.py`: `open_meteo_tab()` split out of `download_export()`
  (same steps), new `read_table()`; the diagnostics WARNING now names the action (`Export of …`
  unchanged, `Table read of …` new).
- `src/sivin/ingest/portal/session.py`: sources tried in order with the existing retry and
  recovery per source; `SessionResult.up_to_date`; failure reason `export: …; table: …` when
  several sources are configured (unchanged text with one source).
- `src/sivin/ingest/portal/models.py`: `DownloadedExport.source` (default `"export"`),
  `UpToDateDevice`, `SessionResult.up_to_date` (default `()`).
- `src/sivin/ingest/portal/errors.py`: `TableReadError`. `__init__.py`: re-exports.
- `src/sivin/app/factory.py` (round 2): passes the store to `FetchService`.
- `src/sivin/app/fetch.py`: `StoreLastTimestamps` (read-only, uses the existing
  `MeasurementStore.time_range`; no storage change was needed), `FetchService(last_timestamps=…)`,
  per-source counts in the log.
- `config/sivin.yaml`, `docs/configuration.md` (regenerated), `docs/ingest.md` (new section
  *Fallback: the device table*, components, run steps, symptoms), `README.md` (How it works,
  What it does).
- Tests: `tests/ingest/portal/{table_fakes,test_table,test_table_page,test_table_file,test_sources}.py`,
  `tests/app/test_table_fallback.py`, fixture `tests/ingest/portal/data/meteo_table_excerpt.html`;
  adjusted `tests/ingest/portal/test_session.py`, `test_diagnostics.py` (export-only settings in
  the tests that are about the export; one log text) and `tests/app/project.py`
  (`table.rows_wait_s: 0.2` for the fake browser).

The fixture is an excerpt of the owner's saved page, built with a `python3 -I` script outside the
repository: the tab link, the card with the table header, the first 20 rows (public measured
data, unchanged) and the paging control. Scripts, styles, `onclick` handlers, the hidden
viewmodel input, all other tabs and everything account-related were removed; it is labelled as
an excerpt in its first lines. The saved page itself is not in the repository.

## How it was verified

- `make lint` → ruff check and format clean (311 files).
- `make type` → `mypy --strict`: no issues in 186 source files.
- `make test` → 2136 passed (round 2, after the rebase).
- `make cov` → 2136 passed, total 99.81 % (round 2). Changed/new modules: `table.py`, `table_file.py`,
  `sources.py`, `session.py`, `client.py`, `models.py`, `settings.py`, `errors.py`,
  `app/fetch.py`, `app/factory.py` 100 %; `table_page.py` 97 % (two stale-element branches not hit).
- Tests on the real excerpt: header texts, the 20 rows (one-digit hours such as `9:53:11`), the
  paging text `Zobrazeno 5000 z 9562 (5000)` against `paging_text_pattern`, and the written file
  through `PortalCsvParser` (CET → UTC: `18.11.2026 13:49:25` → `12:49:25Z`).
- SYNTHETIC tests: incremental stop (page 3 of 6 reaches the stored time), summer-time
  conversion, nothing newer (up to date), unreachable page size, full history, `max_pages`, a row
  repeated on the next page, columns changing between pages, malformed rows, empty table, a next
  page that does not load, page-size clicks (stepping, wrapping, no effect, never reached, no
  button, no paging), the fallback decisions (export works → table untouched; export fails →
  table delivers; both fail → combined reason and diagnostics; `[table]`; `[export]`), and two
  incremental runs through `FetchService` + ingest into a real store (30 rows, then exactly the 2
  new ones, then up to date).

## What did not work / what was not verified

- **Nothing ran against the live portal.** The locators (`card_xpath_template` and the relative
  XPaths) were written from the saved HTML; no XPath engine was available to evaluate them
  against the excerpt (no `lxml`), so they are checked only by the fake browser, which matches
  them as strings. The read script (`JS_READ_TABLE`) was never run in a browser.
- **The page-size button** (`fa-chevron-down`, tooltip "Zvětšit počet zobrazených záznamů") has
  no visible options in the page; its behaviour (step to the next size, wrap after 5000?) is
  assumed. The saved viewmodel already had page size 5000 for this table, so the default 500 can
  only be reached if the button wraps. If it does not, the reader logs a WARNING and reads with
  5000 rows per page (correct, just more rows per page).
- **Wait for rows** (`rows_wait_s` 30 s) and the page-change detection (first row changed) are
  project defaults, to be tuned on the first real run.
- **Precision:** the table shows 4 decimals (`24,3848`), the March 2026 export 2 (`23,79`). Not
  verified on the same rows. See the open question below.

## Round 2 (orchestrator decisions, 2026-11-26)

- **Rebase:** onto `origin/wp/1.3.2-download-headless` (7c4f0df) without conflicts;
  `docs/configuration.md` regenerated check passes (WP-1.3.2's `download_wait_s` 120 s and the
  new `table.*` keys). The test helpers set their own short waits (`download_wait_s` 3 s in the
  portal and app fixtures, `rows_wait_s` 0.1–0.2 s); the suite stays fast.
- **Wiring (Files scope extended to `src/sivin/app/factory.py`):** `ServiceFactory.fetch_service`
  passes `last_timestamps=StoreLastTimestamps(self.store())`. Test
  `tests/app/test_table_fallback.py::test_sivin_run_reads_only_the_rows_newer_than_the_store`:
  a second `RunService` run writes and appends exactly the 2 new rows (0 identical rows skipped,
  so no full-history read).
- **DST:** when the last stored time lies in the repeated autumn hour, `TableReader` lowers the
  local cutoff by twice the clock shift (2 h, `DST_CUTOFF_SHIFTS`): one shift re-reads the
  repeated hour, the second adds ordinary rows before it, because the CSV parser trusts
  repeated-hour rows only between ordinary rows (`RowOrderAnalyser`, point 4; with one shift
  the parser dropped them). Test with the 25.10.2026 change: the two new CET rows are kept and
  reach UTC correctly through `PortalCsvParser`; outside a change the cutoff is unchanged.
- **Precision:** storage unchanged, default `prefer_newest` kept; the behaviour is documented in
  `docs/ingest.md` (Known limits). Still an owner question (below).
- Config list form `ingest.portal.sources` and the `(table)` label accepted;
  `SensorId.parse` and `ExportSourceIds` recognising the name are tested in
  `test_table_file.py`.

## Out of scope

- `docs/architecture.md` and `docs/data-format.md` do not mention the table source; a sentence
  each would help (not in this WP's files).

## Open questions for the owner

1. **Precision of table vs export.** The table shows 4 decimals (`24,3848`), the export 2
   (`23,79`). The table never re-sends stored rows, but a later successful export overlapping
   table-sourced rows replaces their values under `prefer_newest` (each a logged conflict,
   capped by `storage.max_recorded_conflicts`). Keep this, round the table values, or prefer
   the existing values?

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent of the worker; diff `origin/wp/1.3.2-download-headless...HEAD`
(f86568e, f48183e). Probes were throwaway scripts outside the repository; the owner's saved
page was read only with `python3 -I`; nothing connected to the portal.

### Gates (run by the reviewer in the worktree)

- `make lint`: ruff check clean, 311 files formatted.
- `make type`: mypy strict, no issues in 186 source files.
- `make cov`: 2136 passed, total 99.81 % (85 % required). Changed modules 97-100 %.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `src/sivin/ingest/portal/table_file.py:131-140` | A device name that ends in `(VUT)` makes every table read fail | open |
| major | `src/sivin/ingest/portal/table.py:339-354` | The repeated autumn hour is lost when the last stored row lies just before it | open |
| major | `src/sivin/ingest/portal/sources.py:287-289`, `table.py:313-327` | If every row is malformed, the device is reported as "up to date" | open |
| minor | `src/sivin/ingest/portal/table.py:313-316` | The newest-first order is assumed, not checked | open |
| nit | `src/sivin/ingest/portal/table.py:390-393` | Rows are de-duplicated by their cell texts, timestamp included | open |
| nit | `src/sivin/ingest/portal/session.py` (`_fetch`) | The fallback starts only after the export has used all its attempts | open |

**1. major: a device name with `(VUT)` makes the table source fail.** Input:
`PortalDevice("8615620 77680921 (VUT)")`. The file name becomes
`MeteoData_8615620 77680921 (VUT) (table)_20261025_140000.csv`, and `SensorId.parse` rejects
it. `file_name` then raises `TableReadError("... does not name a sensor ...")`, so every table
read of that device fails. Evidence that real names look like this: in the owner's saved page
the device's `Name` and `Title` are `8615620 77680921 (VUT)`, and the real exports are named
`MeteoData_<that name>_<stamp>` (`MeteoData_8615620 77678271 (VUT)_20260301_223857.csv`).
MIGRATION_PLAN §4 and the test fakes use `8615620 77678271` without the suffix, and the fake
export adds ` (VUT)` by itself. Which name the device list (`DeviceName`) gives is therefore
not settled. If it carries `(VUT)`, the fallback cannot work for any device. No test uses a
device name with a suffix. Fix: use a name that parses for both spellings, for example the
brief's `MeteoData_<name>_table_<stamp>.csv` or the label in front of the name. Otherwise make
`SensorId`/`ExportSourceIds` accept a trailing `(label)`. Add tests for both device-name
spellings.

**2. major: data loss at the autumn clock change.** Input: the last stored row is 25.10.2026
01:40 CEST (23:40Z), and the table has SYNTHETIC 30-min rows through the change. The cutoff
is lowered only when the stored time itself lies in the repeated hour. Here the file starts
directly with the four repeated-hour rows (02:10/02:40 CEST, 02:10/02:40 CET) and has no
ordinary row before them. `PortalCsvParser` flags them `TIMESTAMP_SUSPECT` and drops them as
"4 unresolved row(s)". The next run's cutoff is after them, so the table path never fetches
them again. The probe also covered a stored time of 01:10 CEST, the first pass, the second
pass, spring and the turn of the year: no loss in those cases. Fix: apply the lowered cutoff
whenever the read window touches a repeated hour, not only when the stored time is inside it.
Simpler: always write at least one already-stored ordinary row at or before the cutoff as an
anchor (the store skips it as identical). Add a test that starts 20-60 min before the change.

**3. major: a format change is reported as success.** Input: SYNTHETIC rows with ISO
timestamps (`2026-11-20 23:00:00`) where the configured format is `%d.%m.%Y %H:%M:%S`. Every
row is malformed, so the stop rule never fires. The reader pages through `max_pages` pages and
returns `rows=()`. `TableSource.deliver` returns `None`, and the session reports the device as
"up to date (table source)" with no failure. Only a WARNING per page shows the problem, so data
would stop arriving silently. Fix: raise `TableReadError` when a page has rows and none of them
parses, or when `malformed_rows > 0` and nothing was reached or kept. Add a test.

**4. minor: the sort order is not checked.** The header cells of the real table are DotVVM
sort links (`sortBinding` postbacks). If the grid is ever shown oldest first, page 1 already
holds rows at or before the stored time. The stop rule then fires and the rows are filtered
away, and the device is again reported as "up to date". Fix: check that the parsed timestamps
of a page do not increase, and raise `TableReadError` if they do.

**5. nit: de-duplication by cell texts.** `_RowCollector` treats two rows as equal when all
their texts are equal, timestamp included. In the repeated autumn hour, 02:10 CEST and
02:10 CET with identical values would be merged into one row. That is unlikely with four
decimals, but it is not impossible at night (rain 0, same counter and battery). Fix: compare
consecutive page boundaries only, or count duplicates per page.

**6. nit: when the fallback starts.** With `[export, table]` and an export that has been broken
since October, each device first spends `attempts_per_device` (2) × `download_wait_s` (120 s)
on the export before the table is read. That is about 16 min for 4 devices, within the
pipeline's 45 min. This is an owner decision, not a defect: `[table, export]` is possible
while the export is broken.

### Checked without findings

- Brief tasks: the incremental stop, full history at 5000, the page-size change, the source
  modes, the combined failure reason and the reuse of the diagnostics are all implemented and
  tested. `StoreLastTimestamps` is read-only and reuses `MeasurementStore.time_range`. Storage
  is unchanged and append-only.
- Stop rule probes (SYNTHETIC): store newer than the table → 1 page, no rows. Store older than
  the whole table → every page, all rows. Equal timestamp with a different value → dropped
  (append-only). A row inserted at the top while paging → no duplicates, no loss.
- The written file matches the real export byte for byte in the title and header lines
  (compared with `tests/fixtures/exports/real/…csv`). It uses CRLF, the `;` trailer and UTF-8
  without a BOM.
- Locators against the saved page: the card heading `<b>Historie meteorologických dat</b>`
  occurs once, and the events card is a separate `.card`. `fa-step-forward` is a `<button>`
  with `dotvvm-enable`, so it is `disabled` on the last page and `is_enabled()` works. The
  paging text matches `paging_text_pattern`. In the saved page, "shown" is
  min(total, page size), not the row count of the page, but it is not used for decisions.
- The fixture `tests/ingest/portal/data/meteo_table_excerpt.html` (20 kB) has no script,
  `onclick`, input, viewmodel, token, URL or user field. The only matches are in the
  explanatory comment. The saved page and `vm.json` are not in the repository.
- Credentials: the new code logs device names and times only.
- Scope: changes stay in the brief's files plus `app/factory.py` (allowed in round 2).
  `driver.py`, `.github/**` and `storage/` are untouched, and `download_wait_s` is unchanged.
  The WP-1.3.2 tests were switched to export-only settings with unchanged assertions (one log
  text). `open_meteo_tab` is the same sequence of steps as before. README is updated.

### Deviations

- `(table)` label instead of `_table_`, list-form `sources`, `factory.py` wiring and
  `prefer_newest`: these are orchestrator decisions, and the label is behind finding 1.
- DST cutoff of 2 h: correct when the stored time lies in the repeated hour, but incomplete
  (finding 2).
- Unverified live behaviour (page-size button, wait times, `JS_READ_TABLE`): declared openly
  in the hand-off note and acceptable for a fallback, but it should be checked on the first
  real run.

### Out of scope (pre-existing, not this WP)

- `diagnostics.py` notes that a dead chromedriver raises urllib3 `MaxRetryError`, which is
  not in `session.DEVICE_ERRORS` or in `FetchService`'s catch. With a dead browser the run
  stops before the table fallback is tried. Worth a look in WP-1.3.x.
