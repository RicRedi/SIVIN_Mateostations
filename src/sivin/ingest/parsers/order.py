"""Row order of an export before local time is converted to UTC.

:meth:`~sivin.core.timeutil.LocalTimeConverter.to_utc` needs rows in source order, oldest
first. It raises for the whole input as soon as one ordinary row (outside daylight-saving
hours) steps back in time, and it reads a backward jump of the wall clock inside the repeated
autumn hour as the clock switch. Real exports can step back: a device clock is corrected, or
two overlapping exports are concatenated. :class:`RowOrderAnalyser` therefore decides the order
first:

1. **Newest first.** A table is reversed only when it is clearly newest first: it has at least
   ``min_steps`` counted steps and at least ``newest_first_min_share`` of them go back in time.
   A table that steps back but is too short to decide is read oldest first and reported.
2. **Large backward steps.** A row more than ``max_backward_step_s`` earlier than the latest
   time already read (clock reset, long overlap) is dropped; the rows before it are kept.
3. **Repair.** The remaining backward steps are handed to an :class:`OrderRepair` strategy.
   The default, :class:`SplitAtBackwardSteps`, starts a new segment at every backward step
   except one inside the repeated hour of a fall-back transition (between two ambiguous rows
   of the same date), so that the converter sees each export on its own.
4. **Incomplete transitions.** Ambiguous rows are trusted only when their segment has
   ordinary rows on both sides of the transition; otherwise they are marked unresolved (and
   dropped by the parser). This applies to every table, not only repaired ones: rows of the
   repeated hour repeated by an overlap at the end of a file look exactly like a transition
   that the file stops in, and the converter would resolve them as standard time.

All comparisons use the local wall clock.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.ingest.validation import BoolArray

IndexArray = npt.NDArray[np.intp]

_NS_PER_S: Final = 1_000_000_000


@dataclass(frozen=True, eq=False)
class RowOrder:
    """How the rows of one table are ordered and will be converted.

    Positions refer to the rows **after** a possible reversal.

    Attributes
    ----------
    newest_first : bool
        ``True`` if the table is clearly newest first and must be reversed before conversion.
    undecided : bool
        ``True`` if the table steps back in time but has too few steps to decide whether it is
        newest first; it is read oldest first.
    stale : numpy.ndarray of bool
        Rows more than ``max_backward_step_s`` earlier than a row before them; dropped.
    segments : tuple of slice
        Consecutive row ranges that are converted separately; one segment covering all rows
        when the order is clean.
    """

    newest_first: bool
    undecided: bool
    stale: BoolArray
    segments: tuple[slice, ...]

    @property
    def backward_steps(self) -> IndexArray:
        """0-based positions of the rows that step back in time (start of segments 2, 3, ...)."""
        return np.array([segment.start for segment in self.segments[1:]], dtype=np.intp)

    @property
    def is_repaired(self) -> bool:
        """``True`` if the rows are converted in more than one segment."""
        return len(self.segments) > 1


@dataclass(frozen=True, eq=False)
class WallClock:
    """Wall-clock view of naive local timestamps.

    Attributes
    ----------
    ns : numpy.ndarray of int64
        Local wall-clock time in nanoseconds since 1970 (meaningless where not ``present``).
    present : numpy.ndarray of bool
        ``True`` where the timestamp is not ``NaT``.
    ambiguous : numpy.ndarray of bool
        ``True`` where the local time falls into the repeated hour of a fall-back transition.
    day : numpy.ndarray of datetime64[D]
        Local calendar day of each row (identifies the transition of an ambiguous row).
    """

    ns: npt.NDArray[np.int64]
    present: BoolArray
    ambiguous: BoolArray
    day: npt.NDArray[np.datetime64]

    @classmethod
    def of(cls, local: pd.Series, zone: ZoneInfo) -> WallClock:
        """Build the view of naive ``local`` timestamps in ``zone``.

        Parameters
        ----------
        local : pandas.Series
            Naive ``datetime64`` timestamps; ``NaT`` allowed.
        zone : zoneinfo.ZoneInfo
            The zone of the wall clock.

        Returns
        -------
        WallClock
            The view.
        """
        naive = local.dt.as_unit("ns")
        present = np.asarray(naive.notna().to_numpy(), dtype=np.bool_)
        localized = naive.dt.tz_localize(zone, ambiguous="NaT", nonexistent="shift_forward")
        values = naive.to_numpy(dtype="datetime64[ns]")
        return cls(
            ns=values.view(np.int64),
            present=present,
            ambiguous=present & np.asarray(localized.isna().to_numpy(), dtype=np.bool_),
            day=values.astype("datetime64[D]"),
        )

    def steps(self, rows: BoolArray | None = None) -> tuple[IndexArray, npt.NDArray[np.int64]]:
        """Return the steps between consecutive present rows that count for the row order.

        A step between two ambiguous rows of the same day (inside the repeated hour of one
        fall-back transition) does not count: its direction is unknown before conversion.

        Parameters
        ----------
        rows : numpy.ndarray of bool, optional
            Only these rows (and only if present); all present rows when omitted.

        Returns
        -------
        tuple of numpy.ndarray
            ``(positions, steps_ns)``: the position of the later row of every counted step and
            the wall-clock difference in nanoseconds (negative = backward).
        """
        selected = self.present if rows is None else self.present & rows
        positions = np.flatnonzero(selected)
        earlier, later = positions[:-1], positions[1:]
        same_transition = (
            self.ambiguous[earlier] & self.ambiguous[later] & (self.day[earlier] == self.day[later])
        )
        counted = ~same_transition
        return later[counted], (self.ns[later] - self.ns[earlier])[counted]


class OrderRepair(ABC):
    """Strategy for rows that step back in local time."""

    @abstractmethod
    def segments(self, clock: WallClock, rows: BoolArray) -> tuple[slice, ...]:
        """Cut the rows into segments the converter accepts.

        Parameters
        ----------
        clock : WallClock
            Wall-clock view of all rows, in conversion order.
        rows : numpy.ndarray of bool
            The rows that will be converted (others are ignored).

        Returns
        -------
        tuple of slice
            Consecutive, non-overlapping ranges covering all rows; within each range the
            selected rows do not step back, except inside the repeated hour of a fall-back.
        """


class SplitAtBackwardSteps(OrderRepair):
    """Start a new segment at every counted backward step (see :meth:`WallClock.steps`).

    No row is dropped. After conversion, rows of a clock correction are simply earlier UTC
    instants (``MeasurementSeries.from_records`` sorts them) and rows repeated by overlapping
    exports become duplicate instants (the last occurrence is kept and reported).
    """

    def segments(self, clock: WallClock, rows: BoolArray) -> tuple[slice, ...]:
        """Split at backward steps (see :meth:`OrderRepair.segments`)."""
        positions, steps = clock.steps(rows)
        starts = [0, *positions[steps < 0].tolist()]
        ends = [*starts[1:], len(rows)]
        return tuple(slice(start, end) for start, end in zip(starts, ends, strict=True))


class RowOrderAnalyser:
    """Decide the conversion order of a table (see the module docstring).

    Parameters
    ----------
    timezone : str
        IANA zone of the local timestamps.
    newest_first_min_share : float
        Share (0-1) of the counted steps that must go back in time for a newest-first table.
    min_steps : int
        Minimum number of counted non-zero steps needed to decide that a table is newest first.
    max_backward_step_s : float
        Rows more than this many seconds earlier than the latest time read so far are dropped.
    repair : OrderRepair, optional
        Strategy for the remaining backward steps; :class:`SplitAtBackwardSteps` when omitted.
    """

    __slots__ = ("_max_backward_ns", "_min_share", "_min_steps", "_repair", "_zone")

    def __init__(
        self,
        timezone: str,
        newest_first_min_share: float,
        min_steps: int,
        max_backward_step_s: float,
        repair: OrderRepair | None = None,
    ) -> None:
        self._zone = ZoneInfo(timezone)
        self._min_share = newest_first_min_share
        self._min_steps = min_steps
        self._max_backward_ns = round(max_backward_step_s * _NS_PER_S)
        self._repair = repair or SplitAtBackwardSteps()

    def wall_clock(self, local: pd.Series) -> WallClock:
        """Return the wall-clock view of ``local`` in this analyser's zone.

        Parameters
        ----------
        local : pandas.Series
            Naive local timestamps.

        Returns
        -------
        WallClock
            Instants, presence, ambiguity and local day of every row.
        """
        return WallClock.of(local, self._zone)

    def analyse(self, local: pd.Series) -> RowOrder:
        """Return the conversion order of a table.

        Parameters
        ----------
        local : pandas.Series
            Naive local timestamps in file order; ``NaT`` for rows that will not be converted.

        Returns
        -------
        RowOrder
            Reversal, dropped stale rows and segments, in the (reversed) row order.
        """
        _, steps = self.wall_clock(local).steps()
        backward = int((steps < 0).sum())
        moving = backward + int((steps > 0).sum())
        decidable = moving >= self._min_steps
        newest_first = decidable and backward > 0 and backward >= self._min_share * moving
        ordered = local.iloc[::-1].reset_index(drop=True) if newest_first else local
        clock = self.wall_clock(ordered)
        stale = self._stale(clock)
        return RowOrder(
            newest_first=newest_first,
            undecided=not decidable and backward > 0,
            stale=stale,
            segments=self._repair.segments(clock, ~stale),
        )

    def incomplete_transitions(self, local: pd.Series, order: RowOrder) -> BoolArray:
        """Mark ambiguous rows whose transition is not fully covered by their segment.

        Within a segment, the ambiguous rows of one fall-back day can be resolved only between
        ordinary rows before and after them; in a segment that starts or ends inside the
        repeated hour the converter would have to guess (see the module docstring, point 4).

        Parameters
        ----------
        local : pandas.Series
            Naive local timestamps in conversion order (``NaT`` for rows not converted).
        order : RowOrder
            The order returned by :meth:`analyse` for these rows.

        Returns
        -------
        numpy.ndarray of bool
            ``True`` for the ambiguous rows to drop.
        """
        clock = self.wall_clock(local)
        incomplete = np.zeros(len(local), dtype=np.bool_)
        ordinary = clock.present & ~clock.ambiguous
        for segment in order.segments:
            positions = np.arange(segment.start, segment.stop)
            group_positions = positions[clock.ambiguous[segment]]
            for day in np.unique(clock.day[group_positions]):
                group = group_positions[clock.day[group_positions] == day]
                before = ordinary[segment.start : group[0]].any()
                after = ordinary[group[-1] + 1 : segment.stop].any()
                if not (before and after):
                    incomplete[group] = True
        return incomplete

    def _stale(self, clock: WallClock) -> BoolArray:
        """Rows more than the maximum backward step earlier than the latest row before them."""
        stale = np.zeros(len(clock.ns), dtype=np.bool_)
        latest: int | None = None
        for position in np.flatnonzero(clock.present):
            instant = int(clock.ns[position])
            if latest is not None and instant < latest - self._max_backward_ns:
                stale[position] = True
            elif latest is None or instant > latest:
                latest = instant
        return stale
