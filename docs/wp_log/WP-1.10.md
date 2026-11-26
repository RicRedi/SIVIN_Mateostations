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
- `make test` → 2112 passed.
- `make cov` → 2112 passed, total 99.81 %. Changed/new modules: `table.py`, `table_file.py`,
  `sources.py`, `session.py`, `client.py`, `models.py`, `settings.py`, `errors.py`,
  `app/fetch.py` 100 %; `table_page.py` 97 % (two stale-element branches not hit).
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

## Out of scope

- `src/sivin/app/factory.py` (`ServiceFactory.fetch_service`) does **not** pass the store yet, so
  `sivin fetch` and `sivin run` read the whole table history whenever the table is used. The
  change is one argument:
  `FetchService(..., self._redactor, last_timestamps=StoreLastTimestamps(self.store()))`
  (import `StoreLastTimestamps` from `sivin.app.fetch` inside the method). Not in this WP's files;
  see question 1.
- `docs/architecture.md` and `docs/data-format.md` do not mention the table source; a sentence
  each would help (not in this WP's files).

## Open questions for the owner

1. **Wiring in `ServiceFactory` (blocking for the incremental behaviour).** Without the line
   above, every run that falls back reads the full history (for 77680921: 9562 rows, 2 pages)
   and writes all of it. The store skips identical rows, but rows that came from an export
   differ in precision (question 2), so with `prefer_newest` the table's values would replace the
   stored export values. May the orchestrator (or a fix round of this WP) add the line to
   `factory.py`?
2. **Precision of table vs export.** Which value should win when the same timestamp exists from
   both sources? With the wiring, the table never re-sends stored rows; but a later successful
   export (full history) would replace the table's 4-decimal values with rounded ones under
   `prefer_newest`. Options: accept it, round the table values to the export's precision before
   writing (would need the export's per-column precision, not known for sure), or use
   `prefer_existing`.
3. **Config shape.** The brief suggested `ingest.portal.source: export_then_table | table_only |
   export_only`. I made it an ordered list `ingest.portal.sources: [export, table]` (`[table]`,
   `[export]` for the other two modes), so a new source is a registered class without a new
   mode name. Fine, or should the enum be added as well?
4. **File name.** The brief suggested `MeteoData_<portal name>_table_<YYYYMMDD_HHMMSS>.csv`. With
   the portal's spaced device name (`8615620 77680921`) that name is not recognised by
   `SensorId`, so the label is written in parentheses like the export's `(VUT)`:
   `MeteoData_8615620 77680921 (table)_20261126_060000.csv` (time = local time of writing).
5. **Daylight-saving edge.** Table times are compared as local wall-clock time; only if the last
   stored measurement lies in the repeated autumn hour could up to an hour of rows be taken for
   stored ones. Acceptable?

## Review

Verdict: (pending)

| Severity | File:line | Finding | Status |
|---|---|---|---|
