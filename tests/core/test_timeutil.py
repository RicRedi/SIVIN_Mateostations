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


def test_fall_back_without_repetition_reads_standard_time(
    caplog: pytest.LogCaptureFixture,
) -> None:
    local = naive("2026-10-25 01:30", "2026-10-25 02:30", "2026-10-25 03:00")
    with caplog.at_level(logging.WARNING):
        result = LocalTimeConverter(PRAGUE).to_utc(local)
    # 02:30 read as CET (UTC+1) -> 01:30 UTC
    assert result.timestamps_utc.tolist() == utc(
        "2026-10-24 23:30", "2026-10-25 01:30", "2026-10-25 02:00"
    )
    assert result.suspect.tolist() == [False, True, False]
    assert "Cannot infer 1 ambiguous" in caplog.text


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
