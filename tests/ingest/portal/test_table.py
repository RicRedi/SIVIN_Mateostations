"""TableRowParser and TableReader: which pages are read and which rows are kept (WP-1.10).

The rows are SYNTHETIC, except where they come from the excerpt of a real device page
(``real_excerpt``). Expected values are worked out by hand in the comments.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from tests.ingest.portal.table_fakes import (
    HEADERS,
    FakeMeteoTable,
    TableState,
    raw_table,
    real_excerpt,
    synthetic_rows,
)

from sivin.ingest.portal.errors import TableReadError
from sivin.ingest.portal.settings import PortalTableSettings
from sivin.ingest.portal.table import RawTable, TableReader, TableRow, TableRowParser

EXPORT_COLUMNS = (
    "Datum a čas",
    "Teplota (°C)",
    "Vlhkost (%)",
    "Srážky (mm)",
    "Celkové srážky (mm)",
    "Nabití baterie (V)",
)

NEWEST = datetime(2026, 11, 20, 12, 0, 0)
"""Local time of the newest SYNTHETIC row (CET, UTC+1)."""


def _settings(**changes: object) -> PortalTableSettings:
    return PortalTableSettings(incremental_page_size=5, full_history_page_size=10).model_copy(
        update=changes
    )


def _local_times(rows: tuple[TableRow, ...]) -> list[str]:
    return [row.local_time.strftime("%H:%M") for row in rows]


class TestRowParser:
    def test_real_rows_become_export_rows(self) -> None:
        excerpt = real_excerpt()
        page = raw_table(excerpt.rows, excerpt.headers)

        parsed = TableRowParser(PortalTableSettings()).parse(page)

        assert parsed.columns == EXPORT_COLUMNS
        assert parsed.malformed_rows == 0
        assert len(parsed.rows) == 20
        assert parsed.rows[0] == TableRow(
            datetime(2026, 11, 18, 13, 49, 25),
            ("2026-11-18 13:49:25", "24,3848", "35,498", "0", "200,57", "3,3"),
        )
        # "18.11.2026 9:53:11" has a one-digit hour on the page; the export pads it.
        assert parsed.rows[8].cells[0] == "2026-11-18 09:53:11"
        assert parsed.rows[-1].cells[0] == "2026-11-18 04:28:17"

    def test_columns_are_found_by_header_text(self) -> None:
        page = raw_table(
            [("21,5", "1.12.2026 0:05:00", "x", "80,1")],
            headers=("Teplota", "Datum a čas", "Unknown column", "Vlhkost"),
        )

        parsed = TableRowParser(PortalTableSettings()).parse(page)

        assert parsed.columns == ("Datum a čas", "Teplota (°C)", "Vlhkost (%)")
        assert parsed.rows[0].cells == ("2026-12-01 00:05:00", "21,5", "80,1")

    def test_missing_timestamp_column_is_an_error(self) -> None:
        page = raw_table([("21,5",)], headers=("Teplota",))

        with pytest.raises(TableReadError, match="no column 'Datum a čas'"):
            TableRowParser(PortalTableSettings()).parse(page)

    def test_malformed_rows_are_skipped_and_counted(self, caplog: pytest.LogCaptureFixture) -> None:
        rows = [
            ("20.11.2026 12:00:00", "1", "2", "0", "100", "3,5"),
            ("20.11.2026 11:30:00", "1", "2", "0", "100"),  # one cell short
            ("31.02.2026 11:00:00", "1", "2", "0", "100", "3,5"),  # no such day
            ("", "", "", "", "", ""),  # empty row
            ("20.11.2026 10:30:00", "abc", "2", "0", "100", "3,5"),  # value left to validation
        ]

        with caplog.at_level(logging.WARNING):
            parsed = TableRowParser(PortalTableSettings()).parse(raw_table(rows))

        assert parsed.malformed_rows == 3
        assert [row.cells[0] for row in parsed.rows] == [
            "2026-11-20 12:00:00",
            "2026-11-20 10:30:00",
        ]
        assert parsed.rows[1].cells[1] == "abc"
        assert "Skipped 3 malformed table row(s) of 5." in caplog.text


class TestIncrementalReading:
    def test_stops_at_the_page_that_reaches_the_last_stored_row(self) -> None:
        state = TableState(synthetic_rows(NEWEST, 30), page_size=5000)
        table = FakeMeteoTable(state)
        # 05:00 UTC = 06:00 CET. Newer rows: 12:00, 11:30, ..., 06:30 = 12 rows. With 5 rows
        # per page, page 3 (07:00 ... 05:00) holds 06:00, so pages 4-6 are never opened.
        since_utc = datetime(2026, 11, 20, 5, 0, tzinfo=UTC)

        reading = TableReader(table, _settings()).read(since_utc)

        assert table.requested_sizes == [5]
        assert reading.pages_read == 3
        assert table.pages_opened == 2
        assert reading.reached_stored
        assert len(reading.rows) == 12
        assert _local_times(reading.rows)[0] == "12:00"
        assert _local_times(reading.rows)[-1] == "06:30"
        assert reading.columns == EXPORT_COLUMNS

    def test_summer_time_is_converted_with_the_source_zone(self) -> None:
        newest = datetime(2026, 7, 1, 12, 0, 0)  # CEST, UTC+2
        table = FakeMeteoTable(TableState(synthetic_rows(newest, 10)))
        since_utc = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)  # 11:00 CEST

        reading = TableReader(table, _settings()).read(since_utc)

        assert _local_times(reading.rows) == ["12:00", "11:30"]
        assert reading.pages_read == 1

    def test_nothing_newer_gives_no_rows(self) -> None:
        table = FakeMeteoTable(TableState(synthetic_rows(NEWEST, 30)))
        since_utc = datetime(2026, 11, 20, 11, 0, tzinfo=UTC)  # 12:00 CET, the newest row

        reading = TableReader(table, _settings()).read(since_utc)

        assert reading.rows == ()
        assert reading.pages_read == 1
        assert reading.reached_stored

    def test_an_unreachable_page_size_only_changes_the_page_count(self) -> None:
        state = TableState(synthetic_rows(NEWEST, 30), page_size=4)
        table = FakeMeteoTable(state, sizes_reachable=False)
        since_utc = datetime(2026, 11, 20, 5, 0, tzinfo=UTC)

        reading = TableReader(table, _settings()).read(since_utc)

        # 4 rows per page: 06:00 is row 12 (0-based), on page 4 (rows 12-15).
        assert reading.pages_read == 4
        assert len(reading.rows) == 12

    def test_naive_since_is_refused(self) -> None:
        table = FakeMeteoTable(TableState(synthetic_rows(NEWEST, 3)))

        with pytest.raises(ValueError, match="timezone-aware"):
            TableReader(table, _settings()).read(datetime(2026, 11, 20, 5, 0))


class TestFullHistory:
    def test_reads_every_page_at_the_full_history_size(self) -> None:
        table = FakeMeteoTable(TableState(synthetic_rows(NEWEST, 25), page_size=500))

        reading = TableReader(table, _settings()).read(None)

        assert table.requested_sizes == [10]
        assert reading.pages_read == 3  # 10 + 10 + 5 rows
        assert len(reading.rows) == 25
        assert not reading.reached_stored

    def test_max_pages_stops_with_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        table = FakeMeteoTable(TableState(synthetic_rows(NEWEST, 25)))

        with caplog.at_level(logging.WARNING):
            reading = TableReader(table, _settings(max_pages=2)).read(None)

        assert reading.pages_read == 2
        assert len(reading.rows) == 20
        assert "Stopped after max_pages = 2 table pages before the last page" in caplog.text


class ScriptedTable:
    """A MeteoTable that serves fixed pages, for shifted and inconsistent pages."""

    def __init__(self, pages: list[RawTable]) -> None:
        self.pages = pages
        self.index = 0

    def wait_for_rows(self) -> RawTable:
        return self.pages[0]

    def change_page_size(self, page_size: int, current: RawTable) -> RawTable:
        return current

    def next_page(self, current: RawTable) -> RawTable | None:
        self.index += 1
        return self.pages[self.index] if self.index < len(self.pages) else None


def test_a_row_repeated_on_the_next_page_is_kept_once() -> None:
    rows = synthetic_rows(NEWEST, 5)
    # A new measurement arrived between the two reads: page 2 starts with page 1's last row.
    table = ScriptedTable([raw_table(rows[:3]), raw_table(rows[2:])])

    reading = TableReader(table, _settings()).read(None)

    assert reading.pages_read == 2
    assert _local_times(reading.rows) == ["12:00", "11:30", "11:00", "10:30", "10:00"]


def test_columns_changing_between_pages_is_an_error() -> None:
    rows = synthetic_rows(NEWEST, 4)
    second = raw_table([row[:5] for row in rows[2:]], headers=HEADERS[:5])
    table = ScriptedTable([raw_table(rows[:2]), second])

    with pytest.raises(TableReadError, match="columns changed between pages"):
        TableReader(table, _settings()).read(None)


def test_malformed_rows_are_counted_over_all_pages() -> None:
    rows = synthetic_rows(NEWEST, 4)
    bad = ("not a time", "1", "2", "0", "100", "3,5")
    table = ScriptedTable([raw_table([rows[0], bad]), raw_table([rows[1], bad, rows[2]])])

    reading = TableReader(table, _settings()).read(None)

    assert reading.malformed_rows == 2
    assert len(reading.rows) == 3


def test_first_row_of_an_empty_page() -> None:
    assert RawTable(HEADERS, ()).first_row is None
    assert raw_table([("a",) * 6]).first_row == ("a",) * 6
