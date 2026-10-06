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
| `PortalCredentials`, `Secret` | `credentials.py` | User name and password, read **only** from the environment (`from_env()`). The password is a `Secret`: masked in `repr`/`str`/`asdict`, not picklable. |
| `WebDriverFactory`, `ChromeDriverFactory`, `driver_factory_registry` | `driver.py` | Start the browser with download preferences. New browsers are new registered subclasses. |
| `PortalClient` | `client.py` | Context manager owning one browser: `login()`, `list_devices()`, `download_export(device)`, `back_to_device_list()`, `return_to_folder()`. Single-threaded use only. |
| `PortalPage` | `page.py` | Locators, explicit waits and clicks on the portal's pages (used by the client). |
| `ViewModelParser` | `viewmodel.py` | Pure parser of the DotVVM viewmodel JSON into `PortalDevice` objects. |
| `DownloadWatcher` | `watcher.py` | Detects the file a click produced: a *new*, non-empty, size-stable file that is not a late file of an earlier download and not another sensor's export. |
| `DownloadDiagnostics`, `DownloadReport` | `diagnostics.py` | After a failed download: what the download directories, the browser and the portal's notices show, logged as one WARNING block (see [When a download fails](#when-a-download-fails)). |
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
      pause `device_settle_s` (3 s, the legacy value), wait for the spinner;
   2. click the tab containing `Meteorologická data`, wait for the spinner, pause
      `tab_settle_s` (2 s, the legacy value);
   3. wait for a visible Excel button (`button` with an `i.mdi-file-excel` icon) **inside the
      section headed `export_section_name`** (*Historie meteorologických dat*,
      `selectors.section_button_xpath_template`). That the button is visible also shows that the
      meteorological tab is really active (other tabs have Excel buttons too). If no such button
      appears, the first visible Excel button anywhere is used and a WARNING is logged (the
      legacy rule) — then check the section settings;
   4. take a snapshot of the download directory, scroll the button into view and click it;
   5. wait until the new complete file appears (see below) and return its path; a name without
      any sensor serial is accepted with a WARNING;
   6. go back to the device list (`back_to_device_list()`): `driver.back()` as in the legacy
      script, then wait up to `list_check_s` for the device list (the link of the first listed
      device). If it is not there — e.g. because the tab switch added a history entry — the
      portal is reloaded and the folder opened again. A failure here is logged; the download is
      kept.
5. **A failing device** (any Selenium exception, a missing button, a download timeout or an
   incomplete file, a file system error) is retried after the client has reloaded `portal_url`
   and opened the folder again (`return_to_folder()`), up to `attempts_per_device` attempts
   (default 2). Then it is recorded as `DeviceFailure(device, reason)` (the first error, and the
   last one if it differed) and the run continues with the next device. If the reload fails
   too, it is logged and the next devices fail on their own.
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
- a file whose name is the finished name of a download that was still unfinished at the
  snapshot (`A.xlsx` for `A.xlsx.crdownload`) is never accepted: it is the late end of an
  earlier, timed-out download. Files left in the directory by a timed-out wait are also
  remembered and ignored by later waits;
- when the name contains a sensor serial (the legacy log shows names like
  `MeteoData_8615620 77678271.xlsx`), it must be the serial of the device being downloaded;
  another sensor's export is skipped with a WARNING. This also catches late downloads whose
  partial name gave no hint (Chrome sometimes writes `Unconfirmed 123.crdownload`);
- a candidate is accepted when its size is the same in two consecutive polls and at least
  `min_export_size_bytes` (an empty file is never an export);
- after `download_wait_s` it raises `DownloadIncompleteError` if only too small files appeared,
  otherwise `DownloadTimeoutError`. A file first seen exactly at the deadline gets one more poll
  to be confirmed.

When the browser saves a second export of the same day, it appends ` (1)` to the name; that is a
new name and therefore detected. `SensorId.parse` understands these names.

Only explicit waits (`WebDriverWait` with expected conditions) are used. The fixed pauses are
`timeouts.device_settle_s` and `timeouts.tab_settle_s`, kept at the legacy 3 s and 2 s because
DotVVM may still re-render after the spinner has gone (the spinner may also not have appeared
yet when it is first checked). They are **to be tuned** on the first real run; with the
section-scoped button wait they can probably be shortened.

## Settings

Proposed configuration section: `ingest.portal` in `config/sivin.yaml` (wired into
`SivinConfig` by the integration workpackage). All fields have defaults equal to the legacy
values.

