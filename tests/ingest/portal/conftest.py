"""A fake portal and fake browser for the portal client tests (no real browser, no network).

``FakePortalDriver`` imitates the pages of the data provider's portal as the legacy
``chrome_driver.py`` and MIGRATION_PLAN §4 WP-1.3 describe them: login form, folder link,
device links, the meteorological tab with the *Historie meteorologických dat* section and the
Excel export buttons, and the DotVVM spinner. Everything here is synthetic; device names follow
the documented ``<device> <serial>`` pattern.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By

from sivin.ingest.portal.client import SELENIUM_WIRE_LOGGER, PortalClient
from sivin.ingest.portal.credentials import PortalCredentials, Secret
from sivin.ingest.portal.driver import WebDriverFactory
from sivin.ingest.portal.page import JS_CLICK, xpath_literal
from sivin.ingest.portal.settings import TEXT_PLACEHOLDER, PortalSettings, PortalTimeouts

FIXTURES = Path(__file__).parent / "data"

USERNAME = "synthetic-user"
PASSWORD = "synthetic-Secret-42"

DEVICE_NAMES = ("8615620 77678271", "8615621 77678272", "8615622 77678273")
"""Synthetic device names in the portal's documented spelling."""

Behaviour = str
"""What the fake portal does for a device:
``"ok"`` (writes ``MeteoData_<name> (VUT)_<stamp>.xlsx``), ``"partial"`` (only a ``.crdownload``
file), ``"late"`` (a ``.crdownload`` that is finished when the next export is clicked),
``"empty"`` (a zero-byte export), ``"unnamed"`` (an export without serial in its name),
``"none"`` (nothing), ``"no_button"`` (no visible Excel button), ``"no_section"`` (Excel button
outside the export section), ``"no_tab"`` (the tab link is missing), ``"flaky"`` (no button on the
first visit, ok afterwards)."""


class FakeClock:
    """Monotonic clock whose sleep only advances time and runs registered callbacks."""

    def __init__(self) -> None:
        self.now_s = 0.0
        self.sleeps: list[float] = []
        self.on_sleep: list[Callable[[float], None]] = []

    def monotonic(self) -> float:
        return self.now_s

    def sleep(self, duration_s: float) -> None:
        self.sleeps.append(duration_s)
        self.now_s += duration_s
        for callback in self.on_sleep:
            callback(self.now_s)


