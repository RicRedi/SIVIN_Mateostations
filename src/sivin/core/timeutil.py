"""Conversion between local wall-clock time and UTC (MIGRATION_PLAN §1.5).

Internally every timestamp is UTC. Local time appears in two places only: when parsing exports
whose timestamps are local wall-clock time, and when aggregating to local calendar days.
:class:`LocalTimeConverter` handles both, including the daylight-saving transitions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversionResult:
    """Result of :meth:`LocalTimeConverter.to_utc`.

    Attributes
    ----------
    timestamps_utc : pandas.Series
        Converted timestamps, ``datetime64[ns, UTC]``, aligned with the input.
    suspect : pandas.Series of bool
        ``True`` where the local time was ambiguous (repeated hour when clocks fall back) or
        nonexistent (skipped hour when clocks spring forward). Callers typically set
        :attr:`~sivin.core.flags.QcFlag.TIMESTAMP_SUSPECT` on these rows.
    """

    timestamps_utc: pd.Series
    suspect: pd.Series


class LocalTimeConverter:
    """Convert between UTC and the wall-clock time of one IANA time zone.

    Daylight-saving transitions are resolved deterministically:

    * **Ambiguous** times (the repeated hour when clocks fall back) are first resolved from the
      order of the samples (``ambiguous="infer"``: the first occurrence is summer time, the
      repeated one standard time). When that is impossible, e.g. because the repeated hour has
      only one sample, every ambiguous time of the input is read as **standard time**.
    * **Nonexistent** times (the skipped hour when clocks spring forward) are read with the UTC
      offset in effect *before* the transition (PEP 495, ``fold=0``), which equals shifting
      them forward by the length of the gap; spacing between samples is preserved.

    Both kinds are reported as suspect in :class:`ConversionResult`, whether or not inference
    succeeded, because a resolved ambiguous time is still a guess about the device clock.

    Parameters
    ----------
    timezone : str
        IANA zone name, e.g. ``"Europe/Prague"``.

    Raises
    ------
    ValueError
        If the zone name is unknown.
    """

    __slots__ = ("_zone",)

    def __init__(self, timezone: str) -> None:
        try:
            self._zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Unknown IANA time zone {timezone!r}.") from error

    @property
    def timezone(self) -> str:
        """The IANA zone name."""
        return self._zone.key

    def to_utc(self, local_naive: pd.Series) -> ConversionResult:
        """Convert naive local wall-clock timestamps to UTC.

        Parameters
        ----------
        local_naive : pandas.Series
            Naive ``datetime64`` timestamps in this zone's wall-clock time, in recorded order
            (inference of ambiguous times relies on that order). ``NaT`` stays ``NaT``.

        Returns
        -------
        ConversionResult
            UTC timestamps (``datetime64[ns, UTC]``) and the suspect mask, both with the index
            of ``local_naive``.

        Raises
        ------
        TypeError
            If the series is not of a naive ``datetime64`` dtype.
        """
        naive = self._checked_naive(local_naive)
        n_rows = len(naive)
        standard_time = np.zeros(n_rows, dtype=bool)
        ambiguous = (
            naive.dt.tz_localize(self._zone, ambiguous="NaT", nonexistent="shift_forward").isna()
            & naive.notna()
        )
        nonexistent = (
            naive.dt.tz_localize(self._zone, ambiguous=standard_time, nonexistent="NaT").isna()
            & naive.notna()
        )
        try:
            localized = naive.dt.tz_localize(self._zone, ambiguous="infer", nonexistent="NaT")
        except ValueError:
            logger.warning(
                "Cannot infer %d ambiguous local time(s) in %s from sample order; "
                "reading them as standard time.",
                int(ambiguous.sum()),
                self.timezone,
            )
            localized = naive.dt.tz_localize(self._zone, ambiguous=standard_time, nonexistent="NaT")
        utc = localized.dt.tz_convert("UTC").dt.as_unit("ns")
        if nonexistent.any():
            utc = utc.copy()
            utc.loc[nonexistent] = [self._before_gap_utc(t) for t in naive.loc[nonexistent]]
        suspect = (ambiguous | nonexistent).rename("suspect")
        return ConversionResult(timestamps_utc=utc.rename(local_naive.name), suspect=suspect)

    def local_dates(self, utc: pd.Series) -> pd.Series:
        """Return the local calendar date of each UTC timestamp.

        Parameters
        ----------
        utc : pandas.Series
            Timezone-aware ``datetime64`` timestamps.

        Returns
        -------
        pandas.Series of datetime.date
            Calendar date in this zone, with the index of ``utc``.

        Raises
        ------
        TypeError
            If the timestamps are not timezone-aware.
        """
        if not isinstance(utc.dtype, pd.DatetimeTZDtype):
            raise TypeError(f"Expected timezone-aware timestamps, got dtype {utc.dtype}.")
        dates: pd.Series = utc.dt.tz_convert(self._zone).dt.date
        return dates

    def day_bounds_utc(self, day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Return the UTC bounds of a local calendar day.

        Parameters
        ----------
        day : datetime.date
            Local calendar date.

        Returns
        -------
        tuple of pandas.Timestamp
            ``(start, end)`` in UTC, half-open: the day is ``start <= t < end``. The span is
            23 h on the spring-forward day and 25 h on the fall-back day.
        """
        return self._local_midnight_utc(day), self._local_midnight_utc(day + timedelta(days=1))

    def day_length_s(self, day: date) -> float:
        """Return the length of a local calendar day.

        Parameters
        ----------
        day : datetime.date
            Local calendar date.

        Returns
        -------
        float
            Length of the day in seconds (82 800, 86 400 or 90 000 s in Europe/Prague).
        """
        start, end = self.day_bounds_utc(day)
        return float((end - start).total_seconds())

    def _local_midnight_utc(self, day: date) -> pd.Timestamp:
        midnight = pd.Timestamp(datetime(day.year, day.month, day.day))
        local = midnight.tz_localize(self._zone, ambiguous=False, nonexistent="shift_forward")
        return local.tz_convert("UTC").as_unit("ns")

    def _before_gap_utc(self, naive: pd.Timestamp) -> pd.Timestamp:
        wall_clock = naive.to_pydatetime().replace(tzinfo=self._zone, fold=0)
        offset = wall_clock.utcoffset()
        if offset is None:  # pragma: no cover - ZoneInfo always returns an offset
            raise ValueError(f"No UTC offset for {naive} in {self.timezone}.")
        return pd.Timestamp(naive - offset, tz="UTC").as_unit("ns")

    @staticmethod
    def _checked_naive(local_naive: pd.Series) -> pd.Series:
        if not pd.api.types.is_datetime64_dtype(local_naive.dtype) or isinstance(
            local_naive.dtype, pd.DatetimeTZDtype
        ):
            raise TypeError(f"Expected naive datetime64 timestamps, got dtype {local_naive.dtype}.")
        naive: pd.Series = local_naive.dt.as_unit("ns")
        return naive