| Key | Default | Unit | Meaning |
|---|---|---|---|
| `portal_url` | `https://lemon.e-service.cz/` | URL | Start page (redirects to the login). |
| `folder_name` | `SIVIN VUT` | text | Folder link that lists our devices. |
| `meteo_tab_name` | `Meteorologická data` | text | Device tab with the export. |
| `export_section_name` | `Historie meteorologických dat` | text | Heading of the section whose Excel button is clicked. |
| `attempts_per_device` | 2 | count | Attempts per device before it is recorded as failed. |
| `min_export_size_bytes` | 1 | B | Smaller files are incomplete downloads. |
| `selectors.username_id` | `username` | HTML id | User name input. |
| `selectors.password_id` | `password` | HTML id | Password input. |
| `selectors.submit_css` | `input[type='submit']` | CSS | Login button. |
| `selectors.spinner_id` | `UpdateProgress` | HTML id | DotVVM progress spinner. |
| `selectors.viewmodel_id` | `__dot_viewmodel_root` | HTML id | Hidden input with the viewmodel JSON. |
| `selectors.link_xpath_template` | `//a[contains(., {text})]` | XPath | Folder and device links; `{text}` becomes a quoted literal. |
| `selectors.tab_xpath_template` | `//a[contains(text(), {text})]` | XPath | Tab link. |
| `selectors.excel_button_xpath` | `//button[.//i[contains(@class, 'mdi-file-excel')]]` | XPath | All Excel export buttons; the first visible one is only the fallback. |
| `selectors.notification_css` | `[role='alert'], [role='status'], .alert, .toast, .notification` | CSS | Visible error/notification messages whose text is logged when a download fails; generic, not taken from the portal's HTML ([to be verified]). Empty disables the search. |
| `selectors.section_button_xpath_template` | heading containing `{text}` → nearest ancestor with an Excel button → its Excel buttons | XPath | Excel button of the export section ([to be verified] against the real HTML). |
| `timeouts.element_wait_s` | 15 | s | Maximum wait for an element or the spinner. |
| `timeouts.download_wait_s` | 30 | s | Maximum wait for the export file. |
| `timeouts.poll_interval_s` | 0.5 | s | Polling interval of waits and of the download watcher. |
| `timeouts.device_settle_s` | 3.0 | s | Fixed pause after opening a device (legacy value, [to be tuned]). |
| `timeouts.tab_settle_s` | 2.0 | s | Fixed pause after switching to the tab (legacy value, [to be tuned]). |
| `timeouts.list_check_s` | 5.0 | s | Wait for the device list after `back()` before reloading. |
| `headless` | `true` | flag | Run without a window. Set `false` to watch the browser locally. |
| `browser` | `chrome` | name | Registered `WebDriverFactory`. |
| `download_dir` | `data/downloads` | path | Relative to the project root (ignored by git via `/data/`); the caller resolves it with `PortalSettings.resolved_against(ProjectPaths)`. |
| `chrome_binary` | unset | path | Browser executable; falls back to `$CHROME_BINARY`, then to the browser chromedriver finds. |
| `chromedriver_path` | unset | path | chromedriver; falls back to `$CHROMEWEBDRIVER/chromedriver` (GitHub-hosted runners), then `chromedriver` on `PATH`, then webdriver-manager (downloads a matching driver, needs internet). |
| `chrome_arguments` | `["--window-size=1920,1080"]` | flags | Extra Chrome arguments; add `--no-sandbox` only when running as root in a container. |
| `partial_download_suffixes` | `[".crdownload", ".tmp"]` | suffixes | Unfinished downloads. |
| `ignored_download_prefixes` | `["."]` | prefixes | Hidden temporary files. |

### Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `SIVIN_USER` | yes | Portal user name. |
| `SIVIN_PASSWORD` | yes | Portal password. |
| `CHROME_BINARY` | no | Chrome/Chromium executable when `chrome_binary` is not set. |
| `CHROMEWEBDRIVER` | no | Directory with chromedriver (set by GitHub-hosted runner images). |

