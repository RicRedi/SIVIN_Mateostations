"""A fake portal and fake browser for the portal client tests (no real browser, no network).

``FakePortalDriver`` imitates the pages of the data provider's portal as the legacy
``chrome_driver.py`` and MIGRATION_PLAN §4 WP-1.3 describe them: login form, folder link,
device links, the meteorological tab and the Excel export buttons. Everything here is
synthetic; device names follow the documented ``<device> <serial>`` pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By

from sivin.ingest.portal.client import JS_CLICK, PortalClient, xpath_literal
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.portal.driver import WebDriverFactory
from sivin.ingest.portal.settings import TEXT_PLACEHOLDER, PortalSettings, PortalTimeouts

FIXTURES = Path(__file__).parent / "data"

USERNAME = "synthetic-user"
PASSWORD = "synthetic-Secret-42"

DEVICE_NAMES = ("8615620 77678271", "8615621 77678272", "8615622 77678273")
"""Synthetic device names in the portal's documented spelling."""

Behaviour = str
"""What the fake portal does when a device's Excel button is clicked:
``"ok"`` (writes the export), ``"partial"`` (only a ``.crdownload`` file), ``"none"`` (nothing),
``"no_button"`` (no visible export button), ``"no_tab"`` (the tab link is missing)."""


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
        self._portal.log.append(("send_keys", self.key))
        self._portal.typed[self.key] = text

    def click(self) -> None:
        self._portal.log.append(("click", self.key))
        if self._on_click is not None:
            self._on_click()

    def is_displayed(self) -> bool:
        return self._displayed

    def is_enabled(self) -> bool:
        return True

    def get_attribute(self, name: str) -> str | None:
        return self._value if name == "value" else None


class FakePortalDriver:
    """A WebDriver look-alike that serves the fake portal's pages."""

    def __init__(
        self,
        settings: PortalSettings,
        viewmodel_json: str,
        behaviours: dict[str, Behaviour] | None = None,
    ) -> None:
        self.settings = settings
        self.viewmodel_json = viewmodel_json
        self.behaviours = behaviours or {}
        self.page = "blank"
        self.history: list[str] = []
        self.log: list[tuple[str, ...]] = []
        self.typed: dict[str, str] = {}
        self.quit_error: WebDriverException | None = None
        self.fail_get_after: int | None = None
        self.export_counter = 0
        self.logged_in = False

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
        return self._elements().get((by, value), [])

    def _go(self, page: str) -> None:
        self.history.append(self.page)
        self.page = page

    def _link(self, text: str) -> tuple[str, str]:
        template = self.settings.selectors.link_xpath_template
        return By.XPATH, template.replace(TEXT_PLACEHOLDER, xpath_literal(text))

    def _elements(self) -> dict[tuple[str, str], list[FakeElement]]:
        selectors = self.settings.selectors
        folder = self._link(self.settings.folder_name)
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
                elements[self._link(name)] = [
                    FakeElement(self, f"device:{name}", on_click=self._opener(f"device:{name}"))
                ]
            return elements
        if self.page.startswith("device:"):
            return self._device_page(self.page.removeprefix("device:"))
        if self.page.startswith("meteo:"):
            return self._meteo_page(self.page.removeprefix("meteo:"))
        return {}

    def _device_page(self, name: str) -> dict[tuple[str, str], list[FakeElement]]:
        if self.behaviours.get(name) == "no_tab":
            return {}
        template = self.settings.selectors.tab_xpath_template
        tab = (
            By.XPATH,
            template.replace(TEXT_PLACEHOLDER, xpath_literal(self.settings.meteo_tab_name)),
        )
        return {tab: [FakeElement(self, "meteo_tab", on_click=self._switch_tab(f"meteo:{name}"))]}

    def _meteo_page(self, name: str) -> dict[tuple[str, str], list[FakeElement]]:
        behaviour = self.behaviours.get(name, "ok")
        hidden = FakeElement(self, "excel:hidden", displayed=False)
        buttons = [hidden]
        if behaviour != "no_button":
            buttons.append(
                FakeElement(self, f"excel:{name}", on_click=lambda: self._export(name, behaviour))
            )
        return {(By.XPATH, self.settings.selectors.excel_button_xpath): buttons}

    def _opener(self, page: str) -> Callable[[], None]:
        return lambda: self._go(page)

    def _switch_tab(self, page: str) -> Callable[[], None]:
        """Tabs switch in place (no history entry), so one back() leaves the device."""

        def switch() -> None:
            self.page = page

        return switch

    def _submit(self) -> None:
        if self.typed.get("username") == USERNAME and self.typed.get("password") == PASSWORD:
            self.logged_in = True
            self._go("dashboard")

    def _export(self, name: str, behaviour: Behaviour) -> None:
        self.export_counter += 1
        stem = f"MeteoData_{name} (VUT)_20260301_22385{self.export_counter}"
        target = self.settings.download_dir
        if behaviour == "ok":
            (target / f"{stem}.xlsx").write_bytes(b"synthetic export " + name.encode())
        elif behaviour == "partial":
            (target / f"{stem}.xlsx.crdownload").write_bytes(b"partial")


class FakeDriverFactory(WebDriverFactory):
    """Returns a prepared fake driver; not registered."""

    name = "fake"

    def __init__(self, settings: PortalSettings, driver: FakePortalDriver) -> None:
        super().__init__(settings)
        self.driver = driver
        self.created = 0

    def create(self) -> Any:
        self.created += 1
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
            element_wait_s=0.2, download_wait_s=3.0, poll_interval_s=0.01, settle_delay_s=0.5
        ),
    )


@pytest.fixture
def credentials() -> PortalCredentials:
    """Synthetic credentials accepted by the fake portal."""
    return PortalCredentials(USERNAME, PASSWORD)


@pytest.fixture
def fake_clock() -> FakeClock:
    """A clock that never really sleeps."""
    return FakeClock()


ClientBuilder = Callable[..., tuple[PortalClient, FakePortalDriver]]


@pytest.fixture
def make_client(
    settings: PortalSettings,
    credentials: PortalCredentials,
    viewmodel_json: str,
    fake_clock: FakeClock,
) -> ClientBuilder:
    """Build a client on a fake portal; keyword ``behaviours`` maps device name to behaviour."""

    def build(
        behaviours: dict[str, Behaviour] | None = None,
        login: PortalCredentials | None = None,
        viewmodel: str | None = None,
    ) -> tuple[PortalClient, FakePortalDriver]:
        driver = FakePortalDriver(settings, viewmodel or viewmodel_json, behaviours)
        client = PortalClient(
            settings,
            login or credentials,
            FakeDriverFactory(settings, driver),
            clock=fake_clock,
        )
        return client, driver

    return build
