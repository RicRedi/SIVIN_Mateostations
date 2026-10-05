"""Tests of LocalTimeConverter on the 2026 Europe/Prague daylight-saving transitions."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from sivin.core.timeutil import LocalTimeConverter

PRAGUE = "Europe/Prague"


def naive(*local: str) -> pd.Series:
    return pd.Series(pd.to_datetime(list(local)), name="local")


def utc(*values: str) -> list[pd.Timestamp]:
    return [pd.Timestamp(value, tz="UTC") for value in values]


def test_2026_transition_instants_from_zoneinfo() -> None:
    """Independent check of the dates the other tests rely on."""
    zone = ZoneInfo(PRAGUE)
    transitions = []
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    previous = instant.astimezone(zone).utcoffset()
    while instant.year == 2026:
        offset = instant.astimezone(zone).utcoffset()
        if offset != previous:
            transitions.append(instant)
            previous = offset
        instant += timedelta(minutes=30)
    assert transitions == [
        datetime(2026, 3, 29, 1, 0, tzinfo=UTC),  # 02:00 CET -> 03:00 CEST
        datetime(2026, 10, 25, 1, 0, tzinfo=UTC),  # 03:00 CEST -> 02:00 CET
    ]


def test_unknown_zone_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown IANA time zone"):
        LocalTimeConverter("Europe/Brno")


def test_plain_winter_and_summer_times() -> None:
    result = LocalTimeConverter(PRAGUE).to_utc(naive("2026-01-15 12:00", "2026-07-15 12:00"))
    assert result.timestamps_utc.tolist() == utc("2026-01-15 11:00", "2026-07-15 10:00")
    assert result.timestamps_utc.dtype == pd.DatetimeTZDtype("ns", "UTC")
    assert result.timestamps_utc.name == "local"
    assert result.suspect.tolist() == [False, False]


def test_fall_back_inferred_from_order() -> None:
    local = naive(
        "2026-10-25 01:30",
        "2026-10-25 02:00",  # CEST
        "2026-10-25 02:30",  # CEST
        "2026-10-25 02:00",  # CET (repeated hour)
        "2026-10-25 02:30",  # CET
        "2026-10-25 03:00",
    )
    result = LocalTimeConverter(PRAGUE).to_utc(local)
    assert result.timestamps_utc.tolist() == utc(
        "2026-10-24 23:30",
        "2026-10-25 00:00",
        "2026-10-25 00:30",
        "2026-10-25 01:00",
        "2026-10-25 01:30",
        "2026-10-25 02:00",
    )
    assert result.suspect.tolist() == [False, True, True, True, True, False]


def test_fall_back_single_sample_guessed_by_spacing_is_unresolved() -> None:
    # 02:30 between 01:30 CEST (23:30 UTC) and 03:00 CET (02:00 UTC):
    # read as CEST -> 00:30 UTC, steps 60 and 90 min; as CET -> 01:30 UTC, steps 120 and 30 min.
    # The larger minimum step (60 min) wins: summer time, but only as a guess (no clock jump).
    local = naive("2026-10-25 01:30", "2026-10-25 02:30", "2026-10-25 03:00")
    result = LocalTimeConverter(PRAGUE).to_utc(local)
    assert result.timestamps_utc.tolist() == utc(
        "2026-10-24 23:30", "2026-10-25 00:30", "2026-10-25 02:00"
    )
    assert result.suspect.tolist() == [False, True, False]
    assert result.unresolved.tolist() == [False, True, False]


def test_fall_back_tie_reads_standard_time_and_is_unresolved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 02:30 between 01:30 CEST (23:30 UTC) and 03:30 CET (02:30 UTC): both readings give
    # steps of 60 and 120 min, so the sample order cannot decide.
    local = naive("2026-10-25 01:30", "2026-10-25 02:30", "2026-10-25 03:30")
    with caplog.at_level(logging.WARNING):
        result = LocalTimeConverter(PRAGUE).to_utc(local)
    assert result.timestamps_utc.tolist() == utc(
        "2026-10-24 23:30", "2026-10-25 01:30", "2026-10-25 02:30"
    )
    assert result.suspect.tolist() == [False, True, False]
    assert result.unresolved.tolist() == [False, True, False]
    assert "no single clock jump" in caplog.text


def test_fall_back_missing_sample_in_repeated_hour() -> None:
    # 1825 s sampling; the sample at 02:39:05 CEST (00:39:05 UTC) is missing, so the wall
    # clock shows no backward jump: 02:08:40, 02:09:30, 02:39:55.
    local = naive(
        "2026-10-25 01:38:15",  # CEST
        "2026-10-25 02:08:40",  # CEST
        "2026-10-25 02:09:30",  # CET
        "2026-10-25 02:39:55",  # CET
        "2026-10-25 03:10:20",  # CET
    )
    result = LocalTimeConverter(PRAGUE).to_utc(local)
    assert result.timestamps_utc.tolist() == utc(
        "2026-10-24 23:38:15",
        "2026-10-25 00:08:40",
        "2026-10-25 01:09:30",
        "2026-10-25 01:39:55",
        "2026-10-25 02:10:20",
    )
    # Correct here, but found by the spacing guess, not by a clock jump.
    assert result.unresolved.tolist() == [False, True, True, True, False]


def test_fall_back_nat_inside_repeated_hour() -> None:
    local = naive(
        "2026-10-25 01:30",
        "2026-10-25 02:00",  # CEST
        None,  # would be 02:30 CEST
        "2026-10-25 02:00",  # CET
        "2026-10-25 02:30",  # CET
        "2026-10-25 03:00",
    )
    result = LocalTimeConverter(PRAGUE).to_utc(local)
    stamps = result.timestamps_utc.tolist()
    assert stamps[:2] == utc("2026-10-24 23:30", "2026-10-25 00:00")
    assert pd.isna(stamps[2])
    assert stamps[3:] == utc("2026-10-25 01:00", "2026-10-25 01:30", "2026-10-25 02:00")
    assert result.suspect.tolist() == [False, True, False, True, True, False]


def test_fall_back_each_year_resolved_independently() -> None:
    # 2025: complete repeated hour (2025-10-26), 2026: a single unresolvable sample.
    local = naive(
        "2025-10-26 01:30",
        "2025-10-26 02:00",  # CEST
        "2025-10-26 02:30",  # CEST
        "2025-10-26 02:00",  # CET
        "2025-10-26 02:30",  # CET
        "2025-10-26 03:00",
        "2026-10-25 01:30",
        "2026-10-25 02:30",  # ambiguous, tie -> standard time, unresolved
        "2026-10-25 03:30",
    )
    result = LocalTimeConverter(PRAGUE).to_utc(local)
    assert result.timestamps_utc.tolist() == utc(
        "2025-10-25 23:30",
        "2025-10-26 00:00",
        "2025-10-26 00:30",
        "2025-10-26 01:00",
        "2025-10-26 01:30",
        "2025-10-26 02:00",
        "2026-10-24 23:30",
        "2026-10-25 01:30",
        "2026-10-25 02:30",
    )
    assert result.unresolved.tolist() == [False] * 7 + [True, False]
    assert result.timestamps_utc.is_unique


def test_fall_back_several_jumps_are_unresolved() -> None:
    local = naive("2026-10-25 02:30", "2026-10-25 02:00", "2026-10-25 02:40", "2026-10-25 02:10")
    result = LocalTimeConverter(PRAGUE).to_utc(local)
    assert result.unresolved.all()
    assert result.timestamps_utc.tolist() == utc(
        "2026-10-25 01:30", "2026-10-25 01:00", "2026-10-25 01:40", "2026-10-25 01:10"
    )


def test_spring_forward_collisions_become_nat(caplog: pytest.LogCaptureFixture) -> None:
    # 02:00 and 02:15 do not exist; shifted by the gap they equal 03:00 and 03:15 CEST.
    local = naive("2026-03-29 02:00", "2026-03-29 02:15", "2026-03-29 03:00", "2026-03-29 03:15")
    local.index = [5, 5, 6, 7]  # duplicate labels must not matter
    with caplog.at_level(logging.WARNING):
        result = LocalTimeConverter(PRAGUE).to_utc(local)
    stamps = result.timestamps_utc.tolist()
    assert pd.isna(stamps[0])
    assert pd.isna(stamps[1])
    assert stamps[2:] == utc("2026-03-29 01:00", "2026-03-29 01:15")
    assert result.suspect.tolist() == [True, True, False, False]
    assert result.unresolved.tolist() == [True, True, False, False]
    assert result.timestamps_utc.index.tolist() == [5, 5, 6, 7]
    assert "returned as NaT" in caplog.text


def test_spring_forward_nonexistent_times_are_shifted_and_suspect() -> None:
    local = naive("2026-03-29 01:30", "2026-03-29 02:15", "2026-03-29 03:30")
    result = LocalTimeConverter(PRAGUE).to_utc(local)
    # 02:15 does not exist; read with the CET offset (UTC+1) = shifted forward to 03:15 CEST
    assert result.timestamps_utc.tolist() == utc(
        "2026-03-29 00:30", "2026-03-29 01:15", "2026-03-29 01:30"
    )
    assert result.suspect.tolist() == [False, True, False]


def test_missing_timestamps_stay_missing() -> None:
    result = LocalTimeConverter(PRAGUE).to_utc(naive("2026-01-15 12:00", None))
    assert result.timestamps_utc.iloc[0] == pd.Timestamp("2026-01-15 11:00", tz="UTC")
    assert pd.isna(result.timestamps_utc.iloc[1])
    assert result.suspect.tolist() == [False, False]


def test_to_utc_rejects_aware_or_non_datetime_input() -> None:
    converter = LocalTimeConverter(PRAGUE)
    with pytest.raises(TypeError, match="naive datetime64"):
        converter.to_utc(pd.Series(pd.to_datetime(["2026-01-01T00:00Z"])))
    with pytest.raises(TypeError, match="naive datetime64"):
        converter.to_utc(pd.Series(["2026-01-01 00:00"]))


def test_local_dates() -> None:
    converter = LocalTimeConverter(PRAGUE)
    stamps = pd.Series(utc("2026-01-14 22:59", "2026-01-14 23:00", "2026-07-14 22:00"))
    assert converter.local_dates(stamps).tolist() == [
        date(2026, 1, 14),
        date(2026, 1, 15),
        date(2026, 7, 15),
    ]
    with pytest.raises(TypeError, match="timezone-aware"):
        converter.local_dates(pd.Series(pd.to_datetime(["2026-01-01"])))


@pytest.mark.parametrize(
    ("day", "start", "end", "length_s"),
    [
        (date(2026, 1, 15), "2026-01-14 23:00", "2026-01-15 23:00", 86_400.0),
        (date(2026, 3, 29), "2026-03-28 23:00", "2026-03-29 22:00", 82_800.0),
        (date(2026, 10, 25), "2026-10-24 22:00", "2026-10-25 23:00", 90_000.0),
    ],
)
def test_day_bounds_and_length(day: date, start: str, end: str, length_s: float) -> None:
    converter = LocalTimeConverter(PRAGUE)
    assert converter.day_bounds_utc(day) == (
        pd.Timestamp(start, tz="UTC"),
        pd.Timestamp(end, tz="UTC"),
    )
    assert converter.day_length_s(day) == length_s
    assert converter.timezone == PRAGUE


@pytest.mark.parametrize(
    ("local", "expected_unresolved"),
    [
        # A lone ambiguous sample without neighbours: no evidence either way.
        (("2026-10-25 02:30",), [True]),
        # The following sample is earlier than both readings (unsorted input).
        (("2026-10-25 02:30", "2026-10-25 01:00"), [True, False]),
        # A nonexistent spring sample is no usable neighbour.
        (("2026-03-29 02:30", "2026-10-25 02:30"), [False, True]),
        # NaT before the group is skipped: same as test_fall_back_single_sample_resolved_by_spacing.
        (
            ("2026-10-25 01:30", None, "2026-10-25 02:30", "2026-10-25 03:00"),
            [False, False, True, False],
        ),
    ],
)
def test_fall_back_without_jump_edge_cases(
    local: tuple[str | None, ...], expected_unresolved: list[bool]
) -> None:
    result = LocalTimeConverter(PRAGUE).to_utc(naive(*local))
    assert result.unresolved.tolist() == expected_unresolved


def test_spacing_guess_that_is_wrong_is_flagged() -> None:
    """Reviewer case: 1825 s sampling, two samples missing around the repeated hour.

    True instants: 01:58:20 CEST = 23:58:20 UTC, 02:29:35 CET = 01:29:35 UTC,
    03:00:00 CET = 02:00:00 UTC. Without a clock jump the spacing guess picks summer time
    (00:29:35 UTC), which is wrong; it must not be reported as resolved.
    """
    local = naive("2026-10-25 01:58:20", "2026-10-25 02:29:35", "2026-10-25 03:00:00")
    result = LocalTimeConverter(PRAGUE).to_utc(local)
    assert result.suspect.tolist() == [False, True, False]
    assert result.unresolved.tolist() == [False, True, False]
    assert result.timestamps_utc.iloc[0] == pd.Timestamp("2026-10-24 23:58:20", tz="UTC")
    assert result.timestamps_utc.iloc[2] == pd.Timestamp("2026-10-25 02:00:00", tz="UTC")


@pytest.mark.parametrize(
    "local",
    [
        ("2026-10-25 03:30", "2026-10-25 03:00", "2026-10-25 02:30", "2026-10-25 01:30"),
        ("2026-01-15 12:30", "2026-01-15 12:00"),
    ],
)
def test_newest_first_input_is_rejected(local: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="oldest first"):
        LocalTimeConverter(PRAGUE).to_utc(naive(*local))


def test_equal_regular_rows_are_not_an_order_error() -> None:
    result = LocalTimeConverter(PRAGUE).to_utc(naive("2026-01-15 12:00", "2026-01-15 12:00"))
    assert result.timestamps_utc.tolist() == utc("2026-01-15 11:00", "2026-01-15 11:00")
    assert not result.suspect.any()


def test_duplicate_row_in_repeated_hour_is_not_a_jump(caplog: pytest.LogCaptureFixture) -> None:
    local = naive(
        "2026-10-25 01:30",
        "2026-10-25 02:00",  # CEST
        "2026-10-25 02:30",  # CEST
        "2026-10-25 02:30",  # duplicated export row
        "2026-10-25 02:00",  # CET: the single jump
        "2026-10-25 02:30",  # CET
        "2026-10-25 03:00",
    )
    with caplog.at_level(logging.WARNING):
        result = LocalTimeConverter(PRAGUE).to_utc(local)
    stamps = result.timestamps_utc.tolist()
    assert stamps[:2] == utc("2026-10-24 23:30", "2026-10-25 00:00")
    assert pd.isna(stamps[2])
    assert pd.isna(stamps[3])
    assert stamps[4:] == utc("2026-10-25 01:00", "2026-10-25 01:30", "2026-10-25 02:00")
    assert result.unresolved.tolist() == [False, False, True, True, False, False, False]
    assert "returned as NaT" in caplog.text
