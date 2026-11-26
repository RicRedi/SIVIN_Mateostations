"""The data table of the meteorological tab in the browser: rows, paging and page size.

:class:`PortalTablePage` implements :class:`~sivin.ingest.portal.table.MeteoTable` with
Selenium. Every element is searched inside the card headed ``export_section_name`` (other tabs
of the device page have paging controls of their own). A page is read with one JavaScript call
that returns all cell texts, so a page of 5000 rows costs one round trip, not 30 000.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Final, TypeGuard

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from sivin.ingest.portal.clock import Clock
from sivin.ingest.portal.errors import TableReadError
from sivin.ingest.portal.page import Locator, PortalPage, xpath_literal
from sivin.ingest.portal.settings import TEXT_PLACEHOLDER, PortalSettings
from sivin.ingest.portal.table import PagingStatus, RawTable

logger = logging.getLogger(__name__)

JS_READ_TABLE: Final = """
const table = arguments[0];
const texts = (cells) => Array.from(cells, (cell) => cell.textContent.trim());
return {
  headers: texts(table.querySelectorAll('thead th')),
  rows: Array.from(table.querySelectorAll('tbody > tr'), (row) => texts(row.cells)),
};
"""
"""Returns ``{headers: [...], rows: [[...], ...]}``: the trimmed text of every cell."""

HEADERS_KEY: Final = "headers"
ROWS_KEY: Final = "rows"

_SPACES: Final = re.compile(r"\s+")


class PortalTablePage:
    """The table *Historie meteorologických dat* of the open meteorological tab.

    Parameters
    ----------
    driver : selenium.webdriver.remote.webdriver.WebDriver
        The browser, showing the meteorological tab of a device.
    settings : PortalSettings
        ``export_section_name``, ``table`` (locators, waits, page-size clicks) and
        ``timeouts``.
    clock : Clock
        Time source of the page operations.
    """

    __slots__ = ("_driver", "_page", "_paging_pattern", "_settings", "_table")

    def __init__(self, driver: WebDriver, settings: PortalSettings, clock: Clock) -> None:
        self._driver = driver
        self._settings = settings
        self._table = settings.table
        self._page = PortalPage(driver, settings, clock)
        self._paging_pattern = re.compile(settings.table.paging_text_pattern)

    def wait_for_rows(self) -> RawTable:
        """Wait up to ``table.rows_wait_s`` until the table shows rows.

        Returns
        -------
        RawTable
            The current page.

        Raises
        ------
        TableReadError
            If no row appears in time (the table is empty or did not load).
        """
        found: list[RawTable] = []

        def has_rows(_: WebDriver) -> bool:
            page = self._read()
            if page is None or not page.rows:
                return False
            found.append(page)
            return True

        try:
            self._page.wait(self._table.rows_wait_s).until(has_rows)
        except TimeoutException as error:
            raise TableReadError(
                f"No rows in the table {self._settings.export_section_name!r} within "
                f"{self._table.rows_wait_s:g} s ({self._describe_paging()}); the table is empty "
                "or did not load. Check ingest.portal.table.card_xpath_template and table_xpath."
            ) from error
        return found[-1]

    def paging(self) -> PagingStatus | None:
        """Read the paging control.

        Returns
        -------
        PagingStatus or None
            Shown rows, total rows and page size, or ``None`` when the control or its text is
            not found.
        """
        element = self._first_visible(self._locator(self._table.paging_xpath))
        if element is None:
            return None
        try:
            text = element.text
        except StaleElementReferenceException:
            return None
        match = self._paging_pattern.search(text)
        if match is None:
            return None
        return PagingStatus(
            shown_rows=_number(match["shown"]),
            total_rows=_number(match["total"]),
            page_size=_number(match["page_size"]),
        )

    def change_page_size(self, page_size: int, current: RawTable) -> RawTable:
        """Click the page-size button until the paging control shows ``page_size``.

        The button's behaviour is assumed (it steps through the portal's sizes), so a size
        that is not reached within ``table.max_page_size_clicks`` clicks, or a click that
        changes nothing, is logged and reading goes on with the size shown.

        Parameters
        ----------
        page_size : int
            Wanted rows per page (rows).
        current : RawTable
            The page shown now.

        Returns
        -------
        RawTable
            The page shown afterwards (``current`` when nothing was clicked).
        """
        for _ in range(self._table.max_page_size_clicks):
            status = self.paging()
            if status is None:
                logger.warning("No paging control found; reading with the page size shown.")
                return current
            if status.page_size == page_size:
                return current
            button = self._first_visible(self._locator(self._table.page_size_xpath))
            if button is None:
                logger.warning("No page-size button; reading %d rows per page.", status.page_size)
                return current
            self._page.click(button)
            if not self._wait_for_page_size_change(status.page_size):
                logger.warning(
                    "The page size stayed at %d rows after a click; reading with it.",
                    status.page_size,
                )
                return current
            self._page.wait_until_idle()
            current = self.wait_for_rows()
        status = self.paging()
        if status is not None and status.page_size != page_size:
            logger.warning(
                "Page size %d not reached after %d click(s); reading %d rows per page.",
                page_size,
                self._table.max_page_size_clicks,
                status.page_size,
            )
        return current

    def next_page(self, current: RawTable) -> RawTable | None:
        """Open the next (older) page.

        Parameters
        ----------
        current : RawTable
            The page shown now; the next page counts as loaded when its first row differs.

        Returns
        -------
        RawTable or None
            The next page, or ``None`` when the next-page button is missing or disabled (the
            last page).

        Raises
        ------
        TableReadError
            If the next page does not load within ``timeouts.element_wait_s``.
        """
        button = self._first_visible(self._locator(self._table.next_page_xpath))
        if button is None or not button.is_enabled():
            return None
        self._page.click(button)
        found: list[RawTable] = []

        def page_changed(_: WebDriver) -> bool:
            page = self._read()
            if page is None or not page.rows or page.first_row == current.first_row:
                return False
            found.append(page)
            return True

        try:
            self._page.wait().until(page_changed)
        except TimeoutException as error:
            raise TableReadError(
                f"The next table page did not load ({self._describe_paging()})."
            ) from error
        self._page.wait_until_idle()
        return found[-1]

    def _wait_for_page_size_change(self, previous: int) -> bool:
        def changed(_: WebDriver) -> bool:
            status = self.paging()
            return status is not None and status.page_size != previous

        try:
            self._page.wait().until(changed)
        except TimeoutException:
            return False
        return True

    def _read(self) -> RawTable | None:
        """Return the cell texts of the table, or ``None`` when it is not rendered."""
        tables = self._driver.find_elements(By.XPATH, self._locator(self._table.table_xpath)[1])
        if not tables:
            return None
        try:
            data = self._driver.execute_script(JS_READ_TABLE, tables[0])
        except StaleElementReferenceException:
            return None
        return _raw_table(data)

    def _first_visible(self, locator: Locator) -> WebElement | None:
        for element in self._driver.find_elements(*locator):
            try:
                if element.is_displayed():
                    return element
            except StaleElementReferenceException:
                continue
        return None

    def _locator(self, relative_xpath: str) -> Locator:
        card = self._table.card_xpath_template.replace(
            TEXT_PLACEHOLDER, xpath_literal(self._settings.export_section_name)
        )
        return By.XPATH, self._table.within_card(card, relative_xpath)

    def _describe_paging(self) -> str:
        status = self.paging()
        if status is None:
            return "no paging text found"
        return (
            f"paging shows {status.shown_rows} of {status.total_rows} rows, page size "
            f"{status.page_size}"
        )


def _number(text: str) -> int:
    return int(_SPACES.sub("", text))


def _raw_table(data: object) -> RawTable:
    """Check the script's result and turn it into a :class:`RawTable`.

    Raises
    ------
    TableReadError
        If the result does not have the shape :data:`JS_READ_TABLE` returns.
    """
    if not isinstance(data, Mapping):
        raise TableReadError(f"Unexpected table script result of type {type(data).__name__}.")
    headers = data.get(HEADERS_KEY)
    rows = data.get(ROWS_KEY)
    if not _is_texts(headers) or not _is_list(rows):
        raise TableReadError("Unexpected table script result: no header and row texts.")
    checked: list[tuple[str, ...]] = []
    for row in rows:
        if not _is_texts(row):
            raise TableReadError("Unexpected table script result: a row is not a list of texts.")
        checked.append(tuple(row))
    return RawTable(tuple(headers), tuple(checked))


def _is_list(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, str)


def _is_texts(value: object) -> TypeGuard[Sequence[str]]:
    return _is_list(value) and all(isinstance(item, str) for item in value)
