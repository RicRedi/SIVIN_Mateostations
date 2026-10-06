"""Published index entries: no value or class without data (synthetic results)."""

from __future__ import annotations

from tests.site.helpers import SENSOR

from sivin.analytics.base import IndexResult
from sivin.site.indices import index_entry


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
