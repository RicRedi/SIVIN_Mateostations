"""Backward steps, overlaps and newest-first tables (SYNTHETIC rows, hand-computed UTC)."""

from __future__ import annotations

import pandas as pd
import pytest

from sivin.ingest.parsers.order import RowOrder, RowOrderAnalyser, SplitAtBackwardSteps
from sivin.ingest.parsers.portal import PortalCsvParser
from sivin.ingest.validation import Severity

from ..conftest import CsvWriter

# January: Europe/Prague is UTC+1.
LOCAL = ["2026-01-10 10:00:00", "2026-01-10 10:30:25", "2026-01-10 11:00:50", "2026-01-10 11:31:15"]


def rows(times: list[str]) -> list[list[str]]:
    return [[time, f"{k},5", "80"] for k, time in enumerate(times)]


def utc(*local: str) -> list[pd.Timestamp]:
    return [pd.Timestamp(time, tz="Europe/Prague").tz_convert("UTC") for time in local]


def naive(*local: str) -> pd.Series:
    return pd.Series(pd.to_datetime(list(local))).dt.as_unit("ns")


def test_clock_correction_keeps_every_row(write_csv: CsvWriter) -> None:
    # The device clock is set back 30 s just before the fourth sample (synthetic).
    times = [*LOCAL[:3], "2026-01-10 11:00:20", "2026-01-10 11:30:45"]
    result = PortalCsvParser().parse(write_csv(rows(times)))
    assert result.is_accepted
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == utc(
        "2026-01-10 10:00:00",
        "2026-01-10 10:30:25",
        "2026-01-10 11:00:20",
        "2026-01-10 11:00:50",
        "2026-01-10 11:30:45",
    )
    assert frame["temp_c"].tolist() == [0.5, 1.5, 3.5, 2.5, 4.5]
    (issue,) = result.report.issues
    assert (issue.rule, issue.severity, issue.row) == ("backward-steps", Severity.WARNING, 6)
    assert "1 backward step(s)" in issue.message
    assert "converted in 2 monotonic segments" in issue.message


def test_overlapping_exports_keep_one_copy(write_csv: CsvWriter) -> None:
    times = [*LOCAL, *LOCAL[2:]]
    result = PortalCsvParser().parse(write_csv(rows(times)))
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == utc(*LOCAL)
    assert frame["temp_c"].tolist() == [0.5, 1.5, 4.5, 5.5]  # last occurrence wins
    assert [issue.rule for issue in result.report.issues] == [
        "duplicate-timestamps",
        "backward-steps",
    ]
    assert result.report.issues[1].row == 7
    assert result.report.issues[0].message.startswith("2 row(s) repeat an earlier timestamp")


def test_clearly_newest_first_is_reversed(write_csv: CsvWriter) -> None:
    times = list(reversed(LOCAL))
    result = PortalCsvParser().parse(write_csv(rows(times)))
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == utc(*LOCAL)
    assert frame["temp_c"].tolist() == [3.5, 2.5, 1.5, 0.5]
    assert result.report.issues == ()


def test_mixed_order_is_not_reversed(write_csv: CsvWriter) -> None:
    times = [
        "2026-01-10 10:00:00",
        "2026-01-10 09:00:00",
        "2026-01-10 11:00:00",
        "2026-01-10 10:30:00",
    ]
    result = PortalCsvParser().parse(write_csv(rows(times)))
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == utc(
        "2026-01-10 09:00:00", "2026-01-10 10:00:00", "2026-01-10 10:30:00", "2026-01-10 11:00:00"
    )
    (issue,) = result.report.issues
    assert "at row(s) 4, 6; converted in 3 monotonic segments" in issue.message


def test_many_backward_steps_are_listed_briefly(write_csv: CsvWriter) -> None:
    times = [f"2026-01-10 {hour:02d}:00:00" for hour in range(12)]
    times = [time for pair in zip(times[1::2], times[::2], strict=True) for time in pair]
    result = PortalCsvParser().parse(write_csv(rows(times)))
    assert result.is_accepted
    assert len(result.series[0]) == 12
    (issue,) = result.report.issues
    assert issue.message.startswith("6 backward step(s)")
    assert "at row(s) 4, 6, 8, 10, 12, 14;" in issue.message


def test_analyser() -> None:
    analyser = RowOrderAnalyser("Europe/Prague", 0.9)
    assert not analyser.is_newest_first(naive())
    assert not analyser.is_newest_first(naive("2026-01-10 10:00"))
    assert analyser.is_newest_first(naive("2026-01-10 11:00", "2026-01-10 10:00"))
    # Ambiguous fall-back rows are not counted: only one ordinary step, forward.
    order = analyser.analyse(naive("2026-10-25 01:30", "2026-10-25 02:30", "2026-10-25 02:10"))
    assert not order.newest_first
    assert order.segments == (slice(0, 3),)
    assert analyser.ordinary(naive("2026-10-25 02:30", "2026-03-29 02:30")).tolist() == [
        False,
        False,
    ]


@pytest.mark.parametrize(
    ("local", "starts"),
    [
        ([], [0]),
        (["2026-01-10 10:00", "2026-01-10 10:00"], [0]),
        (["2026-01-10 10:00", "2026-01-10 09:59", "2026-01-10 11:00"], [0, 1]),
    ],
)
def test_split_at_backward_steps(local: list[str], starts: list[int]) -> None:
    series = naive(*local)
    segments = SplitAtBackwardSteps().segments(series, series.notna().to_numpy())
    assert [segment.start for segment in segments] == starts
    assert segments[-1].stop == len(local)
    assert RowOrder(False, segments).backward_steps.tolist() == starts[1:]
