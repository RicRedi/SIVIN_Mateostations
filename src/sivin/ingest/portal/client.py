"""The portal client: login, device list and one Excel export per device.

The portal (``lemon.e-service.cz``) is a DotVVM application without an API, so the client
drives a browser through the same steps a person would (MIGRATION_PLAN §2.1). Every wait is an
explicit Selenium wait for a condition; the only fixed pause is the named
``timeouts.settle_delay_s``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Final, Self, cast

from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

from sivin.ingest.portal.clock import Clock, SystemClock
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.portal.driver import WebDriverFactory
from sivin.ingest.portal.errors import ExportButtonNotFoundError, PortalLoginError, ViewModelError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.settings import TEXT_PLACEHOLDER, PortalSettings
from sivin.ingest.portal.viewmodel import ViewModelParser
from sivin.ingest.portal.watcher import DownloadWatcher

logger = logging.getLogger(__name__)

SELENIUM_WIRE_LOGGER: Final = "selenium.webdriver.remote.remote_connection"
"""Selenium logger that writes request bodies (including typed text) at DEBUG level."""

JS_CLICK: Final = "arguments[0].click();"
"""Click through JavaScript, as the legacy script did (works for covered elements too)."""

JS_SCROLL_INTO_VIEW: Final = "arguments[0].scrollIntoView({block: 'center'});"

Locator = tuple[str, str]


def xpath_literal(text: str) -> str:
    """Quote ``text`` as an XPath 1.0 string literal.

    Parameters
    ----------
    text : str
        Any text, possibly containing both quote characters.

    Returns
    -------
    str
        ``'text'``, ``"text"`` or a ``concat(...)`` expression.
    """
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in text.split("'")) + ")"


@contextmanager
def _secret_input_logging() -> Iterator[None]:
    """Silence Selenium's request logging while credentials are typed."""
    wire_logger = logging.getLogger(SELENIUM_WIRE_LOGGER)
    previous_level = wire_logger.level
    if wire_logger.getEffectiveLevel() < logging.WARNING:
        wire_logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        wire_logger.setLevel(previous_level)


