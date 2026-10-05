"""How the rows of one sensor are split into files (MIGRATION_PLAN §2.5).

A :class:`Partitioning` maps each UTC timestamp to a *partition key* (a short string that is the
stem of the file name) and back to the time interval a key covers. The store only talks to this
interface, so a monthly layout is another registered subclass, not a change of the store.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import ClassVar, Final

import pandas as pd

from sivin.storage.registry import NamedRegistry


class Partitioning(ABC):
    """Extension point: assignment of timestamps to partition files.

    Implementations must give keys whose lexicographic order equals the chronological order of
    the partitions, and partitions that do not overlap.
    """

    name: ClassVar[str]
    """Registry name of the partitioning, used in the configuration (the only place it is set)."""

    @abstractmethod
    def keys_of(self, timestamps_utc: pd.Series) -> pd.Series:
        """Return the partition key of every timestamp.

        Parameters
        ----------
        timestamps_utc : pandas.Series
            ``datetime64[ns, UTC]`` values.

        Returns
        -------
        pandas.Series of str
            One key per timestamp, aligned with the input.
        """

    @abstractmethod
    def is_key(self, text: str) -> bool:
        """Tell whether ``text`` (a file-name stem) is a valid partition key.

        Parameters
        ----------
        text : str
            Candidate key.

        Returns
        -------
        bool
            ``True`` for a valid key.
        """

    @abstractmethod
    def bounds(self, key: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Return the half-open UTC interval ``[start, end)`` covered by ``key``.

        Parameters
        ----------
        key : str
            A valid partition key.

        Returns
        -------
        tuple of pandas.Timestamp
            Start (inclusive) and end (exclusive), both UTC.

        Raises
        ------
        ValueError
            If ``key`` is not a valid key.
        """

    def overlaps(self, key: str, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> bool:
        """Tell whether the partition ``key`` may hold rows in ``[start_utc, end_utc]``.

        Parameters
        ----------
        key : str
            A valid partition key.
        start_utc, end_utc : pandas.Timestamp
            Inclusive UTC bounds of the requested interval.

        Returns
        -------
        bool
            ``True`` if the intervals intersect.
        """
        first, after_last = self.bounds(key)
        return first <= end_utc and start_utc < after_last


partitioning_registry: Final = NamedRegistry[Partitioning](Partitioning)
"""Registered partitionings, keyed by :attr:`Partitioning.name`."""


@partitioning_registry.register
class YearPartitioning(Partitioning):
    """One partition per **UTC** calendar year; the key is the four-digit year, e.g. ``2026``.

    The year is taken in UTC, not in local time: a sample taken at 00:30 local time on
    1 January (23:30 UTC on 31 December in winter) belongs to the previous year's file.
    """

    name: ClassVar[str] = "year"

    _KEY_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[0-9]{4}")

    def keys_of(self, timestamps_utc: pd.Series) -> pd.Series:
        """Return the UTC year of every timestamp as a four-digit string.

        Parameters
        ----------
        timestamps_utc : pandas.Series
            ``datetime64[ns, UTC]`` values.

        Returns
        -------
        pandas.Series of str
            E.g. ``"2026"``.
        """
        years: pd.Series = timestamps_utc.dt.tz_convert("UTC").dt.strftime("%Y")
        return years

    def is_key(self, text: str) -> bool:
        """Tell whether ``text`` is a four-digit year.

        Parameters
        ----------
        text : str
            Candidate key.

        Returns
        -------
        bool
            ``True`` for exactly four ASCII digits.
        """
        return self._KEY_PATTERN.fullmatch(text) is not None

    def bounds(self, key: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Return ``[1 Jan key 00:00 UTC, 1 Jan key+1 00:00 UTC)``.

        Parameters
        ----------
        key : str
            Four-digit year.

        Returns
        -------
        tuple of pandas.Timestamp
            Start (inclusive) and end (exclusive), UTC.

        Raises
        ------
        ValueError
            If ``key`` is not a four-digit year.
        """
        if not self.is_key(key):
            raise ValueError(f"{key!r} is not a four-digit year.")
        year = int(key)
        return (
            pd.Timestamp(year=year, month=1, day=1, tz="UTC"),
            pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC"),
        )