class FakeElement:
    """A web element with a fixed visibility and a click action."""

    def __init__(
        self,
        portal: FakePortalDriver,
        key: str,
        *,
        displayed: bool = True,
        value: str | None = None,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        self._portal = portal
        self.key = key
        self._displayed = displayed
        self._value = value
        self._on_click = on_click

    def send_keys(self, text: str) -> None:
        # Imitates selenium's RemoteConnection, which logs request bodies at DEBUG level.
        logging.getLogger(SELENIUM_WIRE_LOGGER).debug(
            "POST /session/1/element/%s/value {'text': %r}", self.key, text
        )
        self._portal.log.append(("send_keys", self.key))
        self._portal.typed[self.key] = text

    def click(self) -> None:
        self._portal.log.append(("click", self.key))
        if self._on_click is not None:
            self._on_click()

    def is_displayed(self) -> bool:
        if self.key == "spinner":
            return self._portal.spinner_visible()
        return self._displayed

    def is_enabled(self) -> bool:
        return True

    def get_attribute(self, name: str) -> str | None:
        return self._value if name == "value" else None


class FakePortalDriver:
    """A WebDriver look-alike that serves the fake portal's pages.

    Parameters
    ----------
    settings : PortalSettings
        Selectors and names the fake answers to.
    viewmodel_json : str
        Value of the hidden viewmodel input.
    behaviours : dict[str, Behaviour], optional
        Per device name; ``"ok"`` by default.
    tab_adds_history : bool
        Whether switching to the meteorological tab adds a browser history entry (then one
        ``back()`` returns to the device page, not to the list).
    """

    def __init__(
        self,
        settings: PortalSettings,
        viewmodel_json: str,
        behaviours: dict[str, Behaviour] | None = None,
        tab_adds_history: bool = False,
    ) -> None:
        self.settings = settings
        self.viewmodel_json = viewmodel_json
        self.behaviours = behaviours or {}
        self.tab_adds_history = tab_adds_history
        self.page = "blank"
        self.history: list[str] = []
        self.log: list[tuple[str, ...]] = []
        self.typed: dict[str, str] = {}
        self.quit_error: WebDriverException | None = None
        self.back_error: WebDriverException | None = None
        self.fail_get_after: int | None = None
        self.export_counter = 0
        self.logged_in = False
        self.spinner_polls_per_action = 2
        self.spinner_stuck = False
        self.spinner_checks = 0
        self._spinner_polls_left = 0
        self._late: list[Path] = []
        self._visits: dict[str, int] = {}

    def get(self, url: str) -> None:
        self.log.append(("get", url))
        if self.fail_get_after is not None:
            if self.fail_get_after == 0:
                raise WebDriverException("navigation failed")
            self.fail_get_after -= 1
        if url != self.settings.portal_url:
            self._go("unknown")
        else:
            self._go("dashboard" if self.logged_in else "login")

    def back(self) -> None:
        self.log.append(("back",))
        if self.back_error is not None:
            raise self.back_error
        self.page = self.history.pop() if self.history else "blank"

    def quit(self) -> None:
        self.log.append(("quit",))
        if self.quit_error is not None:
            raise self.quit_error

    def execute_script(self, script: str, *args: Any) -> None:
        if script == JS_CLICK:
            args[0].click()
        else:
            self.log.append(("script", args[0].key))

    def find_element(self, by: str, value: str) -> FakeElement:
        elements = self.find_elements(by, value)
        if not elements:
            raise NoSuchElementException(f"{by}={value} not on page {self.page}")
        return elements[0]

    def find_elements(self, by: str, value: str) -> list[FakeElement]:
        if (by, value) == (By.ID, self.settings.selectors.spinner_id) and self.page != "login":
            return [FakeElement(self, "spinner")]
        return self._elements().get((by, value), [])

    def spinner_visible(self) -> bool:
        """The spinner shows for a few polls after every action (or forever when stuck)."""
        self.spinner_checks += 1
        if self.spinner_stuck:
            return True
        if self._spinner_polls_left > 0:
            self._spinner_polls_left -= 1
            return True
        return False

    def _go(self, page: str) -> None:
        self.history.append(self.page)
        self.page = page
        self._spinner_polls_left = self.spinner_polls_per_action

    def _locator(self, template: str, text: str) -> tuple[str, str]:
        return By.XPATH, template.replace(TEXT_PLACEHOLDER, xpath_literal(text))

    def _elements(self) -> dict[tuple[str, str], list[FakeElement]]:
        selectors = self.settings.selectors
        folder = self._locator(selectors.link_xpath_template, self.settings.folder_name)
        if self.page == "login":
            return {
                (By.ID, selectors.username_id): [FakeElement(self, "username")],
                (By.ID, selectors.password_id): [FakeElement(self, "password")],
                (By.CSS_SELECTOR, selectors.submit_css): [
                    FakeElement(self, "submit", on_click=self._submit)
                ],
            }
        if self.page == "dashboard":
            return {folder: [FakeElement(self, "folder", on_click=lambda: self._go("folder"))]}
        if self.page == "folder":
            elements = {
                folder: [FakeElement(self, "folder", on_click=lambda: self._go("folder"))],
                (By.ID, selectors.viewmodel_id): [
                    FakeElement(self, "viewmodel", displayed=False, value=self.viewmodel_json)
                ],
            }
            for name in DEVICE_NAMES:
                elements[self._locator(selectors.link_xpath_template, name)] = [
                    FakeElement(self, f"device:{name}", on_click=self._opener(name))
                ]
            return elements
        if self.page.startswith("device:"):
            return self._device_page(self.page.removeprefix("device:"))
        if self.page.startswith("meteo:"):
            return self._meteo_page(self.page.removeprefix("meteo:"))
        return {}

    def _device_page(self, name: str) -> dict[tuple[str, str], list[FakeElement]]:
        # The default tab of a device has a visible Excel button too (other data); it must
        # never be clicked.
        selectors = self.settings.selectors
        elements = {
            (By.XPATH, selectors.excel_button_xpath): [FakeElement(self, "excel:default-tab")]
        }
        if self.behaviours.get(name) != "no_tab":
            tab = self._locator(selectors.tab_xpath_template, self.settings.meteo_tab_name)
            elements[tab] = [FakeElement(self, "meteo_tab", on_click=self._switch_tab(name))]
        return elements

    def _meteo_page(self, name: str) -> dict[tuple[str, str], list[FakeElement]]:
        behaviour = self.behaviours.get(name, "ok")
        if behaviour == "flaky" and self._visits[name] == 1:
            behaviour = "no_button"
        hidden = FakeElement(self, "excel:hidden", displayed=False)
        button = FakeElement(self, f"excel:{name}", on_click=lambda: self._export(name, behaviour))
        section = self._locator(
            self.settings.selectors.section_button_xpath_template,
            self.settings.export_section_name,
        )
        anywhere = (By.XPATH, self.settings.selectors.excel_button_xpath)
        if behaviour == "no_button":
            return {anywhere: [hidden]}
        if behaviour == "no_section":
            return {anywhere: [hidden, button]}
        return {section: [hidden, button], anywhere: [hidden, button]}

    def _opener(self, name: str) -> Callable[[], None]:
        def open_device() -> None:
            self._visits[name] = self._visits.get(name, 0) + 1
            self._go(f"device:{name}")

        return open_device

    def _switch_tab(self, name: str) -> Callable[[], None]:
        def switch() -> None:
            if self.tab_adds_history:
                self._go(f"meteo:{name}")
            else:
                self.page = f"meteo:{name}"
                self._spinner_polls_left = self.spinner_polls_per_action

        return switch

    def _submit(self) -> None:
        if self.typed.get("username") == USERNAME and self.typed.get("password") == PASSWORD:
            self.logged_in = True
            self._go("dashboard")

    def _export(self, name: str, behaviour: Behaviour) -> None:
        for partial in self._late:
            partial.rename(partial.with_name(partial.name.removesuffix(".crdownload")))
        self._late.clear()
        self.export_counter += 1
        stem = f"MeteoData_{name} (VUT)_20260301_22385{self.export_counter}"
        target = self.settings.download_dir
        if behaviour in {"ok", "flaky", "no_section"}:
            (target / f"{stem}.xlsx").write_bytes(b"synthetic export " + name.encode())
        elif behaviour == "unnamed":
            (target / f"export_{self.export_counter}.xlsx").write_bytes(b"synthetic export")
        elif behaviour == "empty":
            (target / f"{stem}.xlsx").write_bytes(b"")
        elif behaviour in {"partial", "late"}:
            partial = target / f"{stem}.xlsx.crdownload"
            partial.write_bytes(b"partial")
            if behaviour == "late":
                self._late.append(partial)


class FakeDriverFactory(WebDriverFactory):
    """Returns a prepared fake driver; not registered."""

    name = "fake"

    def __init__(self, settings: PortalSettings, driver: Any) -> None:
        super().__init__(settings)
        self.driver = driver

    def create(self) -> Any:
        return self.driver


@pytest.fixture
def viewmodel_json() -> str:
    """The synthetic viewmodel sample (three devices in ``Sections[0]``)."""
    return (FIXTURES / "viewmodel_sample.json").read_text(encoding="utf-8")


@pytest.fixture
def settings(tmp_path: Path) -> PortalSettings:
    """Settings with short waits and an absolute download directory."""
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    return PortalSettings(
        download_dir=download_dir,
        timeouts=PortalTimeouts(
            element_wait_s=0.2,
            download_wait_s=3.0,
            poll_interval_s=0.01,
            device_settle_s=0.5,
            tab_settle_s=0.25,
            list_check_s=0.05,
        ),
    )


@pytest.fixture
def credentials() -> PortalCredentials:
    """Synthetic credentials accepted by the fake portal."""
    return PortalCredentials(USERNAME, Secret(PASSWORD))


@pytest.fixture
def fake_clock() -> FakeClock:
    """A clock that never really sleeps."""
    return FakeClock()


@pytest.fixture
def factory_for() -> Callable[[PortalSettings, Any], WebDriverFactory]:
    """Build a WebDriverFactory that returns a given (fake) driver."""
    return FakeDriverFactory


ClientBuilder = Callable[..., tuple[PortalClient, FakePortalDriver]]


@pytest.fixture
def make_client(
    settings: PortalSettings,
    credentials: PortalCredentials,
    viewmodel_json: str,
    fake_clock: FakeClock,
) -> ClientBuilder:
    """Build a client on a fake portal.

    Keywords: ``behaviours`` (device name → behaviour), ``login`` (other credentials),
    ``tab_adds_history``, ``settings_override`` (other settings).
    """

    def build(
        behaviours: dict[str, Behaviour] | None = None,
        login: PortalCredentials | None = None,
        tab_adds_history: bool = False,
        settings_override: PortalSettings | None = None,
    ) -> tuple[PortalClient, FakePortalDriver]:
        used = settings_override or settings
        driver = FakePortalDriver(used, viewmodel_json, behaviours, tab_adds_history)
        client = PortalClient(
            used, login or credentials, FakeDriverFactory(used, driver), clock=fake_clock
        )
        return client, driver

    return build
