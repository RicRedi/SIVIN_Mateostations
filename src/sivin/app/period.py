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
            If a text is not ISO 8601, is a local time in a daylight-saving gap or fold
            (ambiguous or nonexistent), or the end is before the start.
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
        return moment if moment.tzinfo is not None else _local(moment, zone, text)
    if end_of_day:
        midnight = datetime.combine(day + timedelta(days=1), datetime.min.time())
        return _local(midnight, zone, text) - _LAST_INSTANT
    return _local(datetime.combine(day, datetime.min.time()), zone, text)


def _local(naive: datetime, zone: ZoneInfo, text: str) -> datetime:
    """Attach ``zone``; a wall-clock time in a daylight-saving gap or fold is rejected."""
    earlier, later = naive.replace(tzinfo=zone), naive.replace(tzinfo=zone, fold=1)
    if earlier.utcoffset() != later.utcoffset():
        raise ValueError(
            f"{text!r} is ambiguous or does not exist in {zone.key} (daylight-saving change); "
            "give an explicit offset, e.g. '2026-10-25T02:30+01:00' or '...Z'"
        )
    return earlier
