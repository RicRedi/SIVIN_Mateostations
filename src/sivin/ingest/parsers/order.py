"""Row order of an export before local time is converted to UTC.

:meth:`~sivin.core.timeutil.LocalTimeConverter.to_utc` needs rows in source order, oldest
first, and raises for the whole input as soon as one ordinary (non daylight-saving) row steps
back in time. Real exports can do that: a device clock is corrected by a few seconds, or two
overlapping exports are concatenated. :class:`RowOrderAnalyser` therefore inspects the order
first:

1. a table is reversed only when it is **clearly newest first** (a large majority of the
   ordinary steps go back in time),
2. the remaining backward steps are handed to an :class:`OrderRepair` strategy that cuts the
   rows into segments the converter accepts. The default, :class:`SplitAtBackwardSteps`,
   starts a new segment at every backward step and drops no row.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.ingest.validation import BoolArray

IndexArray = npt.NDArray[np.intp]


@dataclass(frozen=True, eq=False)
class RowOrder:
    """How the rows of one table are ordered and will be converted.

    Attributes
    ----------
    newest_first : bool
        ``True`` if the table is clearly newest first and must be reversed before conversion.
    segments : tuple of slice
        Consecutive row ranges (positions after a possible reversal) that are converted
        separately; one segment covering all rows when the order is clean.
    """

    newest_first: bool
    segments: tuple[slice, ...]

    @property
    def backward_steps(self) -> IndexArray:
        """0-based positions of the rows that step back in time (start of segments 2, 3, ...)."""
        return np.array([segment.start for segment in self.segments[1:]], dtype=np.intp)


class OrderRepair(ABC):
    """Strategy for rows that step back in local time outside daylight-saving hours."""

    @abstractmethod
    def segments(self, local: pd.Series, ordinary: BoolArray) -> tuple[slice, ...]:
        """Cut the rows into segments the converter accepts.

        Parameters
        ----------
        local : pandas.Series
            Naive local timestamps in conversion order (``NaT`` where unreadable).
        ordinary : numpy.ndarray of bool
            ``True`` for rows with a readable local time outside daylight-saving transitions;
            only these rows must not decrease within a segment.

        Returns
        -------
        tuple of slice
            Consecutive, non-overlapping ranges covering all rows.
        """


class SplitAtBackwardSteps(OrderRepair):
    """Start a new segment at every ordinary row that is earlier than the previous one.

    No row is dropped. After conversion, rows of a clock correction are simply earlier UTC
    instants (``MeasurementSeries.from_records`` sorts them) and rows repeated by overlapping
    exports become duplicate instants (the last occurrence is kept and reported).
    """

    def segments(self, local: pd.Series, ordinary: BoolArray) -> tuple[slice, ...]:
        """Split at backward steps (see :meth:`OrderRepair.segments`)."""
        positions = np.flatnonzero(ordinary)
        wall_clock = local.to_numpy()[positions]
        starts = [0, *positions[1:][wall_clock[1:] < wall_clock[:-1]].tolist()]
        ends = [*starts[1:], len(local)]
        return tuple(slice(start, end) for start, end in zip(starts, ends, strict=True))


class RowOrderAnalyser:
    """Decide the conversion order of a table: reverse it, and where to split it.

    Parameters
    ----------
    timezone : str
        IANA zone of the local timestamps.
    newest_first_min_share : float
        Share (0-1) of the ordinary non-zero steps that must go back in time for the table to
        count as newest first.
    repair : OrderRepair, optional
        Strategy for the remaining backward steps; :class:`SplitAtBackwardSteps` when omitted.
    """

    __slots__ = ("_min_share", "_repair", "_zone")

    def __init__(
        self, timezone: str, newest_first_min_share: float, repair: OrderRepair | None = None
    ) -> None:
        self._zone = ZoneInfo(timezone)
        self._min_share = newest_first_min_share
        self._repair = repair or SplitAtBackwardSteps()

    def ordinary(self, local: pd.Series) -> BoolArray:
        """Tell which rows have a readable local time outside daylight-saving transitions.

        Parameters
        ----------
        local : pandas.Series
            Naive local timestamps.

        Returns
        -------
        numpy.ndarray of bool
            ``False`` for ``NaT`` and for ambiguous or nonexistent local times.
        """
        localized = local.dt.tz_localize(self._zone, ambiguous="NaT", nonexistent="NaT")
        return np.asarray(localized.notna().to_numpy(), dtype=np.bool_)

    def is_newest_first(self, local: pd.Series) -> bool:
        """Tell whether a table is clearly recorded newest first.

        Parameters
        ----------
        local : pandas.Series
            Naive local timestamps in file order.

        Returns
        -------
        bool
            ``True`` if at least ``newest_first_min_share`` of the non-zero steps between
            consecutive ordinary rows go back in time.
        """
        wall_clock = local.to_numpy()[self.ordinary(local)].view(np.int64)
        steps = np.diff(wall_clock)
        backward = int((steps < 0).sum())
        moving = backward + int((steps > 0).sum())
        return backward > 0 and backward >= self._min_share * moving

    def analyse(self, local: pd.Series) -> RowOrder:
        """Return the conversion order of a table.

        Parameters
        ----------
        local : pandas.Series
            Naive local timestamps in file order.

        Returns
        -------
        RowOrder
            Whether to reverse the rows, and the segments of the (reversed) rows.
        """
        newest_first = self.is_newest_first(local)
        ordered = local.iloc[::-1].reset_index(drop=True) if newest_first else local
        return RowOrder(newest_first, self._repair.segments(ordered, self.ordinary(ordered)))
