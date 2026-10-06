"""The portal client: login, device list and one Excel export per device.

The portal (``lemon.e-service.cz``) is a DotVVM application without an API, so the client
drives a browser through the same steps a person would (MIGRATION_PLAN §2.1). Every wait is an
explicit Selenium wait for a condition; the only fixed pauses are the named settings
``timeouts.device_settle_s`` and ``timeouts.tab_settle_s``.

The client is meant for single-threaded use: one client per process at a time (the CLI and
the workflow run one). See :func:`_secret_input_logging` for the one piece of shared state.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec

from sivin.core.ids import SensorId
from sivin.ingest.portal.clock import Clock, SystemClock
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.portal.diagnostics import DownloadDiagnostics
from sivin.ingest.portal.driver import WebDriverFactory
from sivin.ingest.portal.errors import (
    DownloadIncompleteError,
    DownloadTimeoutError,
    PortalError,
    PortalLoginError,
    ViewModelError,
)
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.page import Locator, PortalPage
from sivin.ingest.portal.settings import PortalSettings
from sivin.ingest.portal.viewmodel import ViewModelParser
from sivin.ingest.portal.watcher import DownloadWatcher

logger = logging.getLogger(__name__)

SELENIUM_WIRE_LOGGER: Final = "selenium.webdriver.remote.remote_connection"
"""Selenium logger that writes request bodies (including typed text) at DEBUG level."""

_WIRE_LOGGER_LOCK: Final = threading.Lock()
"""Serialises the temporary level change of :data:`SELENIUM_WIRE_LOGGER` between threads."""


@contextmanager
def _secret_input_logging() -> Iterator[None]:
    """Silence Selenium's request logging while credentials are typed.

    The logger level is process-global. The lock makes two clients in different threads type
    their credentials one after the other, so neither restores the level while the other is
    typing; logging from other code into that logger is suppressed for that moment too.
    """
    wire_logger = logging.getLogger(SELENIUM_WIRE_LOGGER)
    with _WIRE_LOGGER_LOCK:
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
        Time source for the settle pauses and the download watcher.
    watcher : DownloadWatcher, optional
        Download detection; built from the settings when omitted.
    diagnostics : DownloadDiagnostics, optional
        Collects the WARNING block logged when a download fails; built from the settings and
        the watcher's directory when omitted.

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
        diagnostics: DownloadDiagnostics | None = None,
    ) -> None:
        if not settings.download_dir.is_absolute():
            raise ValueError(
                f"download_dir must be absolute, got {settings.download_dir}; "
                "resolve it with PortalSettings.resolved_against first."
            )
        self._settings = settings
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
            min_size_bytes=settings.min_export_size_bytes,
        )
        self._diagnostics = diagnostics or DownloadDiagnostics(settings, self._watcher.directory)
        self._web_driver: WebDriver | None = None
        self._devices: list[PortalDevice] = []

    @property
    def settings(self) -> PortalSettings:
        """Return the settings.

        Returns
        -------
        PortalSettings
            The client's settings.
        """
        return self._settings

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
        driver, page, selectors = self._driver, self._page, self._settings.selectors
        driver.get(self._settings.portal_url)
        try:
            username_field = page.wait().until(
                ec.presence_of_element_located((By.ID, selectors.username_id))
            )
            with _secret_input_logging():
                username_field.send_keys(self._credentials.username)
                driver.find_element(By.ID, selectors.password_id).send_keys(
                    self._credentials.password.reveal()
                )
            driver.find_element(By.CSS_SELECTOR, selectors.submit_css).click()
        except (TimeoutException, NoSuchElementException) as error:
            raise PortalLoginError(
                "The login form was not found; check selectors.username_id, password_id and "
                "submit_css."
            ) from error
        try:
            page.wait().until(ec.presence_of_element_located(self._folder_link()))
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
        viewmodel_id = self._settings.selectors.viewmodel_id
        element = self._page.wait().until(
            ec.presence_of_element_located((By.ID, viewmodel_id)),
            f"No viewmodel input #{viewmodel_id}.",
        )
        raw_json = element.get_attribute("value")
        if not raw_json:
            raise ViewModelError(f"The input #{viewmodel_id} has no value.")
        self._devices = self._parser.parse(raw_json)
        logger.info("Portal lists %d device(s): %s", len(self._devices), self._devices)
        return list(self._devices)

    def open_folder(self) -> None:
        """Click the folder link and wait until the page is idle."""
        self._page.click_when_clickable(
            self._folder_link(), f"Folder link {self._settings.folder_name!r} is not clickable."
        )
        self._page.wait_until_idle()

    def return_to_folder(self) -> None:
        """Reload the portal, open the folder and wait for the device list.

        Raises
        ------
        selenium.common.exceptions.TimeoutException
            If the device list does not appear.
        """
        self._driver.get(self._settings.portal_url)
        self.open_folder()
        self._page.wait().until(
            ec.presence_of_element_located(self._device_list_marker()),
            "The device list did not appear after reloading the portal.",
        )

    def back_to_device_list(self) -> None:
        """Go back from a device to the device list, reloading when ``back()`` is not enough.

        ``driver.back()`` is what the legacy script did. Whether it reaches the list depends on
        how many history entries the device page and its tab created, so the list is checked
        for ``timeouts.list_check_s``; when it is not there, :meth:`return_to_folder` is used.
        """
        self._driver.back()
        try:
            self._page.wait(self._settings.timeouts.list_check_s).until(
                ec.presence_of_element_located(self._device_list_marker())
            )
        except TimeoutException:
            logger.info("back() did not return to the device list; reloading the portal.")
            self.return_to_folder()

    def download_export(self, device: PortalDevice) -> Path:
        """Download the Excel export of one device; the browser stays on the device page.

        Parameters
        ----------
        device : PortalDevice
            A device from :meth:`list_devices`; the device list must be shown.

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
        DownloadIncompleteError
            If the new file is smaller than ``min_export_size_bytes``.
        selenium.common.exceptions.WebDriverException
            If an element does not appear in time or the browser fails.
        """
        page, timeouts = self._page, self._settings.timeouts
        page.wait_until_idle()
        page.click_when_present(page.link(device.name), f"No link for device {device.name!r}.")
        page.settle(timeouts.device_settle_s)
        page.wait_until_idle()
        page.click_when_clickable(
            page.tab(), f"Tab {self._settings.meteo_tab_name!r} is not clickable."
        )
        page.wait_until_idle()
        page.settle(timeouts.tab_settle_s)
        button = page.export_button(device)
        before = self._watcher.snapshot()
        page.press(button)
        try:
            path = self._watcher.wait_for_new_file(before, expected=device.sensor_id)
        except (DownloadTimeoutError, DownloadIncompleteError) as error:
            self._log_diagnostics(device, error)
            raise
        self._check_name(device, path)
        logger.info("Downloaded the export of %s: %s", device, path.name)
        return path

    def _log_diagnostics(self, device: PortalDevice, error: PortalError) -> None:
        """Log one WARNING block describing the failed download; never raises.

        The caller re-raises ``error``, so nothing here may replace it: an unexpected error
        while collecting is logged by its name only.
        """
        try:
            report = self._diagnostics.collect(self._driver)
        except Exception as failure:  # the original download error must reach the caller
            logger.warning(
                "Export of %s failed (%s); diagnostics unavailable (%s).",
                device,
                type(error).__name__,
                type(failure).__name__,
            )
            return
        logger.warning(
            "Export of %s failed (%s); diagnostics:\n%s", device, type(error).__name__, report
        )

    @staticmethod
    def _check_name(device: PortalDevice, path: Path) -> None:
        """Warn when the file name does not show which sensor it belongs to.

        A name with *another* sensor's serial never gets here: the watcher skips it.
        """
        if device.sensor_id is None:
            return
        try:
            SensorId.parse(path.name)
        except ValueError:
            logger.warning(
                "The export name %r has no sensor serial; it is attributed to %s only by timing.",
                path.name,
                device,
            )

    @property
    def _driver(self) -> WebDriver:
        if self._web_driver is None:
            raise RuntimeError("PortalClient is not open; use it in a 'with' block.")
        return self._web_driver

    @property
    def _page(self) -> PortalPage:
        return PortalPage(self._driver, self._settings, self._clock)

    def _folder_link(self) -> Locator:
        return self._page.link(self._settings.folder_name)

    def _device_list_marker(self) -> Locator:
        """Locator present only on the device list: the first listed device's link."""
        if self._devices:
            return self._page.link(self._devices[0].name)
        return By.ID, self._settings.selectors.viewmodel_id
