"""Low-level page operations on the portal: locators, explicit waits and clicks.

:class:`PortalPage` knows *how* to find and click things on the portal's pages;
:class:`~sivin.ingest.portal.client.PortalClient` decides *what* to do in which order.
"""

from __future__ import annotations

import logging
from typing import Final, cast

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

from sivin.ingest.portal.clock import Clock
from sivin.ingest.portal.errors import ExportButtonNotFoundError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.settings import TEXT_PLACEHOLDER, PortalSettings

logger = logging.getLogger(__name__)

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


class PortalPage:
    """Explicit waits, locators and clicks on the portal's pages.

    Parameters
    ----------
    driver : selenium.webdriver.remote.webdriver.WebDriver
        The open browser.
    settings : PortalSettings
        Selectors, names and waiting times.
    clock : Clock
        Time source for the fixed settle pauses.
    """

    def __init__(self, driver: WebDriver, settings: PortalSettings, clock: Clock) -> None:
        self._driver = driver
        self._settings = settings
        self._selectors = settings.selectors
        self._clock = clock

    def wait(self, timeout_s: float | None = None) -> WebDriverWait[WebDriver]:
        """Return an explicit wait.

        Parameters
        ----------
        timeout_s : float, optional
            Maximum wait (s); ``timeouts.element_wait_s`` when omitted.

        Returns
        -------
        selenium.webdriver.support.wait.WebDriverWait
            The wait, polling every ``timeouts.poll_interval_s``.
        """
        timeouts = self._settings.timeouts
        return WebDriverWait(
            self._driver,
            timeouts.element_wait_s if timeout_s is None else timeout_s,
            poll_frequency=timeouts.poll_interval_s,
        )

    def wait_until_idle(self) -> None:
        """Wait until the DotVVM spinner is absent or hidden."""
        self.wait().until(
            ec.invisibility_of_element_located((By.ID, self._selectors.spinner_id)),
            f"Spinner #{self._selectors.spinner_id} is still visible.",
        )

    def settle(self, duration_s: float) -> None:
        """Pause for a fixed time (a named setting) when it is positive.

        Parameters
        ----------
        duration_s : float
            Pause (s).
        """
        if duration_s > 0:
            self._clock.sleep(duration_s)

    def click(self, element: WebElement) -> None:
        """Click an element through JavaScript.

        Parameters
        ----------
        element : selenium.webdriver.remote.webelement.WebElement
            The element.
        """
        self._driver.execute_script(JS_CLICK, element)

    def click_when_present(self, locator: Locator, message: str) -> None:
        """Wait for an element to be present, then click it.

        Parameters
        ----------
        locator : tuple[str, str]
            Selenium locator.
        message : str
            Message of the ``TimeoutException`` when the element does not appear.
        """
        self.click(self.wait().until(ec.presence_of_element_located(locator), message))

    def click_when_clickable(self, locator: Locator, message: str) -> None:
        """Wait for an element to be visible and enabled, then click it.

        Parameters
        ----------
        locator : tuple[str, str]
            Selenium locator.
        message : str
            Message of the ``TimeoutException`` when the element does not become clickable.
        """
        self.click(self.wait().until(ec.element_to_be_clickable(locator), message))

    def link(self, text: str) -> Locator:
        """Return the locator of a link whose text contains ``text``.

        Parameters
        ----------
        text : str
            Link text (folder or device name).

        Returns
        -------
        tuple[str, str]
            XPath locator.
        """
        return By.XPATH, self._fill(self._selectors.link_xpath_template, text)

    def tab(self) -> Locator:
        """Return the locator of the meteorological tab link.

        Returns
        -------
        tuple[str, str]
            XPath locator.
        """
        return By.XPATH, self._fill(
            self._selectors.tab_xpath_template, self._settings.meteo_tab_name
        )

    def section_buttons(self) -> Locator:
        """Return the locator of the Excel buttons inside the export section.

        Returns
        -------
        tuple[str, str]
            XPath locator.
        """
        template = self._selectors.section_button_xpath_template
        return By.XPATH, self._fill(template, self._settings.export_section_name)

    def export_button(self, device: PortalDevice) -> WebElement:
        """Wait for the visible Excel button of the export section.

        The button inside the section headed ``export_section_name`` is preferred; its being
        visible also shows that the meteorological tab is active. When it does not appear, the
        first visible Excel button anywhere is used, with a warning (the legacy rule).

        Parameters
        ----------
        device : PortalDevice
            The device (for messages).

        Returns
        -------
        selenium.webdriver.remote.webelement.WebElement
            The button.

        Raises
        ------
        ExportButtonNotFoundError
            If no visible Excel button appears at all.
        """
        try:
            return self._first_visible(self.section_buttons())
        except TimeoutException:
            logger.warning(
                "No Excel button in section %r for %s; using the first visible Excel button. "
                "Check export_section_name and selectors.section_button_xpath_template.",
                self._settings.export_section_name,
                device,
            )
        try:
            return self._first_visible((By.XPATH, self._selectors.excel_button_xpath))
        except TimeoutException as error:
            raise ExportButtonNotFoundError(
                f"No visible Excel button for {device}; check selectors.excel_button_xpath."
            ) from error

    def press(self, button: WebElement) -> None:
        """Scroll a button into view and click it.

        Parameters
        ----------
        button : selenium.webdriver.remote.webelement.WebElement
            The button.
        """
        self._driver.execute_script(JS_SCROLL_INTO_VIEW, button)
        self.click(button)

    def _first_visible(self, locator: Locator) -> WebElement:
        def first_visible(driver: WebDriver) -> WebElement | bool:
            elements = driver.find_elements(*locator)
            return next((element for element in elements if element.is_displayed()), False)

        return cast(WebElement, self.wait().until(first_visible))

    @staticmethod
    def _fill(template: str, text: str) -> str:
        return template.replace(TEXT_PLACEHOLDER, xpath_literal(text))
