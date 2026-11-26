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

Verdict: (pending)

| Severity | File:line | Finding | Status |
|---|---|---|---|
