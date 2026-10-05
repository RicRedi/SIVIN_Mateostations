"""Local wall-clock times of the off-site log: parsing to UTC and formatting for the owner.

Times in the log are local (Europe/Prague by default) or ISO 8601 with an explicit offset.
A local time that is ambiguous or does not exist because of a daylight-saving change is
rejected with a request for an explicit offset (:class:`LocalTimeReader`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    ValidationInfo,
)

from sivin.core.defaults import DEFAULT_TIMEZONE

TIMEZONE_CONTEXT_KEY: Final = "timezone"
"""Key of the pydantic validation context that names the IANA zone of local times."""

TIME_TEXT_PATTERN: Final = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?"
    r"(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})?$"
)
"""Accepted text of ``from`` / ``to``: local ``YYYY-MM-DD HH:MM[:SS]`` or the same with an offset.

Without ``offset`` the time is local wall-clock time of the log's zone; with ``Z`` or
``±HH:MM`` it is an absolute instant.
"""

_TIME_TEXT_REGEX: Final = re.compile(TIME_TEXT_PATTERN)

JSON_TIME_PATTERN: Final = TIME_TEXT_PATTERN.replace("?P<offset>", "")
""":data:`TIME_TEXT_PATTERN` without the Python-only named group (for the JSON Schema)."""


class LocalTimeReader:
    """Read the time values of the log as UTC instants.

    Parameters
    ----------
    timezone : str
        IANA zone of local wall-clock times, e.g. ``"Europe/Prague"``.

    Raises
    ------
    ValueError
        If the zone is unknown.
    """

    __slots__ = ("_zone",)

    def __init__(self, timezone: str) -> None:
        try:
            self._zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA time zone {timezone!r}") from error

    @property
    def timezone(self) -> str:
        """The IANA zone name."""
        return self._zone.key

    def read(self, value: object) -> datetime:
        """Convert one ``from`` / ``to`` value to an aware UTC datetime.

        Parameters
        ----------
        value : str or datetime.datetime
            Text matching :data:`TIME_TEXT_PATTERN`, or a datetime as produced by the YAML
            parser for an unquoted ``2025-12-17 12:00:00`` (naive = local wall-clock time).

        Returns
        -------
        datetime.datetime
            The instant in UTC.

        Raises
        ------
        ValueError
            If the value is not a time, has no time of day, or is a local time that is
            ambiguous or does not exist in the zone (daylight-saving change).
        """
        if isinstance(value, datetime):
            instant = value
        elif isinstance(value, date):
            raise ValueError(
                f"{value.isoformat()!r} has no time of day; write 'YYYY-MM-DD HH:MM', "
                f"e.g. '{value.isoformat()} 12:00'"
            )
        elif isinstance(value, str):
            instant = self._parse_text(value)
        else:
            raise ValueError(f"expected a time as text, got {type(value).__name__}")
        if instant.tzinfo is None:
            return self._local_to_utc(instant)
        return instant.astimezone(UTC)

    @staticmethod
    def _parse_text(text: str) -> datetime:
        if _TIME_TEXT_REGEX.fullmatch(text.strip()) is None:
            raise ValueError(
                f"time {text!r} must be local 'YYYY-MM-DD HH:MM' or ISO 8601 with an offset, "
                "e.g. '2025-12-17 12:00', '2025-12-17T12:00+01:00' or '2025-12-17T11:00Z'"
            )
        try:
            return datetime.fromisoformat(text.strip())
        except ValueError as error:
            raise ValueError(
                f"time {text!r} is not a valid calendar date and time (month 01-12, day of the "
                "month, hour 00-23, minute 00-59)"
            ) from error

    def _local_to_utc(self, wall_clock: datetime) -> datetime:
        earlier = wall_clock.replace(tzinfo=self._zone, fold=0)
        later = wall_clock.replace(tzinfo=self._zone, fold=1)
        if earlier.utcoffset() == later.utcoffset():
            return earlier.astimezone(UTC)
        text = wall_clock.isoformat(sep=" ", timespec="minutes")
        iso = text.replace(" ", "T")
        round_trip = earlier.astimezone(UTC).astimezone(self._zone).replace(tzinfo=None)
        if round_trip == wall_clock:
            raise ValueError(
                f"local time {text!r} is ambiguous in {self.timezone} (clocks fall back, the "
                f"hour occurs twice); give an explicit offset: '{iso}{offset_text(earlier)}' "
                f"for the first one (summer time) or '{iso}{offset_text(later)}' for the "
                "second one (winter time)"
            )
        raise ValueError(
            f"local time {text!r} does not exist in {self.timezone} (clocks spring forward, "
            f"the hour is skipped); write a time after the change, or the time on the clock "
            f"before the change with its offset: '{iso}{offset_text(earlier)}'"
        )


def offset_text(instant: datetime) -> str:
    """Format the UTC offset of an aware datetime as ``±HH:MM``."""
    text = instant.strftime("%z")
    return f"{text[:3]}:{text[3:]}"


def format_local(instant: datetime, timezone: str) -> str:
    """Format an instant for the owner: local time of ``timezone`` with UTC in brackets.

    Parameters
    ----------
    instant : datetime.datetime
        Timezone-aware instant.
    timezone : str
        IANA zone, e.g. ``"Europe/Prague"``.

    Returns
    -------
    str
        E.g. ``"2025-12-17 12:00 CET (11:00 UTC)"``; the UTC date is repeated when it differs.
    """
    local = instant.astimezone(ZoneInfo(timezone))
    utc = instant.astimezone(UTC)
    utc_text = f"{utc:%H:%M}" if utc.date() == local.date() else f"{utc:%Y-%m-%d %H:%M}"
    return f"{local:%Y-%m-%d %H:%M} {local.tzname()} ({utc_text} UTC)"


def format_local_iso(instant: datetime, timezone: str) -> str:
    """Format an instant as ready-to-paste log text: local ISO 8601 with its offset.

    Parameters
    ----------
    instant : datetime.datetime
        Timezone-aware instant.
    timezone : str
        IANA zone.

    Returns
    -------
    str
        E.g. ``"2026-04-14T01:55+02:00"``; unambiguous also in the repeated autumn hour.
    """
    local = instant.astimezone(ZoneInfo(timezone))
    return f"{local:%Y-%m-%dT%H:%M}{offset_text(local)}"


def timezone_of(info: ValidationInfo) -> str:
    """Return the zone named in the validation context, else :data:`DEFAULT_TIMEZONE`."""
    context = info.context
    if isinstance(context, Mapping):
        zone = context.get(TIMEZONE_CONTEXT_KEY, DEFAULT_TIMEZONE)
        if isinstance(zone, str):
            return zone
    return DEFAULT_TIMEZONE
