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

**Round 2** addressed the review (round 1). The watcher never gives a late download to the next
device: final names of files that were partial at snapshot time are excluded, files left by a
timeout are remembered, and an export naming another sensor's serial is skipped. Empty files
are rejected (`DownloadIncompleteError`). The deadline gets one confirmation poll. After each
download the session calls `back_to_device_list()`, which checks for the device list and
reloads when `back()` did not reach it. A failing device is retried once after recovery, and a
failure after the file was detected no longer loses the file. The Excel button is looked for
inside the *Historie meteorologických dat* section, with a WARNING fallback. The settle pauses
are back at the legacy 3 s / 2 s. Page operations moved to a new `PortalPage` class. The
password is a `Secret`. `$CHROMEWEBDRIVER` is read. `wp/0.1-foundation` (8f354c0) is merged.
Statuses per finding are in the *Review* table.

## Changed files

- `src/sivin/ingest/portal/__init__.py` — re-exports of the Selenium-free objects only.
- `src/sivin/ingest/portal/settings.py` — `PortalSettings`, `PortalSelectors`, `PortalTimeouts`.
- `src/sivin/ingest/portal/credentials.py` — `PortalCredentials`, `Secret`.
- `src/sivin/ingest/portal/errors.py` — `PortalError` and subclasses (`MissingCredentialsError`,
  `PortalLoginError`, `ViewModelError`, `ExportButtonNotFoundError`, `DownloadTimeoutError`,
  `DownloadIncompleteError`).
- `src/sivin/ingest/portal/models.py` — `PortalDevice`, `DownloadedExport`, `DeviceFailure`,
  `SessionResult`.
- `src/sivin/ingest/portal/viewmodel.py` — `ViewModelParser`.
- `src/sivin/ingest/portal/clock.py` — `Clock` protocol, `SystemClock`.
- `src/sivin/ingest/portal/watcher.py` — `DownloadWatcher`, `DirectorySnapshot`.
- `src/sivin/ingest/portal/driver.py` — `WebDriverFactory` (ABC), `WebDriverFactoryRegistry`,
  `driver_factory_registry`, `ChromeDriverFactory`.
- `src/sivin/ingest/portal/client.py` — `PortalClient`.
- `src/sivin/ingest/portal/page.py` — `PortalPage`, `xpath_literal` (round 2).
- `src/sivin/ingest/portal/session.py` — `PortalSession`.
- `tests/ingest/portal/` — `conftest.py` (fake portal driver, fake clock), tests of every module,
  `data/viewmodel_sample.json` (synthetic viewmodel).
- `docs/ingest.md`, `docs/wp_log/WP-1.3.md`.

## Public API

```python
# sivin.ingest.portal (no Selenium import)
PortalSettings(portal_url, folder_name, meteo_tab_name, export_section_name,
               attempts_per_device, min_export_size_bytes, selectors: PortalSelectors,
               timeouts: PortalTimeouts, headless, browser, download_dir, chrome_binary,
               chromedriver_path, chrome_arguments, partial_download_suffixes,
               ignored_download_prefixes)
    .resolved_against(paths: ProjectPaths) -> PortalSettings      # absolute paths
PortalSelectors(username_id, password_id, submit_css, spinner_id, viewmodel_id,
                link_xpath_template, tab_xpath_template, excel_button_xpath,
                section_button_xpath_template)
PortalTimeouts(element_wait_s, download_wait_s, poll_interval_s, device_settle_s,
               tab_settle_s, list_check_s)
Secret(value); .reveal()                                         # masked, not picklable
PortalCredentials(username, password: Secret); .from_env(environ=None)
PortalDevice(name); .sensor_id -> SensorId | None
DownloadedExport(device, path); DeviceFailure(device, reason)
SessionResult(downloads, failures); .files, .ok
ViewModelParser().parse(raw_json) -> list[PortalDevice]
DownloadWatcher(directory, timeout_s, poll_interval_s, clock, partial_suffixes,
                ignored_prefixes, min_size_bytes); .snapshot() -> DirectorySnapshot(names, pending);
    .wait_for_new_file(snapshot, expected: SensorId | None = None) -> Path; .orphaned
Clock (Protocol), SystemClock
PortalError, MissingCredentialsError, PortalLoginError, ViewModelError,
ExportButtonNotFoundError, DownloadTimeoutError, DownloadIncompleteError

# sivin.ingest.portal.driver
WebDriverFactory(settings) (ABC): name: ClassVar[str]; create() -> WebDriver
driver_factory_registry.register (class decorator), .create(settings), .names()
ChromeDriverFactory(settings, environ=None, driver_class=webdriver.Chrome)
    .options(), .download_preferences(), .chrome_binary(), .chromedriver_path()

# sivin.ingest.portal.page
PortalPage(driver, settings, clock); xpath_literal(text)

# sivin.ingest.portal.client  (single-threaded use)
PortalClient(settings, credentials, driver_factory, parser=None, clock=None, watcher=None)
    with-block; settings; login(); list_devices(); open_folder(); return_to_folder();
    download_export(device) -> Path; back_to_device_list()

# sivin.ingest.portal.session
PortalSession(client).run(devices: Collection[SensorId] | None = None) -> SessionResult
```

