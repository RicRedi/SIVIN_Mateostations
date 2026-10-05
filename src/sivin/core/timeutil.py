"""Conversion between local wall-clock time and UTC (MIGRATION_PLAN §1.5).

Internally every timestamp is UTC. Local time appears in two places only: when parsing exports
whose timestamps are local wall-clock time, and when aggregating to local calendar days.
:class:`LocalTimeConverter` handles both, including the daylight-saving transitions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import numpy.typing as npt
import pandas as pd

logger = logging.getLogger(__name__)

_NO_INSTANT: Final = np.iinfo(np.int64).min
"""Marker for "no instant" in int64 nanosecond arrays (the value pandas uses for ``NaT``)."""


@dataclass(frozen=True)
class ConversionResult:
    """Result of :meth:`LocalTimeConverter.to_utc`.

    All three series have the index of the input.

    Attributes
    ----------
    timestamps_utc : pandas.Series
        Converted timestamps, ``datetime64[ns, UTC]``. ``NaT`` where the input was ``NaT`` and
        where the conversion would have collided with another row (see ``unresolved``).
        Callers must drop (and report) the ``NaT`` rows, and decide what to do with
        ``unresolved`` rows, before building a
        :class:`~sivin.core.schema.MeasurementSeries`, which rejects ``NaT``.
    suspect : pandas.Series of bool
        ``True`` where the local time was ambiguous (repeated hour when clocks fall back) or
        nonexistent (skipped hour when clocks spring forward). Callers typically set
        :attr:`~sivin.core.flags.QcFlag.TIMESTAMP_SUSPECT` on these rows.
    unresolved : pandas.Series of bool
        Subset of ``suspect``: every ambiguous row not resolved by the clock-jump rule (its UTC
        instant is a guess) and every row returned as ``NaT`` because of a collision.
    """

    timestamps_utc: pd.Series
    suspect: pd.Series
    unresolved: pd.Series


class LocalTimeConverter:
    """Convert between UTC and the wall-clock time of one IANA time zone.

    **Input order contract:** rows must be in source/export order, **oldest first**, exactly
    as recorded. Do not sort by local time before converting (that destroys the information
    in the repeated hour); reverse a newest-first export instead. :meth:`to_utc` raises
    ``ValueError`` when the unambiguous rows (not ``NaT``, not in a daylight-saving hour)
    decrease in time.

    Daylight-saving transitions are resolved deterministically:

    * **Ambiguous** times (the repeated hour when clocks fall back) are grouped per local
      calendar date, so every transition is resolved on its own. Within a group (``NaT``
      rows skipped), a **backward jump of the wall clock** (a sample strictly earlier than its
      predecessor) is the switch point: samples before it are summer time, samples from it on
      standard time. Only a group with **exactly one** jump is resolved; this needs no
      complete hour and tolerates missing samples. Every other group is marked
      ``unresolved``, with a warning, and gets a best guess: without a jump, the split that
      keeps consecutive samples (including the nearest unambiguous neighbours) farthest
      apart, if that split is strictly increasing and unique; otherwise (several jumps,
      ties) standard time.
    * **Equal consecutive wall-clock values** in the repeated hour are duplicates, not a
      jump. Both copies get the same offset, hence the same UTC instant, and are then
      handled by the collision rule below (``NaT`` + ``unresolved``).
    * **Nonexistent** times (the skipped hour when clocks spring forward) are read with the UTC
      offset in effect *before* the transition (PEP 495, ``fold=0``), i.e. shifted forward by
      the length of the gap. Samples inside the gap usually mean that the device clock does
      not follow daylight-saving time, i.e. that the configured source zone is wrong.
    * **No silent duplicates:** a suspect row whose UTC instant equals that of another row is
      returned as ``NaT`` and marked ``unresolved`` (a warning is logged). Duplicates between
      two ordinary rows come from the source data and are left to input validation.

    Every ambiguous or nonexistent row is suspect, whether or not it was resolved, because a
    resolved time is still a guess about the device clock.

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
            Naive ``datetime64`` timestamps in this zone's wall-clock time, in source order,
            oldest first (see the class docstring). ``NaT`` stays ``NaT``.

        Returns
        -------
        ConversionResult
            UTC timestamps (``datetime64[ns, UTC]``), the suspect and the unresolved masks.
            Drop (and report) the ``NaT`` rows and handle the ``unresolved`` ones before
            passing the timestamps to :meth:`MeasurementSeries.from_records`.

        Raises
        ------
        TypeError
            If the series is not of a naive ``datetime64`` dtype.
        ValueError
            If the unambiguous rows are not in increasing time order (e.g. newest first).
        """
        naive = self._checked_naive(local_naive).reset_index(drop=True)
        present = naive.notna().to_numpy()
        n_rows = len(naive)
        ambiguous = (
            present
            & naive.dt.tz_localize(self._zone, ambiguous="NaT", nonexistent="shift_forward")
            .isna()
            .to_numpy()
        )
        nonexistent = (
            present
            & naive.dt.tz_localize(
                self._zone, ambiguous=np.zeros(n_rows, dtype=bool), nonexistent="NaT"
            )
            .isna()
            .to_numpy()
        )
        self._check_order(naive, ambiguous | nonexistent | ~present)
        summer_time, unresolved = self._resolve_ambiguous(naive, ambiguous)
        localized = naive.dt.tz_localize(self._zone, ambiguous=summer_time, nonexistent="NaT")
        utc = localized.dt.tz_convert("UTC").dt.as_unit("ns")
        if nonexistent.any():
            utc.iloc[np.flatnonzero(nonexistent)] = [
                self._before_gap_utc(pd.Timestamp(wall_clock))
                for wall_clock in naive.to_numpy()[nonexistent]
            ]
        suspect = ambiguous | nonexistent
        collided = suspect & utc.duplicated(keep=False).to_numpy() & utc.notna().to_numpy()
        if collided.any():
            logger.warning(
                "%d suspect local time(s) in %s would duplicate another UTC instant; "
                "returned as NaT.",
                int(collided.sum()),
                self.timezone,
            )
            utc.iloc[np.flatnonzero(collided)] = pd.NaT
        index = local_naive.index
        return ConversionResult(
            timestamps_utc=pd.Series(utc.to_numpy(), index=index, name=local_naive.name),
            suspect=pd.Series(suspect, index=index, name="suspect"),
            unresolved=pd.Series(unresolved | collided, index=index, name="unresolved"),
        )

    @staticmethod
    def _check_order(naive: pd.Series, skipped: npt.NDArray[np.bool_]) -> None:
        """Raise if the rows outside daylight-saving hours decrease in time."""
        wall_clock = naive.to_numpy()[~skipped]
        decreasing = np.flatnonzero(wall_clock[1:] < wall_clock[:-1])
        if len(decreasing):
            first = decreasing[0]
            raise ValueError(
                "Local timestamps must be in source order, oldest first (do not sort by "
                f"local time, reverse a newest-first export): {wall_clock[first + 1]} follows "
                f"{wall_clock[first]}."
            )

    def _resolve_ambiguous(
        self, naive: pd.Series, ambiguous: npt.NDArray[np.bool_]
    ) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
        """Decide summer or standard time for the ambiguous rows, one transition at a time.

        Returns
        -------
        tuple of numpy.ndarray of bool
            ``(summer_time, unresolved)`` per row.
        """
        n_rows = len(naive)
        summer_time = np.zeros(n_rows, dtype=bool)
        unresolved = np.zeros(n_rows, dtype=bool)
        if not ambiguous.any():
            return summer_time, unresolved
        candidates = _TransitionCandidates.build(naive, self._zone)
        positions = np.flatnonzero(ambiguous)
        days = naive.to_numpy()[positions].astype("datetime64[D]")
        for day in np.unique(days):
            group = positions[days == day]
            n_summer, resolved = candidates.switch_point(group, ambiguous)
            summer_time[group[:n_summer]] = True
            if not resolved:
                unresolved[group] = True
                logger.warning(
                    "%d ambiguous local time(s) on %s in %s have no single clock jump; "
                    "their offsets are a guess (%d read as summer time).",
                    len(group),
                    day,
                    self.timezone,
                    n_summer,
                )
        return summer_time, unresolved

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


@dataclass(frozen=True)
class _TransitionCandidates:
    """UTC instants of every row read as summer time and as standard time (int64 ns).

    Nonexistent rows and ``NaT`` are ``_NO_INSTANT`` in both arrays.
    """

    wall_clock_ns: npt.NDArray[np.int64]
    summer_ns: npt.NDArray[np.int64]
    standard_ns: npt.NDArray[np.int64]

    @classmethod
    def build(cls, naive: pd.Series, zone: ZoneInfo) -> _TransitionCandidates:
        n_rows = len(naive)

        def as_ns(summer: bool) -> npt.NDArray[np.int64]:
            flags = np.full(n_rows, summer, dtype=bool)
            local = naive.dt.tz_localize(zone, ambiguous=flags, nonexistent="NaT")
            return _instants_ns(pd.DatetimeIndex(local).tz_convert("UTC").tz_localize(None))

        return cls(
            wall_clock_ns=_instants_ns(pd.DatetimeIndex(naive)),
            summer_ns=as_ns(summer=True),
            standard_ns=as_ns(summer=False),
        )

    def switch_point(
        self, group: npt.NDArray[np.intp], ambiguous: npt.NDArray[np.bool_]
    ) -> tuple[int, bool]:
        """Return how many leading rows of an ambiguous group are summer time.

        Returns
        -------
        tuple of (int, bool)
            ``(n_summer, resolved)``. ``resolved`` is ``True`` only for rule 1.

        1. Exactly one backward jump of the wall clock (a sample strictly earlier than its
           predecessor) is the switch point: resolved.
        2. Without any jump, a guess: the split that keeps consecutive samples (including the
           nearest unambiguous neighbours) farthest apart, if it is strictly increasing and
           unique.
        3. Otherwise (several jumps, ties): standard time for the whole group.
        """
        wall_clock = self.wall_clock_ns[group]
        jumps = np.flatnonzero(wall_clock[1:] < wall_clock[:-1]) + 1
        if len(jumps) == 1:
            return int(jumps[0]), True
        if len(jumps) > 1:
            return 0, False
        before = self._neighbour(group[0], -1, ambiguous)
        after = self._neighbour(group[-1], 1, ambiguous)
        scores: list[float] = []
        for n_summer in range(len(group) + 1):
            sequence = np.concatenate(
                [
                    before,
                    self.summer_ns[group[:n_summer]],
                    self.standard_ns[group[n_summer:]],
                    after,
                ]
            )
            steps = np.diff(sequence)
            if len(steps) == 0:
                scores.append(np.inf)
            elif (steps <= 0).any():
                scores.append(-np.inf)
            else:
                scores.append(float(steps.min()))
        best = max(scores)
        if best == -np.inf or scores.count(best) != 1:
            return 0, False
        return scores.index(best), False

    def _neighbour(
        self, position: np.intp, direction: int, ambiguous: npt.NDArray[np.bool_]
    ) -> npt.NDArray[np.int64]:
        """Return the UTC instant of the nearest usable row before/after ``position``."""
        index = int(position) + direction
        while 0 <= index < len(self.standard_ns):
            if self.standard_ns[index] != _NO_INSTANT and not ambiguous[index]:
                return self.standard_ns[index : index + 1]
            if self.wall_clock_ns[index] != _NO_INSTANT and not ambiguous[index]:
                break
            index += direction
        return np.empty(0, dtype=np.int64)


def _instants_ns(naive: pd.DatetimeIndex) -> npt.NDArray[np.int64]:
    """Return naive timestamps as int64 nanoseconds; ``NaT`` becomes ``_NO_INSTANT``."""
    values = naive.as_unit("ns").to_numpy(dtype="datetime64[ns]")
    return np.asarray(values.view(np.int64), dtype=np.int64)
