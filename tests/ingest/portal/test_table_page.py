"""PortalTablePage on a fake browser table (SYNTHETIC rows, paging text of the real excerpt)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from tests.ingest.portal.conftest import FakeClock
from tests.ingest.portal.table_fakes import (
    FakeTableDriver,
    TableState,
    raw_table,
    real_excerpt,
    synthetic_rows,
)

from sivin.ingest.portal.errors import TableReadError
from sivin.ingest.portal.settings import PortalSettings, PortalTableSettings, PortalTimeouts
from sivin.ingest.portal.table import PagingStatus
from sivin.ingest.portal.table_page import PortalTablePage, _raw_table

NEWEST = datetime(2026, 11, 20, 12, 0, 0)


@pytest.fixture
def table_settings(tmp_path: Path) -> PortalSettings:
    """Short waits for the fake browser."""
    return PortalSettings(
        download_dir=tmp_path,
        timeouts=PortalTimeouts(element_wait_s=0.1, poll_interval_s=0.01),
        table=PortalTableSettings(rows_wait_s=0.1),
    )


def _page(settings: PortalSettings, state: TableState) -> tuple[PortalTablePage, FakeTableDriver]:
    driver = FakeTableDriver(settings, state)
    driver_any: Any = driver
    return PortalTablePage(driver_any, settings, FakeClock()), driver


def test_the_real_paging_text_is_understood(table_settings: PortalSettings) -> None:
    text = real_excerpt().paging_text
    assert text == "1 2 Zobrazeno 5000 z 9562 (5000)"

    match = re.search(table_settings.table.paging_text_pattern, text)

    assert match is not None
    assert match.groupdict() == {"shown": "5000", "total": "9562", "page_size": "5000"}


def test_rows_and_paging_are_read(table_settings: PortalSettings) -> None:
    state = TableState(synthetic_rows(NEWEST, 12), page_size=5)
    page, _ = _page(table_settings, state)

    first = page.wait_for_rows()

    assert len(first.rows) == 5
    assert first.rows[0][0] == "20.11.2026 12:00:00"
    assert page.paging() == PagingStatus(shown_rows=5, total_rows=12, page_size=5)


def test_an_empty_table_is_an_error(table_settings: PortalSettings) -> None:
    page, _ = _page(table_settings, TableState([]))

    with pytest.raises(TableReadError, match=r"No rows in the table .* within 0\.1 s"):
        page.wait_for_rows()


def test_a_stale_table_is_read_again(table_settings: PortalSettings) -> None:
    page, driver = _page(table_settings, TableState(synthetic_rows(NEWEST, 3)))
    driver.stale_tables = 1

    assert len(page.wait_for_rows().rows) == 3


class TestPageSize:
    def test_clicks_until_the_size_is_shown(self, table_settings: PortalSettings) -> None:
        state = TableState(synthetic_rows(NEWEST, 40), page_size=10)
        page, _ = _page(table_settings, state)

        current = page.change_page_size(30, page.wait_for_rows())

        # 10 → 15 → 20 → 30: three clicks.
        assert state.clicks == ["size", "size", "size"]
        assert state.page_size == 30
        assert len(current.rows) == 30

    def test_a_cycling_button_reaches_a_smaller_size(self, table_settings: PortalSettings) -> None:
        state = TableState(synthetic_rows(NEWEST, 600), page_size=5000)
        page, _ = _page(table_settings, state)

        current = page.change_page_size(500, page.wait_for_rows())

        # 5000 → 10 → 15 → 20 → 30 → 50 → 100 → 500: seven clicks.
        assert len(state.clicks) == 7
        assert len(current.rows) == 500

    def test_the_wanted_size_needs_no_click(self, table_settings: PortalSettings) -> None:
        state = TableState(synthetic_rows(NEWEST, 3), page_size=500)
        page, _ = _page(table_settings, state)
        first = page.wait_for_rows()

        assert page.change_page_size(500, first) is first
        assert state.clicks == []

    def test_a_click_without_effect_keeps_the_size(
        self, table_settings: PortalSettings, caplog: pytest.LogCaptureFixture
    ) -> None:
        state = TableState(synthetic_rows(NEWEST, 3), page_size=5000, size_button_works=False)
        page, _ = _page(table_settings, state)

        with caplog.at_level(logging.WARNING):
            page.change_page_size(500, page.wait_for_rows())

        assert state.clicks == ["size"]
        assert "The page size stayed at 5000 rows after a click" in caplog.text

    def test_a_size_the_button_never_shows(
        self, table_settings: PortalSettings, caplog: pytest.LogCaptureFixture
    ) -> None:
        state = TableState(synthetic_rows(NEWEST, 3), page_size=10)
        page, _ = _page(table_settings, state)

        with caplog.at_level(logging.WARNING):
            page.change_page_size(700, page.wait_for_rows())

        assert len(state.clicks) == table_settings.table.max_page_size_clicks
        assert "Page size 700 not reached after 9 click(s)" in caplog.text

    def test_no_button_or_no_paging(
        self, table_settings: PortalSettings, caplog: pytest.LogCaptureFixture
    ) -> None:
        no_button = TableState(synthetic_rows(NEWEST, 3), show_size_button=False)
        no_paging = TableState(synthetic_rows(NEWEST, 3), show_paging=False)

        with caplog.at_level(logging.WARNING):
            for state in (no_button, no_paging):
                page, _ = _page(table_settings, state)
                first = page.wait_for_rows()
                assert page.change_page_size(500, first) is first

        assert "No page-size button; reading 5000 rows per page." in caplog.text
        assert "No paging control found" in caplog.text

    def test_a_pattern_that_does_not_match_means_no_paging(
        self, table_settings: PortalSettings
    ) -> None:
        settings = table_settings.model_copy(
            update={
                "table": table_settings.table.model_copy(
                    update={
                        "paging_text_pattern": r"Shown (?P<shown>\d+) of (?P<total>\d+) "
                        r"\((?P<page_size>\d+)\)"
                    }
                )
            }
        )
        page, _ = _page(settings, TableState(synthetic_rows(NEWEST, 3)))

        assert page.paging() is None


class TestNextPage:
    def test_opens_the_older_page_until_the_last(self, table_settings: PortalSettings) -> None:
        state = TableState(synthetic_rows(NEWEST, 12), page_size=5)
        page, _ = _page(table_settings, state)

        first = page.wait_for_rows()
        second = page.next_page(first)
        assert second is not None
        third = page.next_page(second)
        assert third is not None

        assert second.rows[0][0] == "20.11.2026 9:30:00"
        assert len(third.rows) == 2
        assert page.next_page(third) is None  # the button is disabled on the last page

    def test_a_page_that_does_not_load_is_an_error(self, table_settings: PortalSettings) -> None:
        state = TableState(synthetic_rows(NEWEST, 12), page_size=5, next_loads=False)
        page, _ = _page(table_settings, state)

        with pytest.raises(TableReadError, match=r"next table page did not load.*page size 5"):
            page.next_page(page.wait_for_rows())

    def test_without_paging_there_is_no_next_page(self, table_settings: PortalSettings) -> None:
        state = TableState(synthetic_rows(NEWEST, 12), page_size=5, show_paging=False)
        page, _ = _page(table_settings, state)

        assert page.next_page(page.wait_for_rows()) is None


class TestScriptResult:
    def test_the_real_excerpt_shape_is_accepted(self) -> None:
        excerpt = real_excerpt()

        table = _raw_table({"headers": excerpt.headers, "rows": excerpt.rows})

        assert table == raw_table(excerpt.rows, excerpt.headers)

    @pytest.mark.parametrize(
        ("result", "message"),
        [
            (None, "of type NoneType"),
            ({"headers": "abc", "rows": []}, "no header and row texts"),
            ({"headers": ["a"], "rows": "abc"}, "no header and row texts"),
            ({"headers": ["a"]}, "no header and row texts"),
            ({"headers": ["a"], "rows": [["x", 1]]}, "a row is not a list of texts"),
        ],
    )
    def test_unexpected_results_are_errors(self, result: object, message: str) -> None:
        with pytest.raises(TableReadError, match=message):
            _raw_table(result)

    def test_the_driver_result_is_checked(self, table_settings: PortalSettings) -> None:
        page, driver = _page(table_settings, TableState(synthetic_rows(NEWEST, 3)))
        driver.script_result = ["not", "a", "mapping"]

        with pytest.raises(TableReadError, match="of type list"):
            page.wait_for_rows()
