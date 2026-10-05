"""Time bounds given on the command line (``--from``/``--to``), in the display time zone."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Self
from zoneinfo import ZoneInfo

_LAST_INSTANT: Final = timedelta(microseconds=1)
"""Subtracted from the next local midnight to make a date-only end inclusive."""


@dataclass(frozen=True, slots=True)
class TimeBounds:
    """Inclusive, timezone-aware bounds of a time range; ``None`` = unbounded.

    Attributes
    ----------
    start : datetime.datetime or None
        First instant (aware).
    end : datetime.datetime or None
        Last instant (aware).

    Raises
    ------
    ValueError
        If ``end`` is before ``start``.
    """

    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(f"the end {self.end} is before the start {self.start}")

    @classmethod
    def parse(cls, start: str | None, end: str | None, timezone: str) -> Self:
        """Read ISO 8601 bounds; values without an offset are local time of ``timezone``.

        ``2026-06-01`` as start means local midnight of that day, as end the last instant of
        that day (the day is included). ``2026-06-01T12:00`` is local wall-clock time,
        ``2026-06-01T10:00Z`` or ``...+02:00`` an explicit instant.

        Parameters
        ----------
        start, end : str or None
            The texts of ``--from`` and ``--to``.
        timezone : str
            IANA zone of local values (``time.display_timezone``).

        Returns
        -------
        TimeBounds
            Aware bounds.

        Raises
        ------
        ValueError
            If a text is not ISO 8601 or the end is before the start.
        """
        zone = ZoneInfo(timezone)
        return cls(_instant(start, zone, end_of_day=False), _instant(end, zone, end_of_day=True))


def _instant(text: str | None, zone: ZoneInfo, *, end_of_day: bool) -> datetime | None:
    if text is None:
        return None
    try:
        day = date.fromisoformat(text)
    except ValueError:
        moment = datetime.fromisoformat(text)
        return moment if moment.tzinfo is not None else moment.replace(tzinfo=zone)
    if end_of_day:
        return datetime.combine(day + timedelta(days=1), datetime.min.time(), zone) - _LAST_INSTANT
    return datetime.combine(day, datetime.min.time(), zone)
