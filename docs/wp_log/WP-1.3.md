# WP-1.3 — Portal client

## Summary

Object-oriented rewrite of the legacy `chrome_driver.py` as the package `sivin.ingest.portal`.
`PortalSettings` holds URL, folder and tab names, the HTML selectors (nested `PortalSelectors`,
so a changed page is fixed in configuration) and the waiting times (`PortalTimeouts`);
`PortalCredentials.from_env()` reads `SIVIN_USER`/`SIVIN_PASSWORD` and masks the password.
`PortalClient` is a context manager around one WebDriver created by an injected
`WebDriverFactory` (`ChromeDriverFactory` registered as `chrome`); `ViewModelParser` reads the
devices from every section of the DotVVM viewmodel; `DownloadWatcher` only accepts a new,
complete, size-stable file and so fixes the legacy "newest file" bug; `PortalSession.run()`
records each failing device as `DeviceFailure` and continues. Everything is tested against a fake
browser that imitates the portal. **Not verified against the real portal.**

## Changed files

- `src/sivin/ingest/portal/__init__.py` — re-exports of the Selenium-free objects only.
- `src/sivin/ingest/portal/settings.py` — `PortalSettings`, `PortalSelectors`, `PortalTimeouts`.
- `src/sivin/ingest/portal/credentials.py` — `PortalCredentials`.
- `src/sivin/ingest/portal/errors.py` — `PortalError` and subclasses (`MissingCredentialsError`,
  `PortalLoginError`, `ViewModelError`, `ExportButtonNotFoundError`, `DownloadTimeoutError`).
- `src/sivin/ingest/portal/models.py` — `PortalDevice`, `DownloadedExport`, `DeviceFailure`,
  `SessionResult`.
- `src/sivin/ingest/portal/viewmodel.py` — `ViewModelParser`.
- `src/sivin/ingest/portal/clock.py` — `Clock` protocol, `SystemClock`.
- `src/sivin/ingest/portal/watcher.py` — `DownloadWatcher`, `DirectorySnapshot`.
- `src/sivin/ingest/portal/driver.py` — `WebDriverFactory` (ABC), `WebDriverFactoryRegistry`,
  `driver_factory_registry`, `ChromeDriverFactory`.
- `src/sivin/ingest/portal/client.py` — `PortalClient`, `xpath_literal`.
- `src/sivin/ingest/portal/session.py` — `PortalSession`.
- `tests/ingest/portal/` — `conftest.py` (fake portal driver, fake clock), tests of every module,
  `data/viewmodel_sample.json` (synthetic viewmodel).
- `docs/ingest.md`, `docs/wp_log/WP-1.3.md`.

## Public API

```python
# sivin.ingest.portal (no Selenium import)
PortalSettings(portal_url, folder_name, meteo_tab_name, selectors: PortalSelectors,
               timeouts: PortalTimeouts, headless, browser, download_dir, chrome_binary,
               chromedriver_path, chrome_arguments, partial_download_suffixes,
               ignored_download_prefixes)
    .resolved_against(paths: ProjectPaths) -> PortalSettings      # absolute paths
PortalSelectors(username_id, password_id, submit_css, spinner_id, viewmodel_id,
                link_xpath_template, tab_xpath_template, excel_button_xpath)
PortalTimeouts(element_wait_s, download_wait_s, poll_interval_s, settle_delay_s)
PortalCredentials(username, password); .from_env(environ=None)
PortalDevice(name); .sensor_id -> SensorId | None
DownloadedExport(device, path); DeviceFailure(device, reason)
SessionResult(downloads, failures); .files, .ok
ViewModelParser().parse(raw_json) -> list[PortalDevice]
DownloadWatcher(directory, timeout_s, poll_interval_s, clock, partial_suffixes,
                ignored_prefixes); .snapshot(); .wait_for_new_file(snapshot) -> Path
Clock (Protocol), SystemClock
PortalError, MissingCredentialsError, PortalLoginError, ViewModelError,
ExportButtonNotFoundError, DownloadTimeoutError

# sivin.ingest.portal.driver
WebDriverFactory(settings) (ABC): name: ClassVar[str]; create() -> WebDriver
driver_factory_registry.register (class decorator), .create(settings), .names()
ChromeDriverFactory(settings, environ=None, driver_class=webdriver.Chrome)
    .options(), .download_preferences(), .chrome_binary(), .chromedriver_path()

# sivin.ingest.portal.client
PortalClient(settings, credentials, driver_factory, parser=None, clock=None, watcher=None)
    with-block; login(); list_devices(); open_folder(); return_to_folder();
    download_export(device) -> Path

# sivin.ingest.portal.session
PortalSession(client).run(devices: Collection[SensorId] | None = None) -> SessionResult
```

## How it was verified

All commands in `/home/user/wt/wp-1.3` with the venv created by
`uv venv --python 3.12 .venv && uv pip install -e ".[dev,ingest,viz]"` (selenium 4.50.0).

- `make lint` → `All checks passed!`, `50 files already formatted`.
- `make type` → `Success: no issues found in 31 source files`.
- `make test` → `262 passed` (81 of them in `tests/ingest/portal/`).
- `make cov` → every module of `src/sivin/ingest/portal/` at 100 % (statements and branches),
  `TOTAL 1358 0 252 0 100%`, `Required test coverage of 85% reached. Total coverage: 100.00%`.
