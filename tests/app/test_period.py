"""TimeBounds of --from/--to."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sivin.app.period import TimeBounds

PRAGUE = "Europe/Prague"


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def test_dates_cover_whole_local_days() -> None:
    bounds = TimeBounds.parse("2026-06-01", "2026-06-02", PRAGUE)
    assert bounds.start is not None
    assert bounds.end is not None
    # CEST = UTC+2: 2026-06-01 00:00 local = 2026-05-31 22:00Z; the end is the last
    # microsecond of 2026-06-02 local = 2026-06-02 21:59:59.999999Z.
    assert bounds.start.astimezone(UTC) == utc("2026-05-31T22:00:00+00:00")
    assert bounds.end.astimezone(UTC) == utc("2026-06-02T21:59:59.999999+00:00")


def test_local_and_explicit_times() -> None:
    bounds = TimeBounds.parse("2026-01-10T12:00", "2026-01-10T12:00Z", PRAGUE)
    assert bounds.start is not None
    assert bounds.start.astimezone(UTC) == utc("2026-01-10T11:00:00+00:00")  # CET
    assert bounds.end == utc("2026-01-10T12:00:00+00:00")


def test_unbounded_and_invalid() -> None:
    assert TimeBounds.parse(None, None, PRAGUE) == TimeBounds()
    with pytest.raises(ValueError, match="before the start"):
        TimeBounds.parse("2026-06-02", "2026-06-01", PRAGUE)
    with pytest.raises(ValueError, match="Invalid isoformat"):
        TimeBounds.parse("June", None, PRAGUE)


@pytest.mark.parametrize("text", ["2026-10-25T02:30", "2026-03-29T02:30"])
def test_local_times_in_a_daylight_saving_change_need_an_offset(text: str) -> None:
    # 2026-10-25 02:30 occurs twice (fold), 2026-03-29 02:30 does not exist (gap) in Prague.
    with pytest.raises(ValueError, match="give an explicit offset"):
        TimeBounds.parse(text, None, PRAGUE)
    explicit = TimeBounds.parse(f"{text}+01:00", None, PRAGUE)
    assert explicit.start is not None
