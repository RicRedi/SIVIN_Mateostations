"""Periods of the year given by month and day, e.g. the vegetation season."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Final, Self

LEAP_DAY: Final = (2, 29)
"""February 29 as ``(month, day)``; in common years it is read as February 28."""

_ANY_LEAP_YEAR: Final = 2024
"""A leap year used only to validate a month-day combination (allows February 29)."""


@dataclass(frozen=True, slots=True, order=True)
class MonthDay:
    """A day of the year without a year, e.g. April 1.

    Parameters
    ----------
    month : int
        Month, 1-12.
    day : int
        Day of the month, 1-31 (February 29 is allowed, see :meth:`in_year`).

    Raises
    ------
    ValueError
        If the combination does not exist in a leap year.
    """

    month: int
    day: int

    def __post_init__(self) -> None:
        try:
            date(_ANY_LEAP_YEAR, self.month, self.day)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid month-day {self.month}-{self.day}: {error}") from error

    def in_year(self, year: int) -> date:
        """Return the date of this month-day in a given year.

        Parameters
        ----------
        year : int
            Calendar year.

        Returns
        -------
        datetime.date
            The date; February 29 becomes February 28 in a common year.
        """
        if (self.month, self.day) == LEAP_DAY and not calendar.isleap(year):
            return date(year, self.month, self.day - 1)
        return date(year, self.month, self.day)

    def __str__(self) -> str:
        return f"{self.month:02d}-{self.day:02d}"


@dataclass(frozen=True, slots=True)
class Season:
    """An inclusive period of the year from ``start`` to ``end``, e.g. April 1 - October 31.

    Periods crossing the new year are not supported (no index of the project needs them).

    Parameters
    ----------
    start : MonthDay
        First day of the period (inclusive).
    end : MonthDay
        Last day of the period (inclusive).

    Raises
    ------
    ValueError
        If ``end`` is before ``start``.
    """

    start: MonthDay
    end: MonthDay

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(
                f"Season {self.start}..{self.end} crosses the new year, which is not supported."
            )

    @classmethod
    def vegetation(cls) -> Self:
        """Return the grapevine growing season of the northern hemisphere, April 1 - October 31.

        Returns
        -------
        Season
            Period used by growing degree-days (Amerine and Winkler, 1944).
        """
        return cls(MonthDay(4, 1), MonthDay(10, 31))

    @classmethod
    def huglin(cls) -> Self:
        """Return the period of the Huglin heliothermal index, April 1 - September 30.

        Returns
        -------
        Season
            Period defined by Huglin (1978) for the northern hemisphere.
        """
        return cls(MonthDay(4, 1), MonthDay(9, 30))

    @classmethod
    def month(cls, month: int) -> Self:
        """Return one whole calendar month, e.g. ``Season.month(9)`` for September.

        Parameters
        ----------
        month : int
            Month, 1-12.

        Returns
        -------
        Season
            From the first to the last day of the month (February ends on the 29th, read as
            the 28th in common years).
        """
        last_day = calendar.monthrange(_ANY_LEAP_YEAR, month)[1]
        return cls(MonthDay(month, 1), MonthDay(month, last_day))

    def dates(self, year: int) -> tuple[date, date]:
        """Return the first and last date of the period in a given year.

        Parameters
        ----------
        year : int
            Calendar year.

        Returns
        -------
        tuple of datetime.date
            ``(first, last)``, both inclusive.
        """
        return self.start.in_year(year), self.end.in_year(year)

    def n_days(self, year: int) -> int:
        """Return the number of days of the period in a given year.

        Parameters
        ----------
        year : int
            Calendar year.

        Returns
        -------
        int
            Number of days, both ends included.
        """
        first, last = self.dates(year)
        return (last - first).days + 1

    def contains(self, day: date) -> bool:
        """Tell whether a date lies in the period of its own year.

        Parameters
        ----------
        day : datetime.date
            The date to test.

        Returns
        -------
        bool
            ``True`` if ``first <= day <= last`` for ``first, last = self.dates(day.year)``.
        """
        first, last = self.dates(day.year)
        return first <= day <= last

    def __str__(self) -> str:
        return f"{self.start}..{self.end}"
