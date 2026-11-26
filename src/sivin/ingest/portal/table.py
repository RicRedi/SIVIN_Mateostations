"""Reading the device page's data table, page by page, as the fallback source (WP-1.10).

The device page shows the same measurements as the Excel export in the table *Historie
meteorologických dat*, newest first, with a paging control below it. :class:`TableReader`
decides *which* pages to read: newest to older, and only until a page reaches the last stored
measurement of the sensor (or every page when nothing is stored yet). *How* a page is read in
the browser is the job of a :class:`MeteoTable`
(:class:`~sivin.ingest.portal.table_page.PortalTablePage`), so this module needs no Selenium.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from sivin.ingest.portal.errors import TableReadError
from sivin.ingest.portal.settings import PortalTableSettings

logger = logging.getLogger(__name__)

EXPORT_TIMESTAMP_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
"""Timestamp format of the portal's CSV export (local wall-clock time, MIGRATION_PLAN §0.6.1)."""


@dataclass(frozen=True, slots=True)
class RawTable:
    """The cell texts of one table page as the browser shows them.

    Parameters
    ----------
    headers : tuple[str, ...]
        Texts of the header cells, left to right.
    rows : tuple[tuple[str, ...], ...]
        Texts of the body cells, row by row in page order (newest first).
    """

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    @property
    def first_row(self) -> tuple[str, ...] | None:
        """Return the first (newest) row.

        Returns
        -------
        tuple[str, ...] or None
            Its cell texts, or ``None`` for a page without rows.
        """
        return self.rows[0] if self.rows else None


@dataclass(frozen=True, slots=True)
class PagingStatus:
    """What the paging control says: ``Zobrazeno <shown> z <total> (<page size>)``.

    Parameters
    ----------
    shown_rows : int
        Rows on the current page (rows).
    total_rows : int
        Rows of the whole history (rows).
    page_size : int
        Selected page size (rows).
    """

    shown_rows: int
    total_rows: int
    page_size: int


class MeteoTable(Protocol):
    """The table of the open meteorological tab, as :class:`TableReader` uses it."""

    def wait_for_rows(self) -> RawTable:
        """Wait until the table shows rows and return the current page.

        Raises
        ------
        TableReadError
            If no row appears in time.
        """
        ...

    def change_page_size(self, page_size: int, current: RawTable) -> RawTable:
        """Try to select ``page_size`` rows per page; return the page shown afterwards."""
        ...

    def next_page(self, current: RawTable) -> RawTable | None:
        """Open the next (older) page; ``None`` when ``current`` is the last page.

        Raises
        ------
        TableReadError
            If the next page does not load.
        """
        ...


@dataclass(frozen=True, slots=True)
class TableRow:
    """One measurement row of the table, in the column order of the CSV export.

    Parameters
    ----------
    local_time : datetime.datetime
        Naive local wall-clock time of the measurement.
    cells : tuple[str, ...]
        The timestamp as in the export (``YYYY-MM-DD HH:MM:SS``), then the value texts as the
        table shows them (decimal comma), one per column of :attr:`TableReading.columns`.
    """

    local_time: datetime
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TableReading:
    """The rows read from a device's table.

    Parameters
    ----------
    columns : tuple[str, ...]
        CSV export headers of the cells, timestamp first.
    rows : tuple[TableRow, ...]
        Rows newer than the last stored measurement (all rows without one), newest first,
        without exact duplicates.
    pages_read : int
        Pages read (count).
    malformed_rows : int
        Rows skipped because their cell count or timestamp was wrong (count).
    reached_stored : bool
        Whether a read page reached the last stored measurement (always ``False`` without one).
    """

    columns: tuple[str, ...]
    rows: tuple[TableRow, ...]
    pages_read: int
    malformed_rows: int = 0
    reached_stored: bool = False


@dataclass(frozen=True, slots=True)
class ParsedPage:
    """The rows of one page that could be read.

    Parameters
    ----------
    columns : tuple[str, ...]
        CSV export headers of the cells, timestamp first.
    rows : tuple[TableRow, ...]
        Well-formed rows in page order.
    malformed_rows : int
        Rows skipped (count).
    """

    columns: tuple[str, ...]
    rows: tuple[TableRow, ...]
    malformed_rows: int