Credentials come **only** from the environment: locally from `.env` (git-ignored), in GitHub
Actions from repository secrets. They are never written to the configuration, never logged and
masked in `repr`. While they are typed, Selenium's request logger
(`selenium.webdriver.remote.remote_connection`, which logs request bodies at DEBUG level) is
raised to WARNING, so a DEBUG run does not leak them either. That level is process-global;
a lock serialises the change between threads, but the client as a whole is meant for
**single-threaded use** (one client at a time, as the CLI and the workflow run it).

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
| `TimeoutException: No link for device '...'` | `selectors.link_xpath_template`; if every device fails like this, also `selectors.viewmodel_id` / the folder page |
| WARNING `No Excel button in section ...` | `export_section_name`, `selectors.section_button_xpath_template` |
| `DownloadIncompleteError` | the portal produced an empty file; `min_export_size_bytes` |
| WARNING `Skipping ...: it is the export of ...` | a late download of another sensor was seen and ignored; check `download_wait_s` |
| `TimeoutException: Tab 'Meteorologická data' is not clickable.` | `meteo_tab_name`, `selectors.tab_xpath_template` |
| `ExportButtonNotFoundError` | `selectors.excel_button_xpath`, `selectors.section_button_xpath_template`; the window size in `chrome_arguments` |
| `TimeoutException: Spinner #UpdateProgress is still visible.` | `selectors.spinner_id`, `timeouts.element_wait_s` |
| `DownloadTimeoutError` | read the diagnostics block first ([When a download fails](#when-a-download-fails)); then `timeouts.download_wait_s`, Chrome's download preferences, free disk space |

## When a download fails

When the export button was pressed but no file was accepted (`DownloadTimeoutError` or
`DownloadIncompleteError`), the client logs **one WARNING block** right before the error goes
on to `PortalSession` (which retries and records the device exactly as before):

```text
WARNING Export of 8615620 77678271 failed (DownloadTimeoutError); diagnostics:
  download dir /…/data/downloads: 1 entry: MeteoData_8615620 77678271 (VUT)_20260301_223851.xlsx.crdownload (7 B, unfinished)
  Chrome default dir /home/runner/Downloads: absent
  browser: title …; url https://lemon.e-service.cz/…; readyState complete; windows 1
  portal notices: none visible
```

(Synthetic example from the tests, not a real run.)

| Line | What it shows |
|---|---|
| `download dir` | Every entry of `download_dir`, newest first, with its size in bytes, also the ones the watcher does not take: `unfinished` (a `partial_download_suffixes` ending, e.g. `.crdownload`) and `ignored` (an `ignored_download_prefixes` beginning, e.g. Chrome's hidden `.com.google.Chrome.*`). At most 10 entries, then `… and N more`; `empty` or `absent` otherwise. |
| `Chrome default dir` | `~/Downloads` of the user running the browser, listed only when it exists and differs from `download_dir`; `absent` otherwise. |
| `browser` | Page title, the current URL **without** user info, query string and fragment (they may carry tokens), `document.readyState` and the number of open windows/tabs. |
| `portal notices` | Texts of visible elements matching `selectors.notification_css` (at most 3, each cut to 200 characters), `none visible`, or `not searched` when the selector is empty. |

Any item that cannot be read says `unavailable (<ExceptionName>)`; collecting never replaces
the download error. Credentials, cookies, page source and input values are never logged.

**Reading it — provider or our side?**

- **Provider side (likely):** `download dir` is `empty` (or holds only older exports), the default
  directory is `absent` or unchanged, the browser is still on the device page with
  `readyState complete` and one window, and possibly a portal notice. The button was pressed,
  and the portal produced no file. Confirm by exporting by hand in a normal browser; if that
  fails too, it is the provider.
- **Download still running or slow:** an `unfinished` file in `download dir`, growing between
  retries — raise `timeouts.download_wait_s`, check disk space.
- **Our side, download preferences ignored:** the new export is in `Chrome default dir`, not in
  `download dir` — check `ChromeDriverFactory.download_preferences` and `download_dir`.
- **Our side, export opened a tab:** `windows 2` or more, or the URL is no longer the portal page
  — the export was opened instead of downloaded.
- **Empty export:** a complete file of `0 B` (with `DownloadIncompleteError`) — the portal
  produced an empty file; usually the provider.
- **`url` shows the login page:** the portal session ended before the export; the client does
  not log in again, so the remaining devices of the run are likely to fail as well.

The notification selector is generic (ARIA `alert`/`status` roles and common toast classes) and
has not been checked against the portal's HTML; `none visible` therefore does not prove that
the portal showed no message. Set `selectors.notification_css` once the real message element is
known.

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
- **INFO "back() did not return to the device list; reloading the portal" for every device** —
  the portal's history differs from the legacy assumption; this costs one reload per device but
  works. If devices still fail with "No link for device" after the reload, the log also says
  "Returning to the device list failed" and the folder/device-link selectors need checking.
- **Old exports in `download_dir`** do no harm: only files created after the click are taken.
  Downloaded files are not deleted by the client; the store (WP-1.4) decides what happens to
  them.