## How it was verified

Round 2 (all commands in `/home/user/wt/wp-1.3` after merging `wp/0.1-foundation` at 8f354c0):

- `make lint` → `All checks passed!`, `51 files already formatted`.
- `make type` → `Success: no issues found in 32 source files`.
- `make test` → `297 passed` (107 of them in `tests/ingest/portal/`).
- `make cov` → every module of `src/sivin/ingest/portal/` at 100 % (statements and branches),
  `TOTAL 1561 0 300 0 100%`, `Required test coverage of 85% reached. Total coverage: 100.00%`.
- The reviewer's `probe.py` (import of `xpath_literal` changed to `sivin.ingest.portal.page`)
  re-run: B no longer gets `A.xlsx`. B's wait now times out, which is right because the probe
  never writes a B file. The zero-byte case now raises `DownloadIncompleteError`, and the
  last-poll file is now returned.
- New tests (fake browser, fake clock, no network):
  - the review's late-download scenario, both as a watcher unit test and end to end
    (`late` behaviour, 1 and 2 attempts), with THIRD getting its own file;
  - an orphan ignored by a later wait;
  - another sensor's export skipped (legacy name `MeteoData_8615620 77678271.xlsx`);
  - empty file → `DownloadIncompleteError`, and a placeholder that fills later is accepted;
  - the confirmation poll at the deadline;
  - both history variants (`tab_adds_history` False/True) succeed for all devices, with 0
    and 3 reloads;
  - a flaky device succeeds on the retry;
  - a failing `back()` keeps all downloads;
  - the section button is preferred over the default tab's visible Excel button, with a
    WARNING fallback;
  - spinner polls counted and a stuck spinner's timeout message;
  - an export name without serial gives a WARNING;
  - `Secret` hidden in `repr`, `str`, `format`, `asdict`, `astuple` and `deepcopy`, and
    pickling refused;
  - the fake element logs typed text through Selenium's request logger like
    `RemoteConnection` does. A control test shows that text is captured without the guard, and
    the login test shows the password is not; the level is restored after an exception;
  - `$CHROMEWEBDRIVER` lookup and its fallback.

Round 1:

- `make lint` → `All checks passed!`, `50 files already formatted`; `make type` → `Success: no
  issues found in 31 source files`; `make test` → `262 passed`; `make cov` → 100 %.

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
  which is what `return_to_folder()` relies on after a failure, and the first device's link is
  only on the device list page (the marker `back_to_device_list()` waits for); (c) the viewmodel input is
  readable after the folder click once the spinner is gone; (d) the settle pauses (legacy 3 s / 2 s, now the
  defaults) are [to be tuned]; (f) the section XPath (heading → nearest ancestor with an Excel
  button) matches the real HTML, otherwise the WARNING fallback is used; (g) the real export
  names contain the serial, as the legacy log suggests; (e) `--headless=new` with the download
  preferences saves files in this Chrome version.
- The optional smoke test with a real headless Chromium was **not written**: the sandbox has
  Chromium 141 (`/opt/pw-browsers/chromium-1194`) but only chromedriver 147, which cannot drive
  it, so the test would always be skipped here.
- webdriver-manager's download path was only tested with a monkeypatched `ChromeDriverManager`.

## Deviations

- The synthetic fixture lives in `tests/ingest/portal/data/` instead of `tests/fixtures/`
  (MIGRATION_PLAN §1.4), because `tests/fixtures/**` is outside this WP's Files scope.
- `PortalSettings` has fields beyond the brief, all with defaults: `browser` (key of the
  driver-factory registry), `chromedriver_path`, `chrome_arguments`, `partial_download_suffixes`,
  `ignored_download_prefixes`, and since round 2 `export_section_name`, `attempts_per_device`,
  `min_export_size_bytes`, `selectors.section_button_xpath_template`, `timeouts.device_settle_s`,
  `timeouts.tab_settle_s` and `timeouts.list_check_s` (replacing `settle_delay_s`).
- `_WIRE_LOGGER_LOCK` in `client.py` is a module-level `threading.Lock` (module-level state that
  is not a registry), requested in round 2 to serialise the temporary log-level change.
- The legacy `"safebrowsing.enabled": True` preference was not carried over (not needed for the
  Excel download; easy to add in `ChromeDriverFactory.download_preferences` if a warning appears).