class TableRowParser:
    """Turn the cell texts of a page into :class:`TableRow` objects in the export's layout.

    Columns are found by their header text (``settings.columns``), so a reordered table is
    read correctly; table columns that are not configured are ignored. Values are kept as the
    table shows them: the existing export parser and the input validation judge them.

    Parameters
    ----------
    settings : PortalTableSettings
        ``columns`` (header text → export header; the first is the timestamp) and
        ``timestamp_format``.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: PortalTableSettings) -> None:
        self._settings = settings

    def parse(self, page: RawTable) -> ParsedPage:
        """Read one page.

        Parameters
        ----------
        page : RawTable
            Header and body texts.

        Returns
        -------
        ParsedPage
            The export headers present in the table and the well-formed rows.

        Raises
        ------
        TableReadError
            If the timestamp column is not among the headers.
        """
        positions = self._positions(page.headers)
        columns = tuple(self._settings.columns[header] for header, _ in positions)
        rows: list[TableRow] = []
        malformed = 0
        for cells in page.rows:
            row = self._row(cells, len(page.headers), positions)
            if row is None:
                malformed += 1
            else:
                rows.append(row)
        if malformed:
            logger.warning("Skipped %d malformed table row(s) of %d.", malformed, len(page.rows))
        return ParsedPage(columns, tuple(rows), malformed)

    def _positions(self, headers: tuple[str, ...]) -> list[tuple[str, int]]:
        """Return ``(table header, cell index)`` of every configured column present."""
        index = {header.strip(): position for position, header in enumerate(headers)}
        timestamp_header = next(iter(self._settings.columns))
        if timestamp_header not in index:
            raise TableReadError(
                f"The table has no column {timestamp_header!r} (headers: {list(headers)}); "
                "check ingest.portal.table.columns."
            )
        return [(header, index[header]) for header in self._settings.columns if header in index]

    def _row(
        self, cells: tuple[str, ...], width: int, positions: list[tuple[str, int]]
    ) -> TableRow | None:
        if len(cells) != width:
            logger.debug("Table row with %d cell(s) instead of %d: %s", len(cells), width, cells)
            return None
        timestamp_text = cells[positions[0][1]].strip()
        try:
            local_time = datetime.strptime(timestamp_text, self._settings.timestamp_format)
        except ValueError:
            logger.debug("Table row with an unreadable timestamp %r.", timestamp_text)
            return None
        values = tuple(cells[position].strip() for _, position in positions[1:])
        return TableRow(local_time, (local_time.strftime(EXPORT_TIMESTAMP_FORMAT), *values))


class TableReader:
    """Read the table newest to older, stopping at the last stored measurement.

    With a last stored time the page size is ``incremental_page_size`` and reading stops after
    the first page that holds a row at or before that time; only the newer rows are returned,
    so rows already stored are never sent to the store again. Without one (nothing stored),
    every page is read at ``full_history_page_size``. At most ``max_pages`` pages are read.

    Parameters
    ----------
    table : MeteoTable
        The table of the open meteorological tab.
    settings : PortalTableSettings
        Page sizes, page limit, columns, timestamp format and source time zone.
    parser : TableRowParser, optional
        Built from ``settings`` when omitted.
    """

    __slots__ = ("_parser", "_settings", "_table", "_zone")

    def __init__(
        self,
        table: MeteoTable,
        settings: PortalTableSettings,
        parser: TableRowParser | None = None,
    ) -> None:
        self._table = table
        self._settings = settings
        self._parser = parser or TableRowParser(settings)
        self._zone = ZoneInfo(settings.source_timezone)

    def read(self, since_utc: datetime | None) -> TableReading:
        """Read the rows newer than ``since_utc``.

        Parameters
        ----------
        since_utc : datetime.datetime or None
            Last stored measurement of the sensor (timezone-aware); ``None`` reads the whole
            history.

        Returns
        -------
        TableReading
            The new rows, newest first.

        Raises
        ------
        TableReadError
            If no rows appear, a page does not load, the columns change between pages or the
            timestamp column is missing.
        ValueError
            If ``since_utc`` is naive.
        """
        since_local = None if since_utc is None else self._local(since_utc)
        page_size = (
            self._settings.full_history_page_size
            if since_local is None
            else self._settings.incremental_page_size
        )
        page: RawTable | None = self._table.change_page_size(page_size, self._table.wait_for_rows())
        collector = _RowCollector()
        reached = False
        pages = 0
        while page is not None:
            pages += 1
            parsed = self._parser.parse(page)
            collector.add(parsed)
            reached = since_local is not None and any(
                row.local_time <= since_local for row in parsed.rows
            )
            if reached:
                break
            if pages >= self._settings.max_pages:
                logger.warning(
                    "Stopped after max_pages = %d table pages before %s; older rows were not read.",
                    self._settings.max_pages,
                    "the last stored measurement" if since_local is not None else "the last page",
                )
                break
            page = self._table.next_page(page)
        rows = collector.rows_after(since_local)
        return TableReading(collector.columns, rows, pages, collector.malformed, reached)

    def _local(self, since_utc: datetime) -> datetime:
        """Return ``since_utc`` as naive wall-clock time of the source zone."""
        if since_utc.tzinfo is None:
            raise ValueError("since_utc must be timezone-aware.")
        return since_utc.astimezone(UTC).astimezone(self._zone).replace(tzinfo=None)


class _RowCollector:
    """Rows of several pages, newest first, without exact duplicates.

    A measurement that arrives while the pages are read shifts every page by one row, so a page
    can start with the last row of the page before; such a repeated row is identical and kept
    once.
    """

    __slots__ = ("_columns", "_malformed", "_rows", "_seen")

    def __init__(self) -> None:
        self._columns: tuple[str, ...] | None = None
        self._rows: list[TableRow] = []
        self._seen: set[tuple[str, ...]] = set()
        self._malformed = 0

    @property
    def columns(self) -> tuple[str, ...]:
        return self._columns or ()

    @property
    def malformed(self) -> int:
        return self._malformed

    def add(self, page: ParsedPage) -> None:
        if self._columns is None:
            self._columns = page.columns
        elif page.columns != self._columns:
            raise TableReadError(
                f"The table columns changed between pages: {list(self._columns)} → "
                f"{list(page.columns)}."
            )
        self._malformed += page.malformed_rows
        for row in page.rows:
            if row.cells not in self._seen:
                self._seen.add(row.cells)
                self._rows.append(row)

    def rows_after(self, since_local: datetime | None) -> tuple[TableRow, ...]:
        if since_local is None:
            return tuple(self._rows)
        return tuple(row for row in self._rows if row.local_time > since_local)
