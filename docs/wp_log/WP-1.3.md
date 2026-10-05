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

Verdict: CHANGES_REQUESTED (round 1)

Gates observed by the reviewer in `/home/user/wt/wp-1.3`:

- `make lint` → `All checks passed!`, `50 files already formatted`.
- `make type` → `Success: no issues found in 31 source files`.
- `make test` → `262 passed`.
- `make cov` → every module in `src/sivin/ingest/portal/` at 100 % (statements and branches);
  `Total coverage: 100.00%`.
- `import sivin, sivin.config, sivin.ingest.portal` loads no `selenium*` module (checked).
- Scope: the diff `bcde7d9...HEAD` touches only `src/sivin/ingest/portal/**`,
  `tests/ingest/portal/**`, `docs/ingest.md` and this note.

Probes were run outside the repo (`/tmp/claude-0/review-1.3/probe.py`, `alt.py`) against the
real `DownloadWatcher` and the worker's fake portal.

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | `src/sivin/ingest/portal/watcher.py:92-129`, `client.py:266-269` | A download that times out but finishes later is attributed to the next device | open |
| major | `src/sivin/ingest/portal/client.py:271`, `session.py:225-231`, `tests/ingest/portal/conftest.py:211-217` | `back()` is unchecked, and the fake hard-codes "a tab switch adds no history". If `back()` does not return to the list, every second device fails | open |
| minor | `src/sivin/ingest/portal/client.py:255-265`, `settings.py:96-104` | The tab-switch and spinner race is wider than in the legacy script. The default `settle_delay_s=1` replaces legacy pauses of 3 + 1 s and 2 s, and no new explicit condition replaces them | open |
| minor | `src/sivin/ingest/portal/settings.py:61-67`, `client.py:299-310` | "First visible Excel button" is described as the *Historie meteorologických dat* button. Nothing checks the section, so this is an unverified claim | open |
| minor | `src/sivin/ingest/portal/client.py:269-272` | If `driver.back()` raises after a successful download, the device is recorded as failed and the file is missing from `SessionResult` | open |
| minor | `src/sivin/ingest/portal/watcher.py:130-136` | A zero-byte new file is accepted as a finished export | open |
| minor | `src/sivin/ingest/portal/client.py:67-77` | The temporary log-level change is process-global and not safe with concurrent clients. The level is restored on exceptions (verified) | open |
| minor | `tests/ingest/portal/conftest.py:157-186` | The fake portal never has a `#UpdateProgress` element, so no test runs the spinner wait (visible, then invisible), its timeout message, or the race | open |
| minor | `docs/ingest.md:190` | Troubleshooting says "every device after the first fails". With the current recovery it is every second device (see major 2) | open |
| nit | `src/sivin/ingest/portal/watcher.py:137` | A file that first appears on the last poll before the deadline is never confirmed, so the effective timeout is one poll shorter | open |
| nit | `src/sivin/ingest/portal/credentials.py:279-300` | A plain dataclass: `dataclasses.asdict`/`astuple`, pickling and `--showlocals` tracebacks expose the password. Consider pydantic `SecretStr` or `field(repr=False)` plus a docstring warning | open |
| nit | `tests/ingest/portal/test_client.py:195-207` | `test_credentials_never_reach_the_logs` cannot fail with the fake driver, because it never goes through Selenium's `RemoteConnection`. The real protection is tested separately (lines 210-218), but restoration on an exception is not tested | open |
| nit | `src/sivin/ingest/portal/driver.py:580-597` | On GitHub `ubuntu-latest` this works offline when `chromedriver` is on `PATH`. Also reading `$CHROMEWEBDRIVER` (set by the runner image) would make it independent of the symlink | open |

### Details

**Major 1: a late download is claimed by the next device.** Input: device A times out while
`A.xlsx.crdownload` is still being written. The session recovers and starts device B. B's
snapshot contains `A.xlsx.crdownload`, but not `A.xlsx`. When Chrome finishes A and renames it,
`A.xlsx` is a new name. Wrong behaviour: B's `wait_for_new_file` returns `A.xlsx`. The
`SessionResult` then maps A's data to device B, and B's own export becomes the "late" file for C.
The probe reproduced this: `B got: A.xlsx`. This silently mis-attributes data, which is what the
watcher was meant to prevent. Suggested fix (any one of these):
(a) In `wait_for_new_file`, also exclude a completed name `X` when `X + suffix` was in the
snapshot for any partial suffix. The watcher then also needs to track names that were partial at
snapshot time.
(b) After a `DownloadTimeoutError`, wait until no partial files remain in the directory, or mark
those names as "orphaned" before the next device.
(c) If the export file name contains the device or serial (the fake assumes
`MeteoData_<name> ...`; unknown for the real portal), check the returned name against the
device.
Add a test for this scenario.

**Major 2: `back()` versus reload, and an assumption the fake encodes.** The legacy script did
one `driver.back()`. In the new code the fake portal makes `back()` correct by construction:
`_switch_tab` sets `self.page` without a history entry. If the real "Meteorologická data" tab is
a route link, or a DotVVM postback that changes the URL, `back()` lands on the device page.
Simulation: the worker's fake with `_switch_tab` pushing history gives
`ok: [device1, device3]`, `fail: [device2 "No link for device"]`. With four sensors, half the
exports are lost on every run, and only every second run gets them, depending on the order. In
the real flow, a device's failure is then caused by stale navigation, not by the device.
Suggested fix: after `back()`, explicitly wait for the device list, for example for the next
device's link or the folder/viewmodel element, with a short timeout. If it is not there, call
`return_to_folder()` proactively. Alternatively, always use `return_to_folder()` after each
device: it costs one reload but is deterministic. Optionally, `PortalSession` can retry a device
once after a recovery. Add a fake variant whose tab switch pushes history, and a test that all
devices still succeed.

