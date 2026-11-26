"""Fakes of the device table (WP-1.10): a table in a fake browser, and a pure table.

Everything here is SYNTHETIC unless it comes from :func:`real_excerpt`, which reads the
trimmed excerpt of a real device page (``data/meteo_table_excerpt.html``; public measured data,
nothing account-related). No browser, no network.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from tests.ingest.portal.conftest import FakePortalDriver

from sivin.ingest.portal.page import JS_CLICK, xpath_literal
from sivin.ingest.portal.settings import TEXT_PLACEHOLDER, PortalSettings
from sivin.ingest.portal.table import RawTable
from sivin.ingest.portal.table_page import JS_READ_TABLE

EXCERPT = Path(__file__).parent / "data" / "meteo_table_excerpt.html"
"""Excerpt of a real device page: tab link, table header, 20 rows, paging control."""

HEADERS = ("Datum a čas", "Teplota", "Vlhkost", "Srážky", "Celkové srážky", "Nabití baterie")
"""The table headers of the real page."""

PAGE_SIZES = (10, 15, 20, 30, 50, 100, 500, 1000, 5000)
"""The page sizes the real page offers (``RecordsPerPage`` of its viewmodel)."""

STEP = timedelta(seconds=1800)
"""Step of the SYNTHETIC rows (s)."""


def synthetic_rows(newest: datetime, count: int, step: timedelta = STEP) -> list[tuple[str, ...]]:
    """Return ``count`` SYNTHETIC table rows, newest first, in the table's text format.

    The temperature of row ``i`` (0 = newest) is ``10,<i>``; humidity 50, no rain, counter
    100, battery 3,5.
    """
    rows = []
    for index in range(count):
        local = newest - index * step
        stamp = f"{local.day:02d}.{local.month:02d}.{local.year} {local.hour}:{local:%M:%S}"
        rows.append((stamp, f"10,{index}", "50", "0", "100", "3,5"))
    return rows


@dataclass
class TableState:
    """The fake table of one device: all rows, paging and page size.

    Attributes
    ----------
    rows : list of tuple of str
        All rows, newest first.
    page_size : int
        Rows per page.
    cycle : bool
        Whether the page-size button wraps from the largest size to the smallest.
    size_button_works : bool
        Whether a click on the page-size button changes the size.
    next_loads : bool
        Whether a click on the next-page button loads the next page.
    """

    rows: list[tuple[str, ...]]
    headers: tuple[str, ...] = HEADERS
    page_size: int = 5000
    page_index: int = 0
    cycle: bool = True
    size_button_works: bool = True
    next_loads: bool = True
    show_paging: bool = True
    show_size_button: bool = True
    clicks: list[str] = field(default_factory=list)
    on_next: Callable[[TableState], None] | None = None

    @property
    def last_page_index(self) -> int:
        return max(0, (len(self.rows) - 1) // self.page_size)

    def page(self) -> list[tuple[str, ...]]:
        start = self.page_index * self.page_size
        return self.rows[start : start + self.page_size]

    def paging_text(self) -> str:
        pages = " ".join(str(number + 1) for number in range(self.last_page_index + 1))
        shown = len(self.page())
        return f"{pages}\nZobrazeno {shown} z {len(self.rows)} ({self.page_size})"

    def click_size(self) -> None:
        self.clicks.append("size")
        if not self.size_button_works:
            return
        position = PAGE_SIZES.index(self.page_size)
        if position + 1 < len(PAGE_SIZES):
            self.page_size = PAGE_SIZES[position + 1]
        elif self.cycle:
            self.page_size = PAGE_SIZES[0]
        self.page_index = 0

    def click_next(self) -> None:
        self.clicks.append("next")
        if self.on_next is not None:
            self.on_next(self)
        if self.next_loads and self.page_index < self.last_page_index:
            self.page_index += 1


class TableElement:
    """An element of the fake table (table, paging control or button)."""

    def __init__(
        self,
        key: str,
        state: TableState,
        *,
        on_click: Callable[[], None] | None = None,
        enabled: bool = True,
        displayed: bool = True,
        text: str = "",
        stale: bool = False,
    ) -> None:
        self.key = key
        self.state = state
        self._on_click = on_click
        self._enabled = enabled
        self._displayed = displayed
        self._text = text
        self.stale = stale

    @property
    def text(self) -> str:
        if self.stale:
            raise StaleElementReferenceException("stale")
        return self._text

    def click(self) -> None:
        if self._on_click is not None:
            self._on_click()

    def is_displayed(self) -> bool:
        if self.stale:
            raise StaleElementReferenceException("stale")
        return self._displayed

    def is_enabled(self) -> bool:
        return self._enabled


class TableLocators:
    """The absolute XPath locators :class:`PortalTablePage` builds from the settings."""

    def __init__(self, settings: PortalSettings) -> None:
        table = settings.table
        card = table.card_xpath_template.replace(
            TEXT_PLACEHOLDER, xpath_literal(settings.export_section_name)
        )
        self.table = (By.XPATH, table.within_card(card, table.table_xpath))
        self.paging = (By.XPATH, table.within_card(card, table.paging_xpath))
        self.next_page = (By.XPATH, table.within_card(card, table.next_page_xpath))
        self.page_size = (By.XPATH, table.within_card(card, table.page_size_xpath))


def table_elements(
    settings: PortalSettings, state: TableState
) -> dict[tuple[str, str], list[TableElement]]:
    """Return the elements of the fake table, keyed by the locators of the settings."""
    locators = TableLocators(settings)
    elements: dict[tuple[str, str], list[TableElement]] = {}
    if state.rows:
        elements[locators.table] = [TableElement("table", state)]
    if state.show_paging:
        elements[locators.paging] = [TableElement("paging", state, text=state.paging_text())]
        elements[locators.next_page] = [
            TableElement("next:hidden", state, displayed=False),
            TableElement(
                "next",
                state,
                on_click=state.click_next,
                enabled=state.page_index < state.last_page_index,
            ),
        ]
        if state.show_size_button:
            elements[locators.page_size] = [TableElement("size", state, on_click=state.click_size)]
    return elements


def read_table(element: TableElement) -> dict[str, Any]:
    """What :data:`JS_READ_TABLE` returns for the fake table."""
    if element.stale:
        raise StaleElementReferenceException("stale")
    state = element.state
    return {"headers": list(state.headers), "rows": [list(row) for row in state.page()]}


class FakeTableDriver:
    """A WebDriver look-alike that shows only the meteorological tab of one device."""

    def __init__(self, settings: PortalSettings, state: TableState) -> None:
        self.settings = settings
        self.state = state
        self.script_result: object | None = None
        self.stale_tables = 0

    def find_elements(self, by: str, value: str) -> list[TableElement]:
        if (by, value) == (By.ID, self.settings.selectors.spinner_id):
            return []
        found = table_elements(self.settings, self.state).get((by, value), [])
        if found and found[0].key == "table" and self.stale_tables > 0:
            self.stale_tables -= 1
            found[0].stale = True
        return found

    def find_element(self, by: str, value: str) -> TableElement:
        found = self.find_elements(by, value)
        if not found:
            raise NoSuchElementException(f"{by}={value}")
        return found[0]

    def execute_script(self, script: str, *args: Any) -> object:
        if script == JS_CLICK:
            args[0].click()
            return None
        if script == JS_READ_TABLE:
            if self.script_result is not None:
                return self.script_result
            return read_table(args[0])
        raise AssertionError(f"unexpected script {script!r}")


class TablePortalDriver(FakePortalDriver):
    """The WP-1.3 fake portal whose meteorological tabs also show a device table."""

    def __init__(
        self,
        settings: PortalSettings,
        viewmodel_json: str,
        behaviours: dict[str, str] | None = None,
        tables: dict[str, TableState] | None = None,
    ) -> None:
        super().__init__(settings, viewmodel_json, behaviours)
        self.tables = tables or {}

    def execute_script(self, script: str, *args: Any) -> Any:
        if script == JS_READ_TABLE:
            return read_table(args[0])
        return super().execute_script(script, *args)

    def _meteo_page(self, name: str) -> dict[tuple[str, str], list[Any]]:
        elements: dict[tuple[str, str], list[Any]] = dict(super()._meteo_page(name))
        state = self.tables.get(name)
        if state is not None:
            elements.update(table_elements(self.settings, state))
        return elements


class FakeMeteoTable:
    """A pure :class:`~sivin.ingest.portal.table.MeteoTable` over a :class:`TableState`."""

    def __init__(self, state: TableState, sizes_reachable: bool = True) -> None:
        self.state = state
        self.sizes_reachable = sizes_reachable
        self.requested_sizes: list[int] = []
        self.pages_opened = 0

    def wait_for_rows(self) -> RawTable:
        return self._current()

    def change_page_size(self, page_size: int, current: RawTable) -> RawTable:
        self.requested_sizes.append(page_size)
        if self.sizes_reachable:
            self.state.page_size = page_size
            self.state.page_index = 0
            return self._current()
        return current

    def next_page(self, current: RawTable) -> RawTable | None:
        if self.state.page_index >= self.state.last_page_index:
            return None
        self.state.page_index += 1
        self.pages_opened += 1
        return self._current()

    def _current(self) -> RawTable:
        return RawTable(self.state.headers, tuple(self.state.page()))


@dataclass
class ExcerptContent:
    """Texts of the real excerpt: table header, body rows and the paging control's text."""

    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    paging_text: str = ""
    tab_text: str = ""