- What the tests cover (fake browser, no network): login call order (`get`, user name, password,
  submit); wrong password and missing login form → `PortalLoginError`; device list from the saved
  synthetic viewmodel, devices in a later section, duplicates, and eight broken structures →
  `ViewModelError`; a download returns the new file, never a pre-existing export of the same
  sensor; the watcher ignores pre-existing, `.crdownload`, `.tmp` and hidden files, waits for a
  rename and for a stable size (fake clock with hand-computed poll times), detects a file written
  by another thread (real clock); one device timing out while the other two succeed; Selenium
  timeouts and a missing export button recorded per device; a failing recovery; selection by
  `SensorId` with an unlisted sensor; the browser is closed after a login failure; password and
  user name never appear in logs at DEBUG level, in `repr`/`str`, or in error messages;
  `ChromeDriverFactory` options, download preferences and driver lookup (settings, `PATH`,
  webdriver-manager monkeypatched) without starting a browser; `import sivin.ingest.portal` does
  not load Selenium (subprocess check).
- The usage example of `docs/ingest.md` was run up to building the `PortalSession` (no browser
  started).

## What did not work / what was not verified

- **Not verified against the real portal.** The agents' sandbox cannot reach
  `lemon.e-service.cz`. The page flow, the selectors and the viewmodel path come from the legacy
  `chrome_driver.py`; the fake portal implements exactly that description, so the tests show the
  client follows the legacy flow, not that the portal still behaves that way.
- The viewmodel sample `tests/ingest/portal/data/viewmodel_sample.json` is **synthetic**: only the
  path `viewModel.Scene.Sections[*].Devices[*].DeviceName` comes from the legacy code; other keys
  are invented. A saved real viewmodel (with any personal data removed) would make the test
  stronger.
- Assumptions to check on the first real run: (a) the tab switch adds no browser history entry,
  so one `driver.back()` returns to the device list (the legacy script assumed the same);
  (b) reloading `portal_url` with an active session lands on the dashboard with the folder link,
  which is what `return_to_folder()` relies on after a failure; (c) the viewmodel input is
  readable after the folder click once the spinner is gone; (d) `settle_delay_s = 1 s` is enough
  (legacy used 3 s and 2 s), marked [to be verified]; (e) `--headless=new` with the download
  preferences saves files in this Chrome version.
- The optional smoke test with a real headless Chromium was **not written**: the sandbox has
  Chromium 141 (`/opt/pw-browsers/chromium-1194`) but only chromedriver 147, which cannot drive
  it, so the test would always be skipped here.
- webdriver-manager's download path was only tested with a monkeypatched `ChromeDriverManager`.

## Deviations

- The synthetic fixture lives in `tests/ingest/portal/data/` instead of `tests/fixtures/`
  (MIGRATION_PLAN §1.4), because `tests/fixtures/**` is outside this WP's Files scope.
- `PortalSettings` has a few fields beyond the brief, all with defaults: `browser` (key of the
  driver-factory registry), `chromedriver_path`, `chrome_arguments`, `partial_download_suffixes`,
  `ignored_download_prefixes` and `timeouts.settle_delay_s` (the one named fixed wait).
- The legacy `"safebrowsing.enabled": True` preference was not carried over (not needed for the
  Excel download; easy to add in `ChromeDriverFactory.download_preferences` if a warning appears).
- `PortalClient.login()` temporarily raises the level of Selenium's request logger
  (`selenium.webdriver.remote.remote_connection`) to WARNING while typing credentials, because
  that logger writes request bodies, including typed text, at DEBUG. This touches global logging
  state for a moment; it is restored in `finally`.

## Out of scope

- `config/sivin.yaml` / `sivin.config`: proposed section `ingest.portal` mapping to
  `PortalSettings` (WP-1.7). Because `sivin.ingest.portal` imports no Selenium, `sivin.config`
  can import `PortalSettings` without the `ingest` extra.
- `src/sivin/cli.py`: proposed command `sivin fetch [--sensor SERIAL ...] [--headed]
  [--download-dir PATH]`: resolve settings with `resolved_against(ProjectPaths.discover())`,
  `PortalCredentials.from_env()`, `driver_factory_registry.create(settings)`,
  `PortalSession(client).run(...)`; exit code non-zero when `not result.ok` (WP-1.7).
- `.env` loading: the legacy script used `python-dotenv`, which is not a dependency of `sivin`.
  Either the CLI loads `.env` (would need `python-dotenv` in `pyproject.toml`) or the user exports
  the variables; currently `docs/ingest.md` says "export them first".
- `.gitignore` already ignores `/data/` (the default `download_dir` is `data/downloads`) and a
  global `downloads/`; nothing to change.
- `chrome_driver.py` stays in the root until the legacy clean-up WP.

## Open questions for the owner

1. Can you save the portal's viewmodel once (browser developer tools → value of the hidden
   input `#__dot_viewmodel_root` on the `SIVIN VUT` page) with personal data removed? It would
   replace the synthetic sample.
2. Please run the client once locally with `headless=False` (see `docs/ingest.md`) and report
   whether all four exports download; the assumptions (a)–(e) above are what to watch.
3. Should a CLI run load `.env` itself (adds the dependency `python-dotenv`), or are exported
   environment variables enough?

## Review

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