- `PortalClient.login()` temporarily raises the level of Selenium's request logger
  (`selenium.webdriver.remote.remote_connection`) to WARNING while typing credentials, because
  that logger writes request bodies, including typed text, at DEBUG. This touches global logging
  state for a moment; it is restored in `finally` and serialised by a lock. The client is
  documented as single-threaded.

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
- Downloaded late files (from timed-out attempts) stay in `download_dir` and are reported only in
  the log. The store or the CLI (WP-1.4/WP-1.7) may want to quarantine or clean them.
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
| major | `src/sivin/ingest/portal/watcher.py:92-129`, `client.py:266-269` | A download that times out but finishes later is attributed to the next device | fixed (round 2): `DirectorySnapshot.pending` excludes the final names of partial files; names left by a timeout are orphaned; an export naming another serial is skipped (WARNING); a name without a serial is accepted with a WARNING; tests in `test_watcher.py` and `test_session.py::test_a_late_download_is_never_given_to_the_next_device` |
| major | `src/sivin/ingest/portal/client.py:271`, `session.py:225-231`, `tests/ingest/portal/conftest.py:211-217` | `back()` is unchecked, and the fake hard-codes "a tab switch adds no history". If `back()` does not return to the list, every second device fails | fixed (round 2): `PortalClient.back_to_device_list()` waits `list_check_s` for the first device's link and otherwise reloads and reopens the folder; one retry per device after recovery (`attempts_per_device=2`); the fake has a `tab_adds_history` variant and both variants are tested |
| minor | `src/sivin/ingest/portal/client.py:255-265`, `settings.py:96-104` | The tab-switch and spinner race is wider than in the legacy script. The default `settle_delay_s=1` replaces legacy pauses of 3 + 1 s and 2 s, and no new explicit condition replaces them | fixed (round 2): defaults back to the legacy 3 s / 2 s (`device_settle_s`, `tab_settle_s`, [to be tuned]); the button wait is scoped to the export section, so a visible button there also shows that the tab is active |
| minor | `src/sivin/ingest/portal/settings.py:61-67`, `client.py:299-310` | "First visible Excel button" is described as the *Historie meteorologických dat* button. Nothing checks the section, so this is an unverified claim | fixed (round 2): `selectors.section_button_xpath_template` + `export_section_name`; fallback to the first visible button with a WARNING; the XPath is marked [to be verified] |
| minor | `src/sivin/ingest/portal/client.py:269-272` | If `driver.back()` raises after a successful download, the device is recorded as failed and the file is missing from `SessionResult` | fixed (round 2): `download_export` no longer navigates; the session records the download, then calls `back_to_device_list()` separately and only logs its failure |
| minor | `src/sivin/ingest/portal/watcher.py:130-136` | A zero-byte new file is accepted as a finished export | fixed (round 2): `min_export_size_bytes` (default 1); only too small files by the deadline → `DownloadIncompleteError` |
| minor | `src/sivin/ingest/portal/client.py:67-77` | The temporary log-level change is process-global and not safe with concurrent clients. The level is restored on exceptions (verified) | fixed (round 2): a module-level lock serialises the change; the client is documented as single-threaded (`client.py` docstring, `docs/ingest.md`) |
| minor | `tests/ingest/portal/conftest.py:157-186` | The fake portal never has a `#UpdateProgress` element, so no test runs the spinner wait (visible, then invisible), its timeout message, or the race | fixed (round 2): the fake shows `#UpdateProgress` for 2 polls after each action; tests count the polls and check the stuck-spinner message |
| minor | `docs/ingest.md:190` | Troubleshooting says "every device after the first fails". With the current recovery it is every second device (see major 2) | fixed (round 2): the troubleshooting entry is rewritten for the new reload behaviour |
| nit | `src/sivin/ingest/portal/watcher.py:137` | A file that first appears on the last poll before the deadline is never confirmed, so the effective timeout is one poll shorter | fixed (round 2): one confirmation poll after the deadline when a file is still unconfirmed; tested |
| nit | `src/sivin/ingest/portal/credentials.py:279-300` | A plain dataclass: `dataclasses.asdict`/`astuple`, pickling and `--showlocals` tracebacks expose the password. Consider pydantic `SecretStr` or `field(repr=False)` plus a docstring warning | fixed (round 2): `Secret` wrapper (masked repr/str/format, kept by `asdict`, pickling refused); tested |
| nit | `tests/ingest/portal/test_client.py:195-207` | `test_credentials_never_reach_the_logs` cannot fail with the fake driver, because it never goes through Selenium's `RemoteConnection`. The real protection is tested separately (lines 210-218), but restoration on an exception is not tested | fixed (round 2): the fake logs typed text through the Selenium request logger; a control test shows the leak without the guard; restoration after an exception is tested |
| nit | `src/sivin/ingest/portal/driver.py:580-597` | On GitHub `ubuntu-latest` this works offline when `chromedriver` is on `PATH`. Also reading `$CHROMEWEBDRIVER` (set by the runner image) would make it independent of the symlink | fixed (round 2): `$CHROMEWEBDRIVER/chromedriver` checked before `PATH`; tested |

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