class PortalClient:
    """A browser session on the data provider's portal; use as a context manager.

    Parameters
    ----------
    settings : PortalSettings
        Settings; ``download_dir`` must be absolute (see ``PortalSettings.resolved_against``).
    credentials : PortalCredentials
        Login; never logged.
    driver_factory : WebDriverFactory
        Starts the browser on ``__enter__`` (tests pass a factory of a fake driver).
    parser : ViewModelParser, optional
        Viewmodel parser.
    clock : Clock, optional
        Time source for the settle pause and the download watcher.
    watcher : DownloadWatcher, optional
        Download detection; built from the settings when omitted.

    Raises
    ------
    ValueError
        If ``settings.download_dir`` is not absolute.
    """

    def __init__(
        self,
        settings: PortalSettings,
        credentials: PortalCredentials,
        driver_factory: WebDriverFactory,
        parser: ViewModelParser | None = None,
        clock: Clock | None = None,
        watcher: DownloadWatcher | None = None,
    ) -> None:
        if not settings.download_dir.is_absolute():
            raise ValueError(
                f"download_dir must be absolute, got {settings.download_dir}; "
                "resolve it with PortalSettings.resolved_against first."
            )
        self._settings = settings
        self._selectors = settings.selectors
        self._credentials = credentials
        self._driver_factory = driver_factory
        self._parser = parser or ViewModelParser()
        self._clock = clock or SystemClock()
        self._watcher = watcher or DownloadWatcher(
            settings.download_dir,
            timeout_s=settings.timeouts.download_wait_s,
            poll_interval_s=settings.timeouts.poll_interval_s,
            clock=self._clock,
            partial_suffixes=settings.partial_download_suffixes,
            ignored_prefixes=settings.ignored_download_prefixes,
        )
        self._web_driver: WebDriver | None = None

    def __enter__(self) -> Self:
        self._web_driver = self._driver_factory.create()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        driver, self._web_driver = self._web_driver, None
        if driver is None:
            return
        try:
            driver.quit()
        except WebDriverException as error:
            logger.warning("Closing the browser failed: %s", error.msg)

    def login(self) -> None:
        """Open the portal, submit the login form and wait for the folder link.

        Raises
        ------
        PortalLoginError
            If the login form does not appear, or the folder link does not appear after
            submitting (wrong credentials or a changed page).
        """
        driver = self._driver
        driver.get(self._settings.portal_url)
        try:
            username_field = self._wait().until(
                ec.presence_of_element_located((By.ID, self._selectors.username_id))
            )
            with _secret_input_logging():
                username_field.send_keys(self._credentials.username)
                driver.find_element(By.ID, self._selectors.password_id).send_keys(
                    self._credentials.password
                )
            driver.find_element(By.CSS_SELECTOR, self._selectors.submit_css).click()
        except (TimeoutException, NoSuchElementException) as error:
            raise PortalLoginError(
                "The login form was not found; check selectors.username_id, password_id and "
                "submit_css."
            ) from error
        try:
            self._wait().until(ec.presence_of_element_located(self._folder_locator()))
        except TimeoutException as error:
            raise PortalLoginError(
                f"No link {self._settings.folder_name!r} after login: wrong credentials, or "
                "the page changed."
            ) from error
        logger.info("Logged in to %s.", self._settings.portal_url)

    def list_devices(self) -> list[PortalDevice]:
        """Open the folder and read its devices from the DotVVM viewmodel.

        Returns
        -------
        list[PortalDevice]
            Devices in portal order.

        Raises
        ------
        ViewModelError
            If the viewmodel input is empty or its structure is unexpected.
        """
        self.open_folder()
        element = self._wait().until(
            ec.presence_of_element_located((By.ID, self._selectors.viewmodel_id)),
            f"No viewmodel input #{self._selectors.viewmodel_id}.",
        )
        raw_json = element.get_attribute("value")
        if not raw_json:
            raise ViewModelError(f"The input #{self._selectors.viewmodel_id} has no value.")
        devices = self._parser.parse(raw_json)
        logger.info("Portal lists %d device(s): %s", len(devices), [str(d) for d in devices])
        return devices

    def open_folder(self) -> None:
        """Click the folder link and wait until the page is idle."""
        folder = self._wait().until(
            ec.element_to_be_clickable(self._folder_locator()),
            f"Folder link {self._settings.folder_name!r} is not clickable.",
        )
        self._click(folder)
        self._wait_until_idle()

    def return_to_folder(self) -> None:
        """Reload the portal and open the folder; used to recover after a failed device."""
        self._driver.get(self._settings.portal_url)
        self.open_folder()

    def download_export(self, device: PortalDevice) -> Path:
        """Download the Excel export of one device and go back to the device list.

        Parameters
        ----------
        device : PortalDevice
            A device from :meth:`list_devices`.

        Returns
        -------
        pathlib.Path
            The new file in the download directory.

        Raises
        ------
        ExportButtonNotFoundError
            If no visible Excel button appears on the meteorological tab.
        DownloadTimeoutError
            If no new complete file appears in time.
        selenium.common.exceptions.WebDriverException
            If an element does not appear in time or the browser fails.
        """
        self._wait_until_idle()
        self._click(
            self._wait().until(
                ec.presence_of_element_located(self._link(device.name)),
                f"No link for device {device.name!r}.",
            )
        )
        self._settle()
        self._wait_until_idle()
        self._click(
            self._wait().until(
                ec.element_to_be_clickable(self._tab_locator()),
                f"Tab {self._settings.meteo_tab_name!r} is not clickable.",
            )
        )
        self._wait_until_idle()
        self._settle()
        button = self._visible_export_button(device)
        before = self._watcher.snapshot()
        self._driver.execute_script(JS_SCROLL_INTO_VIEW, button)
        self._click(button)
        path = self._watcher.wait_for_new_file(before)
        logger.info("Downloaded the export of %s: %s", device, path.name)
        self._driver.back()
        return path

    @property
    def _driver(self) -> WebDriver:
        if self._web_driver is None:
            raise RuntimeError("PortalClient is not open; use it in a 'with' block.")
        return self._web_driver

    def _wait(self) -> WebDriverWait[WebDriver]:
        timeouts = self._settings.timeouts
        return WebDriverWait(
            self._driver, timeouts.element_wait_s, poll_frequency=timeouts.poll_interval_s
        )

    def _wait_until_idle(self) -> None:
        self._wait().until(
            ec.invisibility_of_element_located((By.ID, self._selectors.spinner_id)),
            f"Spinner #{self._selectors.spinner_id} is still visible.",
        )

    def _settle(self) -> None:
        if self._settings.timeouts.settle_delay_s > 0:
            self._clock.sleep(self._settings.timeouts.settle_delay_s)

    def _click(self, element: WebElement) -> None:
        self._driver.execute_script(JS_CLICK, element)

    def _visible_export_button(self, device: PortalDevice) -> WebElement:
        def first_visible(driver: WebDriver) -> WebElement | bool:
            buttons = driver.find_elements(By.XPATH, self._selectors.excel_button_xpath)
            return next((button for button in buttons if button.is_displayed()), False)

        try:
            found = self._wait().until(first_visible)
        except TimeoutException as error:
            raise ExportButtonNotFoundError(
                f"No visible Excel button for {device}; check selectors.excel_button_xpath."
            ) from error
        return cast(WebElement, found)

    def _link(self, text: str) -> Locator:
        return By.XPATH, self._selectors.link_xpath_template.replace(
            TEXT_PLACEHOLDER, xpath_literal(text)
        )

    def _folder_locator(self) -> Locator:
        return self._link(self._settings.folder_name)

    def _tab_locator(self) -> Locator:
        return By.XPATH, self._selectors.tab_xpath_template.replace(
            TEXT_PLACEHOLDER, xpath_literal(self._settings.meteo_tab_name)
        )
