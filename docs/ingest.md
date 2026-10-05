# Ingest: downloading exports from the data provider's portal

The sensors' data provider, `https://lemon.e-service.cz/`, is a [DotVVM](https://www.dotvvm.com/)
web application **without an API** (owner decision, MIGRATION_PLAN §0.5). The exports are
downloaded by driving a real browser (Chrome/Chromium through Selenium) through the same clicks
a person would make. The code is in `src/sivin/ingest/portal/`; it replaces the legacy
`chrome_driver.py`.

> **Status:** the client has been tested only against a fake browser that imitates the portal's
> pages as the legacy script describes them. It has **not been run against the real portal**
> (the agents' sandbox cannot reach it). The first real run must be watched; see
> [Troubleshooting](#troubleshooting).

## Components

| Class | Module | Responsibility |
|---|---|---|
| `PortalSettings` (+ `PortalSelectors`, `PortalTimeouts`) | `settings.py` | URL, folder and tab names, HTML selectors, waiting times, browser options. Frozen pydantic models, unknown keys are rejected. |
| `PortalCredentials` | `credentials.py` | User name and password, read **only** from the environment (`from_env()`); `repr` masks the password. |
| `WebDriverFactory`, `ChromeDriverFactory`, `driver_factory_registry` | `driver.py` | Start the browser with download preferences. New browsers are new registered subclasses. |
| `PortalClient` | `client.py` | Context manager owning one browser: `login()`, `list_devices()`, `download_export(device)`, `return_to_folder()`. |
| `ViewModelParser` | `viewmodel.py` | Pure parser of the DotVVM viewmodel JSON into `PortalDevice` objects. |
| `DownloadWatcher` | `watcher.py` | Detects the file a click produced: a *new* file (not in the snapshot taken before the click), not partial, with a stable size. |
| `PortalSession` | `session.py` | One run: login, device list, one export per device; a failing device is recorded, the run goes on. Returns `SessionResult`. |

`import sivin.ingest.portal` loads only the Selenium-free parts (settings, credentials, value
objects, errors, parser, watcher), so reading the configuration never needs the `ingest` extra.
Import `PortalClient`, `PortalSession` and the driver factories from their modules.

## How a run works, step by step

1. **Start the browser.** `ChromeDriverFactory` starts Chrome (headless by default, window
   1920×1080) with the preferences `download.default_directory = <download_dir>`,
   `download.prompt_for_download = false`, `download.directory_upgrade = true` and
   `profile.default_content_setting_values.automatic_downloads = 1` (several downloads without
   asking).
2. **Log in.** Open `portal_url`, wait for `#username`, type the user name, type the password into
   `#password`, click `input[type='submit']`. The login counts as successful when the link of the
   folder (`SIVIN VUT`) appears; otherwise `PortalLoginError` (wrong credentials or a changed page)
   stops the run.
3. **Open the folder and list devices.** Click the folder link (through JavaScript, like the legacy
   script), wait until the spinner `#UpdateProgress` is invisible, read the `value` of the hidden
   input `#__dot_viewmodel_root` and parse it: `viewModel.Scene.Sections[*].Devices[*].DeviceName`
   gives the device names (e.g. `8615620 77678271`). All sections are searched, not only the
   first; duplicates are dropped. A structure without any `Devices` list raises
   `ViewModelError`. New devices in the portal are therefore downloaded without any change here.
4. **For each device:**
   1. wait for the spinner to disappear, click the link containing the device name,
      pause `settle_delay_s`, wait for the spinner;
   2. click the tab containing `Meteorologická data`, wait for the spinner, pause
      `settle_delay_s`;
   3. wait for the first **visible** button matching `excel_button_xpath`
      (`button` with an `i.mdi-file-excel` icon; the other tabs contain hidden ones) — this is the
      button of the *Historie meteorologických dat* section;
   4. take a snapshot of the download directory, scroll the button into view and click it;
   5. wait until a new complete file appears (see below) and return its path;
   6. `driver.back()` to the device list (as the legacy script did; this assumes that switching
      the tab adds no browser history entry).
5. **A failing device** (any Selenium exception, a missing button, a download timeout, a file
   system error) is recorded as `DeviceFailure(device, reason)`. The client then reloads
   `portal_url` and opens the folder again (`return_to_folder()`), and the run continues with the
   next device. If even that fails, it is logged and the next devices fail on their own.
6. **Close the browser** (always, also after an error) and return
   `SessionResult(downloads, failures)`. `result.ok` is `True` when nothing failed; the caller
   decides the exit code.

### How a finished download is recognised

`DownloadWatcher` fixes the legacy bug of reporting the newest file of the directory, which
returned the *previous* export when a download failed:

- before the click it records the names of all files in the directory;
- after the click it polls every `poll_interval_s` and only considers files that were **not**
  there before, whose names do not end with `.crdownload` or `.tmp` and do not start with `.`
  (Chrome on Linux first writes a hidden `.com.google.Chrome.*` file);
- a candidate is accepted when its size is the same in two consecutive polls;
- after `download_wait_s` without such a file it raises `DownloadTimeoutError`.

When the browser saves a second export of the same day, it appends ` (1)` to the name; that is a
new name and therefore detected. `SensorId.parse` understands these names.

Only explicit waits (`WebDriverWait` with expected conditions) are used. The one fixed pause is
`timeouts.settle_delay_s` (default 1 s, the legacy script slept 3 s and 2 s), because DotVVM may
still re-render after the spinner has gone; it is **to be verified** on the real portal and can
be set to 0.

## Settings

Proposed configuration section: `ingest.portal` in `config/sivin.yaml` (wired into
`SivinConfig` by the integration workpackage). All fields have defaults equal to the legacy
values.

| Key | Default | Unit | Meaning |
|---|---|---|---|
| `portal_url` | `https://lemon.e-service.cz/` | URL | Start page (redirects to the login). |
| `folder_name` | `SIVIN VUT` | text | Folder link that lists our devices. |
| `meteo_tab_name` | `Meteorologická data` | text | Device tab with the export. |
| `selectors.username_id` | `username` | HTML id | User name input. |
| `selectors.password_id` | `password` | HTML id | Password input. |
| `selectors.submit_css` | `input[type='submit']` | CSS | Login button. |
| `selectors.spinner_id` | `UpdateProgress` | HTML id | DotVVM progress spinner. |
| `selectors.viewmodel_id` | `__dot_viewmodel_root` | HTML id | Hidden input with the viewmodel JSON. |
| `selectors.link_xpath_template` | `//a[contains(., {text})]` | XPath | Folder and device links; `{text}` becomes a quoted literal. |
| `selectors.tab_xpath_template` | `//a[contains(text(), {text})]` | XPath | Tab link. |
| `selectors.excel_button_xpath` | `//button[.//i[contains(@class, 'mdi-file-excel')]]` | XPath | Excel export buttons (the first visible one is clicked). |
| `timeouts.element_wait_s` | 15 | s | Maximum wait for an element or the spinner. |
| `timeouts.download_wait_s` | 30 | s | Maximum wait for the export file. |
| `timeouts.poll_interval_s` | 0.5 | s | Polling interval of waits and of the download watcher. |
| `timeouts.settle_delay_s` | 1.0 | s | Fixed pause after opening a device and the tab ([to be verified]). |
| `headless` | `true` | flag | Run without a window. Set `false` to watch the browser locally. |
| `browser` | `chrome` | name | Registered `WebDriverFactory`. |
| `download_dir` | `data/downloads` | path | Relative to the project root (ignored by git via `/data/`); the caller resolves it with `PortalSettings.resolved_against(ProjectPaths)`. |
| `chrome_binary` | unset | path | Browser executable; falls back to `$CHROME_BINARY`, then to the browser chromedriver finds. |
| `chromedriver_path` | unset | path | chromedriver; falls back to `chromedriver` on `PATH`, then to webdriver-manager (downloads a matching driver, needs internet). |
| `chrome_arguments` | `["--window-size=1920,1080"]` | flags | Extra Chrome arguments; add `--no-sandbox` only when running as root in a container. |
| `partial_download_suffixes` | `[".crdownload", ".tmp"]` | suffixes | Unfinished downloads. |
| `ignored_download_prefixes` | `["."]` | prefixes | Hidden temporary files. |

### Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `SIVIN_USER` | yes | Portal user name. |
| `SIVIN_PASSWORD` | yes | Portal password. |
| `CHROME_BINARY` | no | Chrome/Chromium executable when `chrome_binary` is not set. |

Credentials come **only** from the environment: locally from `.env` (git-ignored), in GitHub
Actions from repository secrets. They are never written to the configuration, never logged and
masked in `repr`. While they are typed, Selenium's request logger
(`selenium.webdriver.remote.remote_connection`, which logs request bodies at DEBUG level) is
raised to WARNING, so a DEBUG run does not leak them either.

## Running it locally

The command `sivin fetch` is wired into the CLI by the integration workpackage (WP-1.7);
proposed options: `--sensor <serial>` (repeatable), `--headed`, `--download-dir`. Until then the
client can be driven from Python:

```python
import logging

from sivin.ingest.portal.client import PortalClient
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.portal.driver import driver_factory_registry
from sivin.ingest.portal.session import PortalSession
from sivin.ingest.portal.settings import PortalSettings
from sivin.paths import ProjectPaths

logging.basicConfig(level=logging.INFO)
settings = PortalSettings(headless=False).resolved_against(ProjectPaths.discover())
client = PortalClient(
    settings,
    PortalCredentials.from_env(),  # export SIVIN_USER=... SIVIN_PASSWORD=... first
    driver_factory_registry.create(settings),
)
result = PortalSession(client).run()
print(result.files, result.failures)
```

Requirements: `pip install -e ".[ingest]"`, a Chrome or Chromium, and a chromedriver of the same
major version (on `PATH`, in `chromedriver_path`, or downloaded by webdriver-manager).

## When the portal's HTML changes

Find the failing step in the log or in `SessionResult.failures`, then adjust the matching
setting in `config/sivin.yaml` (no code change needed):

| Symptom | Setting to check |
|---|---|
| `PortalLoginError: The login form was not found` | `selectors.username_id`, `selectors.password_id`, `selectors.submit_css`, `portal_url` |
| `PortalLoginError: No link 'SIVIN VUT' after login` | credentials first; then `folder_name`, `selectors.link_xpath_template` |
| `ViewModelError: ... has no 'viewModel.Scene...'` or `No section ... has a 'Devices' list` | the viewmodel structure changed: `selectors.viewmodel_id`, and the keys in `viewmodel.py` (code change) |
| `TimeoutException: No link for device '...'` | `selectors.link_xpath_template`; or the page after `back()` is not the device list |
| `TimeoutException: Tab 'Meteorologická data' is not clickable.` | `meteo_tab_name`, `selectors.tab_xpath_template` |
| `ExportButtonNotFoundError` | `selectors.excel_button_xpath`; the window size in `chrome_arguments` |
| `TimeoutException: Spinner #UpdateProgress is still visible.` | `selectors.spinner_id`, `timeouts.element_wait_s` |
| `DownloadTimeoutError` | `timeouts.download_wait_s`; Chrome's download preferences; free disk space |

## Troubleshooting

- **Watch it.** Run with `headless=False` to see the browser, and with `logging` at DEBUG for
  the client's own messages.
- **`session not created: This version of ChromeDriver only supports Chrome version N`** —
  chromedriver and the browser have different major versions. Point `chromedriver_path` to a
  matching driver, or remove the mismatched one from `PATH` so webdriver-manager fetches one.
- **Chrome crashes immediately in a container** — add `--no-sandbox` (and possibly
  `--disable-dev-shm-usage`) to `chrome_arguments`.
- **Downloads land elsewhere or a "Save as" dialog appears** — `download_dir` must be absolute
  (`resolved_against`); the factory refuses a relative one.
- **Every device after the first fails with "No link for device"** — the portal's back
  navigation does not return to the device list. The client recovers after each failure by
  reloading the portal; if that also fails, the log says "Returning to the device list failed".
- **Old exports in `download_dir`** do no harm: only files created after the click are taken.
  Downloaded files are not deleted by the client; the store (WP-1.4) decides what happens to
  them.