_VOID_TAGS = frozenset({"br", "meta", "img", "input", "hr", "link"})
"""HTML elements without an end tag."""


class _ExcerptParser(HTMLParser):
    """Collects the cell texts and the visible text of the paging control (stdlib only)."""

    def __init__(self) -> None:
        super().__init__()
        self.content = ExcerptContent()
        self._stack: list[tuple[str, dict[str, str | None]]] = []
        self._cell: list[str] | None = None
        self._row: list[str] | None = None
        self._paging_depth: int | None = None
        self._hidden_depth: int | None = None
        self._paging: list[str] = []
        self._in_tab = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_TAGS:
            return
        attributes = dict(attrs)
        self._stack.append((tag, attributes))
        depth = len(self._stack)
        bind = attributes.get("data-bind") or ""
        if self._paging_depth is None and "dotvvm-with-control-properties" in bind:
            self._paging_depth = depth
        if "display: none" in (attributes.get("style") or "") and self._hidden_depth is None:
            self._hidden_depth = depth
        if tag == "tr":
            self._row = []
        if tag in {"td", "th"}:
            self._cell = []
        if tag == "a" and "nav-link" in (attributes.get("class") or ""):
            self._in_tab = True

    def handle_endtag(self, tag: str) -> None:
        depth = len(self._stack)
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        if tag == "tr" and self._row is not None:
            if self._row and self._inside("thead"):
                self.content.headers = self._row
            elif self._row:
                self.content.rows.append(self._row)
            self._row = None
        if tag == "a":
            self._in_tab = False
        if self._hidden_depth == depth:
            self._hidden_depth = None
        if self._paging_depth == depth:
            self.content.paging_text = " ".join("".join(self._paging).split())
            self._paging_depth = None
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        if self._paging_depth is not None and self._hidden_depth is None:
            self._paging.append(data)
        if self._in_tab:
            self.content.tab_text += data

    def _inside(self, tag: str) -> bool:
        return any(name == tag for name, _ in self._stack)


def real_excerpt() -> ExcerptContent:
    """Read the excerpt of the real device page (see the comment at the top of the file)."""
    parser = _ExcerptParser()
    parser.feed(EXCERPT.read_text(encoding="utf-8"))
    return parser.content


def raw_table(rows: Sequence[Sequence[str]], headers: Sequence[str] = HEADERS) -> RawTable:
    """Build a :class:`RawTable` of texts."""
    return RawTable(tuple(headers), tuple(tuple(row) for row in rows))
