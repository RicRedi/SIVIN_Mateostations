"""Published index entries: no value or class without data, daily risk block (synthetic)."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
from tests.site.helpers import SENSOR

from sivin.analytics.base import DailyLevels, IndexResult
from sivin.site.indices import daily_block, index_entry


def result(value: float | None, coverage: float, complete: bool) -> IndexResult:
    return IndexResult("powdery_mildew_gt", SENSOR, 2026, value, "points", coverage, complete,
                       classification="low", estimated=True)  # fmt: skip


def test_zero_coverage_publishes_no_value_and_no_class() -> None:
    assert index_entry(result(0.0, 0.0, False)) == {
        "value": None, "unit": "points", "coverage": 0.0, "complete": False, "class": None,
        "estimated": True, "status": "no_data", "detail": "no data",
    }  # fmt: skip


def test_incomplete_result_keeps_its_value_but_no_class() -> None:
    entry = index_entry(result(12.346, 0.4, False))
    assert (entry["value"], entry["class"], entry["status"]) == (12.35, None, "ok")
    assert "detail" not in entry


def test_complete_result_has_its_class() -> None:
    entry = index_entry(result(40.0, 0.95, True))
    assert (entry["value"], entry["coverage"], entry["class"]) == (40.0, 0.95, "low")


def risk_result(coverage: float) -> IndexResult:
    days = [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)]
    daily = pd.Series([0.0, 70.0, math.nan], index=days)
    levels = DailyLevels(
        ("low", "moderate", "high"),
        date(2026, 4, 1),
        date(2026, 10, 31),
        pd.Series(["low", "high", None], index=days, dtype=object),
    )
    return IndexResult("powdery_mildew_gt", SENSOR, 2026, 70.0, "points", coverage, False,
                       classification="high", daily=daily, daily_levels=levels)  # fmt: skip


def test_daily_risk_block_follows_the_levels() -> None:
    entry = index_entry(risk_result(0.4))
    assert entry["class"] is None  # incomplete season: no seasonal class
    assert entry["daily"] == {
        "levels": ["low", "moderate", "high"],
        "start": "2026-04-01",
        "end": "2026-10-31",
        "date": ["2026-06-01", "2026-06-02", "2026-06-03"],
        "value": [0.0, 70.0, None],
        "level": ["low", "high", None],
    }


def test_day_without_level_publishes_no_value() -> None:
    days = [date(2026, 6, 1)]
    levels = DailyLevels(("low",), date(2026, 6, 1), date(2026, 6, 1),
                         pd.Series([None], index=days, dtype=object))  # fmt: skip
    block = daily_block(levels, pd.Series([5.0], index=days))
    assert (block["value"], block["level"]) == ([None], [None])
    assert daily_block(levels, None)["value"] == [None]


def test_no_data_entry_has_no_daily_block() -> None:
    assert "daily" not in index_entry(risk_result(0.0))