**Minor 3: race against the tab switch.** After the JS click on the tab, `_wait_until_idle()`
can pass before DotVVM even shows `#UpdateProgress`. `invisibility_of_element_located` is true
for an absent or not-yet-shown element. Then `first_visible` returns as soon as *any* Excel
button is visible. The legacy comment says other tabs carry Excel buttons too. If the default
device tab shows one and the tab switch or postback has not taken effect after 1 s, the wrong
export is clicked. The legacy script waited 2 s at this point (and 3 + 1 s after the device
click). Suggestion: set the defaults to the legacy pauses (3 s / 2 s) until the first real run.
Better, wait for an explicit condition, such as the tab link becoming active or the button
being inside the meteorological tab's pane. See minor 4.

**Minor 4: Excel button section.** Selection is by DOM order among visible buttons. Neither the
code nor the fake checks that the button belongs to *Historie meteorologických dat*. The
setting's description states this as a fact. Reword it as an assumption [to be verified], or
scope the default XPath to the section heading once the real HTML is known (open question 1
could cover a saved page).

**Minor 5: `back()` failing after a successful download.** `download_export` calls
`self._driver.back()` after the file has been detected (`client.py:271`). A
`WebDriverException` there turns a completed download into a `DeviceFailure`, and the path is
lost from the result. Suggestion: return the path and let the session do the navigation in a
separate step, with its own error handling.

**Minor 6: zero-byte file.** Probe: an empty `empty.xlsx` is returned (size 0 stable in two
polls). An empty file is never a valid export, so require `size > 0`. It is also not certain
that Chrome never creates an empty placeholder under the final name.

**Minor 7: logging.** `_secret_input_logging` restores the level in `finally`, which the probe
verified with an exception inside the block. However, with two `PortalClient`s in parallel
threads, client A can restore `NOTSET` while client B is typing. B's `send_keys` body is then
logged at DEBUG. A `logging.Filter` on that logger that drops records during a thread-local or
contextvar "typing secrets" flag would be thread-safe. Single-threaded use, which is the
planned CLI, is fine. Exceptions: Selenium's `send_keys` errors do not echo the text, and the
code takes no screenshots and attaches no chromedriver log, so I found no other leak path.

### Comparison with the legacy `chrome_driver.py` (step by step)

- Login: same steps. Native `click()` on submit (legacy: native) and an explicit presence wait
  for `#username`. The legacy's spinner wait before `driver.get` was a bug and is rightly
  dropped.
- Folder: JS click after `element_to_be_clickable` (same as legacy), plus a spinner wait. The
  viewmodel is read after an explicit presence wait (legacy: immediately). This is fine.
- Device link: presence wait + JS click (same). Legacy: `sleep(3)`, scroll to the page bottom,
  `sleep(1)`. New: settle 1 s + spinner wait, no scroll to the bottom. The scroll is irrelevant
  for JS clicks unless the page lazy-loads on scroll (unknown).
- Tab: `element_to_be_clickable` + JS click (same). Legacy: spinner + `sleep(2)`. New: spinner +
  settle 1 s (see minor 3).
- Excel: first `is_displayed()` button (same rule), now inside an explicit wait instead of a
  one-shot `find_elements`, which is better. `scrollIntoView` + JS click (same). The 1 s pause
  before the click and the 5 s pause after it are dropped. The watcher makes the 5 s pause
  unnecessary.
- Download detection: set difference + stable size. This fixes the legacy "newest file" bug,
  except for major 1. The ` (1)` suffix for repeated names gives a new name and is detected
  (probe: `export (1).xlsx`).
- After the device: `back()` (same as legacy) on success. On failure, reload + folder, where the
  legacy script did `driver.get("tvoje_url…")`, a bug. See major 2.
- Chrome prefs: same, except `safebrowsing.enabled`. That is an accepted deviation; `.xlsx` is
  not a dangerous file type.

### Headless CI

`ChromeDriverFactory` passes an explicit `ChromeService(executable_path=…)`. When `chromedriver`
is on `PATH` (the GitHub `ubuntu-latest` image ships a matching Chrome and chromedriver), neither
webdriver-manager nor Selenium Manager is contacted, so no network is needed. webdriver-manager
is imported lazily, only in the fallback. `--headless=new` honours the download prefs. On the
runner (non-root) no `--no-sandbox` is needed, and the docs say when to add it. Not run here,
because the sandbox's chromedriver 147 does not match Chromium 141.

### Deviations assessment

- Fixture under `tests/ingest/portal/data/`: accepted. It is inside the Files scope and labelled
  synthetic.
- Extra settings fields (`browser`, `chromedriver_path`, `chrome_arguments`, suffix/prefix
  tuples, `settle_delay_s`): accepted. All are described, with units and defaults.
- Dropping `safebrowsing.enabled`: accepted (see above).
- Temporary raising of Selenium's request-logger level: accepted for the single-threaded CLI. It
  is restored on exceptions. See minor 7 for a thread-safe alternative.
- The real-browser smoke test was not written: accepted, and the reason (version mismatch) is
  plausible.
- "Not verified against the real portal" is stated explicitly, as required.