### Round 2

Verdict: APPROVE (round 2)

Reviewed commits `1b8e09e` and `26e14a6`; `e1b1480` merges the reviewed foundation. Both worker
commits touch only `src/sivin/ingest/portal/**`, `tests/ingest/portal/**`, `docs/ingest.md` and
this note.

Gates observed by the reviewer:

- `make lint` → `All checks passed!`, `51 files already formatted`.
- `make type` → `Success: no issues found in 32 source files`.
- `make test` → `297 passed`.
- `make cov` → every module of `src/sivin/ingest/portal/` (now including `page.py`) at 100 %
  (statements and branches); `Total coverage: 100.00%`.
- `import sivin.config, sivin.ingest.portal` still loads no `selenium*` module.

**Re-run probes** (`/tmp/claude-0/review-1.3/probe2.py`, `alt2.py`, run against the real
watcher and the worker's fake portal):

- Late download: after A's timeout, B's snapshot has `pending={'A.xlsx'}`. B ignores the renamed
  `A.xlsx` and returns its own `B.xlsx`.
- Session with a `late` device: the late file is never given to the next device. The other
  devices succeed and the late device fails after 2 attempts.
- History variant (`tab_adds_history=True`): all 3 devices download.
  `back_to_device_list()` falls back to a reload each time (4 `get`s).
- Flaky export button: the first attempt fails and the retry succeeds.
- Empty file: `DownloadIncompleteError`. An empty file that later fills is accepted.
- File that appears on the last poll: accepted after the extra confirmation poll.
- Serial matching: `SensorId.parse` uses `fullmatch`. So `export.xlsx`, `20260301_223857.xlsx`
  and other unknown names give no serial and are never falsely treated as another sensor's
  file. A name with another sensor's serial is skipped and orphaned.
- `Secret`: masked in `repr`, `str`, f-strings and `asdict`. Pickling raises `TypeError`, and
  `copy` and `deepcopy` keep the value masked.
- Lock: a second thread waits until the first one has restored the level. The level is
  restored after an exception and the lock is released.

**Legacy navigation semantics:** unchanged. The order is: spinner wait, presence wait and JS
click on the device link, `device_settle_s` (3 s, the legacy value), spinner wait, clickable
wait and JS click on the tab, spinner wait, `tab_settle_s` (2 s, the legacy value), then the
visible Excel button, scroll into view and JS click, then the watcher, then `back()`. The new
parts only add to this: the check after `back()` with a reload fallback, and the button search
that prefers the export section and falls back to the legacy "first visible" rule.

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | `src/sivin/ingest/portal/watcher.py:244-248` | `pending` maps a partial file to a final name only by stripping the suffix. If Chrome is still using an `Unconfirmed NNN.crdownload` name at the timeout, and the export name has no serial, the late file is still given to the next device. The probe reproduced this: `Unconfirmed 123.crdownload` → `A.xlsx` was accepted for B. With the documented `MeteoData_<device> <serial> …` names, the serial check catches it (probe 2b). Suggestion: on timeout, also orphan the next *complete* name that appears while that partial file disappears, or document the dependence on serial-bearing names. Not blocking | open |
| minor | `src/sivin/ingest/portal/client.py:321-325` | The device-list marker is the first device's link. If device pages show that link too (breadcrumb or sidebar), `back_to_device_list()` accepts the wrong page. Simulated: every next device fails attempt 1 and only the retry saves it, at the cost of an `element_wait_s` timeout and a reload per device. Suggestion: use a marker that exists only on the folder page, configurable as a selector, after the first real run | open |
| nit | `src/sivin/ingest/portal/credentials.py:99-101` | `PortalCredentials("u", "plain")` with a `str` password is accepted at runtime (only mypy objects). `repr` then shows the plain password, and `login()` would fail on `.reveal()`. Suggestion: check `isinstance(password, Secret)`, or wrap it, in `__post_init__` | open |
| nit | `src/sivin/ingest/portal/page.py:468-476` | When the default section XPath does not match the real portal, every device and every attempt waits the full `element_wait_s` (15 s) before the fallback. This is acceptable because it logs a WARNING; tune it on the first real run | open |
| nit | `src/sivin/ingest/portal/watcher.py:215-221` | A device's own late export from attempt 1 is orphaned during attempt 2, even when its serial matches. This is safe and conservative; the file stays in `download_dir` but is not reported in `SessionResult` | open |

All round-1 findings are verified as fixed, as the statuses above state. No blockers or majors
remain. The hand-off note still states "Not verified against the real portal".
