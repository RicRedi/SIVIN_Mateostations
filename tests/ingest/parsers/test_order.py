"""Backward steps, overlaps and newest-first tables (SYNTHETIC rows, hand-computed UTC)."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sivin.core.ids import SensorId
from sivin.ingest.parsers.base import ParsedExport
from sivin.ingest.parsers.columns import ParserSettings
from sivin.ingest.parsers.order import RowOrder, RowOrderAnalyser, SplitAtBackwardSteps
from sivin.ingest.parsers.portal import PortalCsvParser
from sivin.ingest.parsers.sources import CellGrid
from sivin.ingest.parsers.tabular import SensorTable, TabularExportReader
from sivin.ingest.validation import ExportInspection, InputValidator, Severity

from ..conftest import CsvWriter, make_settings

N_OVERLAP_CASES = 400

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
    result = PortalCsvParser(make_settings()).parse(write_csv(rows(times)))
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
    result = PortalCsvParser(make_settings()).parse(write_csv(rows(times)))
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
    times = list(reversed([*LOCAL, "2026-01-10 12:01:40"]))
    result = PortalCsvParser(make_settings()).parse(write_csv(rows(times)))
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == utc(*LOCAL, "2026-01-10 12:01:40")
    assert frame["temp_c"].tolist() == [4.5, 3.5, 2.5, 1.5, 0.5]
    assert result.report.issues == ()


def test_short_backward_table_is_undecided(write_csv: CsvWriter) -> None:
    result = PortalCsvParser(make_settings()).parse(write_csv(rows(list(reversed(LOCAL)))))
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == utc(*LOCAL)
    assert [issue.rule for issue in result.report.issues] == ["row-order", "backward-steps"]


def test_mixed_order_is_not_reversed(write_csv: CsvWriter) -> None:
    times = [
        "2026-01-10 10:00:00",
        "2026-01-10 09:00:00",
        "2026-01-10 11:00:00",
        "2026-01-10 10:30:00",
        "2026-01-10 11:30:00",
    ]
    result = PortalCsvParser(make_settings()).parse(write_csv(rows(times)))
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == utc(
        "2026-01-10 09:00:00",
        "2026-01-10 10:00:00",
        "2026-01-10 10:30:00",
        "2026-01-10 11:00:00",
        "2026-01-10 11:30:00",
    )
    (issue,) = result.report.issues
    assert "at row(s) 4, 6; converted in 3 monotonic segments" in issue.message


def test_many_backward_steps_are_listed_briefly(write_csv: CsvWriter) -> None:
    times = [f"2026-01-10 {hour:02d}:00:00" for hour in range(24)]
    times = [time for pair in zip(times[1::2], times[::2], strict=True) for time in pair]
    result = PortalCsvParser(make_settings()).parse(write_csv(rows(times)))
    assert result.is_accepted
    assert len(result.series[0]) == 24
    (issue,) = result.report.issues
    assert issue.message.startswith("12 backward step(s)")
    assert "at row(s) 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, ...;" in issue.message


def test_clock_reset_drops_the_far_earlier_rows(write_csv: CsvWriter) -> None:
    # Synthetic: the clock jumps back 3 h (more than max_backward_step_s = 2 h) and recovers.
    times = [
        "2026-03-01 00:00:07",
        "2026-03-01 01:00:07",
        "2026-03-01 02:00:07",
        "2026-02-28 23:00:00",
        "2026-02-28 23:30:25",
        "2026-03-01 03:00:07",
    ]
    result = PortalCsvParser(make_settings()).parse(write_csv(rows(times)))
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == utc(
        "2026-03-01 00:00:07", "2026-03-01 01:00:07", "2026-03-01 02:00:07", "2026-03-01 03:00:07"
    )
    (issue,) = result.report.issues
    assert (issue.rule, issue.row, issue.severity) == ("large-backward-steps", 6, "warning")
    assert issue.message.startswith("2 row(s) are far earlier")


@pytest.mark.parametrize(
    ("times", "severity"),
    [
        (["2000-01-01 00:00:00", "2000-01-01 00:30:25"], Severity.WARNING),
        (["2099-01-01 00:00:00"], Severity.WARNING),
    ],
)
def test_implausible_timestamps_are_dropped(
    write_csv: CsvWriter, times: list[str], severity: Severity
) -> None:
    good = [f"2026-03-01 {hour:02d}:00:07" for hour in range(5)]
    result = PortalCsvParser(make_settings()).parse(write_csv(rows([*good[:3], *times, *good[3:]])))
    assert result.is_accepted
    assert result.series[0].frame["timestamp_utc"].tolist() == utc(*good)
    (issue,) = result.report.issues
    assert (issue.rule, issue.severity, issue.row) == ("timestamps-plausible", severity, 6)


def test_mostly_implausible_timestamps_reject_the_file(write_csv: CsvWriter) -> None:
    times = [f"2019-03-01 {hour:02d}:00:07" for hour in range(5)] + ["2026-03-01 00:00:07"]
    result = PortalCsvParser(make_settings()).parse(write_csv(rows(times)))
    assert result.report.rules(Severity.ERROR) == {"timestamps-plausible"}


def test_latest_plausible_time_follows_the_run_time(write_csv: CsvWriter) -> None:
    path = write_csv(rows(LOCAL))
    settings = ParserSettings()
    reader = TabularExportReader(settings, now_utc=datetime(2026, 1, 9, 9, 0, tzinfo=UTC))
    result = PortalCsvParser(settings, reader=reader).parse(path)
    # Latest plausible: 2026-01-10 09:00Z = 10:00 local; 3 rows later (min_error_rows = 3).
    assert result.report.rules(Severity.WARNING) == {"timestamps-plausible"}
    assert len(result.series[0]) == 1
    reader = TabularExportReader(settings, now_utc=datetime(2026, 1, 9, 10, 0, tzinfo=UTC))
    assert PortalCsvParser(settings, reader=reader).parse(path).is_accepted


def analyser() -> RowOrderAnalyser:
    return RowOrderAnalyser("Europe/Prague", 0.75, 4, 7200.0)


def test_analyser() -> None:
    assert not analyser().analyse(naive()).newest_first
    assert not analyser().analyse(naive("2026-01-10 10:00")).undecided
    order = analyser().analyse(naive("2026-01-10 11:00", "2026-01-10 10:00"))
    assert (order.newest_first, order.undecided) == (False, True)
    many = naive(*(f"2026-01-10 {hour:02d}:00" for hour in range(10, 4, -1)))
    assert analyser().analyse(many).newest_first
    # Steps inside the repeated hour are not counted; the one ordinary step goes forward.
    order = analyser().analyse(naive("2026-10-25 01:30", "2026-10-25 02:30", "2026-10-25 02:10"))
    assert (order.newest_first, order.undecided, order.segments) == (False, False, (slice(0, 3),))
    assert not order.is_repaired


@pytest.mark.parametrize(
    ("local", "starts"),
    [
        ([], [0]),
        (["2026-01-10 10:00", "2026-01-10 10:00"], [0]),
        (["2026-01-10 10:00", "2026-01-10 09:59", "2026-01-10 11:00"], [0, 1]),
        # ambiguous -> ordinary and ordinary -> ambiguous steps back are split points
        (
            ["2026-10-25 02:33", "2026-10-25 01:33", "2026-10-25 03:05", "2026-10-25 02:04"],
            [0, 1, 3],
        ),
        # two ambiguous rows of the same transition are not
        (["2026-10-25 02:33", "2026-10-25 02:04"], [0]),
    ],
)
def test_split_at_backward_steps(local: list[str], starts: list[int]) -> None:
    series = naive(*local)
    clock = analyser().wall_clock(series)
    segments = SplitAtBackwardSteps().segments(clock, clock.present)
    assert [segment.start for segment in segments] == starts
    assert segments[-1].stop == len(local)
    order = RowOrder(False, False, np.zeros(len(local), dtype=np.bool_), segments)
    assert order.backward_steps.tolist() == starts[1:]


# Repeated-hour cases from the review (synthetic). UTC grid: 2026-10-24 20:00:13Z + k * 1825 s.
GRID = pd.date_range("2026-10-24 20:00:13", periods=24, freq="1825s", tz="UTC")
GRID_LOCAL = GRID.tz_convert("Europe/Prague").tz_localize(None)


def grid_rows(indices: list[int]) -> list[list[str]]:
    return [[f"{GRID_LOCAL[i]:%Y-%m-%d %H:%M:%S}", f"{i},0", "50"] for i in indices]


def check_against_grid(result: ParsedExport, indices: list[int]) -> set[int]:
    """Assert every imported row sits at its true instant; return the indices lost."""
    assert result.is_accepted, result.report.summary()
    frame = result.series[0].frame
    truth = {GRID[i]: float(i) for i in indices}
    for instant, temp_c in zip(frame["timestamp_utc"], frame["temp_c"], strict=True):
        assert truth[instant] == temp_c, (instant, temp_c)
    return {i for i in indices if GRID[i] not in set(frame["timestamp_utc"])}


def test_overlap_ending_in_summer_half_is_not_misplaced(write_csv: CsvWriter) -> None:
    # Export 1 ends at 02:33:58 CEST, export 2 starts at 01:33:08 and also ends at 02:33:58.
    indices = [*range(10), 7, 8, 9]
    result = PortalCsvParser(make_settings()).parse(write_csv(grid_rows(indices)))
    lost = check_against_grid(result, indices)
    assert lost == {8, 9}  # no ordinary row after the repeated hour: dropped, not guessed
    assert "4 unresolved row(s) dropped" in result.report.issues[-1].message
    assert "backward-steps" in result.report.rules()


def test_newest_first_below_share_is_not_misplaced(write_csv: CsvWriter) -> None:
    indices = [*range(10), 0, 1][::-1]
    result = PortalCsvParser(make_settings()).parse(write_csv(grid_rows(indices)))
    check_against_grid(result, indices)


def test_overlap_before_fall_back_keeps_the_repeated_hour(write_csv: CsvWriter) -> None:
    indices = [*range(10), *range(7, 14)]
    result = PortalCsvParser(make_settings()).parse(write_csv(grid_rows(indices)))
    assert check_against_grid(result, indices) == set()


def overlap_cases() -> list[tuple[list[int], bool]]:
    """Two overlapping chunks of the 24-sample grid across the fall-back, both directions."""
    cases = []
    for a_end in range(1, 24):
        for b_start in range(a_end):
            for b_end in range(a_end, 25):
                indices = [*range(a_end), *range(b_start, b_end)]
                cases += [(indices, False), (indices[::-1], True)]
    return cases


def test_overlaps_never_misplace_a_row() -> None:
    """Seeded subset of the review's exhaustive check (5152 files) through the reader."""
    settings = make_settings()
    reader = TabularExportReader(settings)
    validator = InputValidator()
    sample = random.Random(1825).sample(overlap_cases(), N_OVERLAP_CASES)
    for indices, _ in sample:
        grid = CellGrid(
            "t", (("Datum a čas", "Teplota", "Vlhkost"), *map(tuple, grid_rows(indices)))
        )
        table = reader.inspect(SensorTable(grid, SensorId("77678271")))
        report = validator.validate(ExportInspection(Path("t.csv"), 1, tables=(table,)))
        series = reader.assemble(table, "t.csv")
        result = ParsedExport((series,), Path("t.csv"), report)
        check_against_grid(result, indices)
