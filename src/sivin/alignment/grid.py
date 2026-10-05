"""The common time grid the sensors are aligned onto (MIGRATION_PLAN §2.7).

A :class:`TimeGrid` is a regular sequence of UTC instants ``start, start + step, …, end``.
:class:`GridPolicy` derives a grid from the time spans of several series; *which* span (the
union of all spans or their overlap) is an extension point, :class:`SpanRule`.

Grid points are anchored to multiples of the step since the Unix epoch (for the default 30 min:
``hh:00`` and ``hh:30`` UTC), so grids derived from different data sets coincide.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.alignment.registry import ClassRegistry
from sivin.core.schema import Column, MeasurementSeries

logger = logging.getLogger(__name__)

DEFAULT_GRID_STEP_S: Final = 1800.0
"""Default grid step in seconds: 30 min, the default named in MIGRATION_PLAN §2.7.

It is the round value closest to the sensors' nominal sampling interval of 1825 s
(:data:`sivin.core.defaults.LEGACY_SAMPLING_INTERVAL_S`).
"""

MIN_GRID_STEP_S: Final = 1.0
"""Smallest accepted grid step in seconds; the sensors sample about every 1825 s, so anything
finer is a configuration error rather than a use case."""

_NS_PER_S: Final = 1_000_000_000
_WHOLE_NS_TOLERANCE: Final = 1e-3
"""Allowed deviation (ns) of ``step_s * 1e9`` from an integer, for float representation error."""

DataSpan = tuple[pd.Timestamp, pd.Timestamp]
"""First and last usable instant (UTC) of one series, inclusive."""


@dataclass(frozen=True, slots=True)
class TimeGrid:
    """A regular grid of UTC instants.

    The grid points are ``start + k * step`` for every integer ``k >= 0`` with the point not
    later than ``end``; ``start`` is always a grid point, ``end`` only if the span is a whole
    number of steps.

    Parameters
    ----------
    start : pandas.Timestamp
        First grid point; timezone-aware (converted to UTC).
    end : pandas.Timestamp
        Upper bound (inclusive); timezone-aware, not before ``start``.
    step_s : float
        Distance between grid points in seconds: at least 1 s and a whole number of
        nanoseconds. Default 1800 s (30 min).

    Raises
    ------
    ValueError
        If a bound is naive, ``end`` is before ``start`` or ``step_s`` is invalid.
    """

    start: pd.Timestamp
    end: pd.Timestamp
    step_s: float = DEFAULT_GRID_STEP_S
    _times: pd.DatetimeIndex = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _utc(self.start, "start"))
        object.__setattr__(self, "end", _utc(self.end, "end"))
        validate_step_s(self.step_s)
        if self.end < self.start:
            raise ValueError(f"Grid end {self.end} is before its start {self.start}.")
        times = pd.date_range(self.start, self.end, freq=self.step, name=str(Column.TIMESTAMP))
        object.__setattr__(self, "_times", times.as_unit("ns"))

    @classmethod
    def from_series(
        cls,
        series: Sequence[MeasurementSeries],
        policy: GridPolicy,
        exclude_mask: int,
    ) -> TimeGrid | None:
        """Derive a grid from the usable samples of several series.

        A row is usable if its ``qc`` flags are not in ``exclude_mask`` and at least one of
        ``temp_c`` and ``rh_pct`` is not ``NaN``. Series without usable rows do not contribute
        a span.

        Parameters
        ----------
        series : sequence of MeasurementSeries
            The series to cover.
        policy : GridPolicy
            Step and span rule.
        exclude_mask : int
            :class:`~sivin.core.flags.QcFlag` bits that make a row unusable.

        Returns
        -------
        TimeGrid or None
            The grid, or ``None`` if the span rule finds no span (no usable data, or no
            overlap).
        """
        spans = [span for one in series if (span := usable_span(one, exclude_mask)) is not None]
        return policy.grid_for(spans)

    @property
    def step(self) -> pd.Timedelta:
        """The step as a :class:`pandas.Timedelta`."""
        return pd.Timedelta(seconds=self.step_s)

    @property
    def times(self) -> pd.DatetimeIndex:
        """The grid points, ``datetime64[ns, UTC]``, named ``timestamp_utc`` (computed once)."""
        return self._times

    @property
    def times_ns(self) -> npt.NDArray[np.int64]:
        """The grid points as integer nanoseconds since the Unix epoch."""
        return epoch_ns(self.times)

    def __len__(self) -> int:
        return len(self._times)


class SpanRule(ABC):
    """Extension point: which time span a grid covers, given the spans of several series.

    Span rules are stateless; two instances of the same class compare equal.
    """

    rule_id: ClassVar[str]
    """Identifier under which the rule is registered (e.g. in the configuration)."""

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other)

    def __hash__(self) -> int:
        return hash(type(self))

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    @abstractmethod
    def bounds(self, spans: Sequence[DataSpan], step: pd.Timedelta) -> DataSpan | None:
        """Return the first and last grid point for the given data spans.

        Parameters
        ----------
        spans : sequence of (pandas.Timestamp, pandas.Timestamp)
            First and last usable instant (UTC) of every series that has data; may be empty.
        step : pandas.Timedelta
            Grid step; returned bounds are multiples of it since the Unix epoch.

        Returns
        -------
        (pandas.Timestamp, pandas.Timestamp) or None
            Inclusive grid bounds, or ``None`` if there is nothing to cover.
        """


span_registry: Final = ClassRegistry[SpanRule](SpanRule, "rule_id", "span rule")
"""Registry of :class:`SpanRule` implementations, keyed by ``rule_id``."""


@span_registry.register
class UnionSpan(SpanRule):
    """Cover the time when *any* series has data, widened outwards to grid points.

    Use it when no data should be dropped, e.g. for charts; grid points where some sensors have
    no data stay invalid for them.
    """

    rule_id: ClassVar[str] = "union"

    def bounds(self, spans: Sequence[DataSpan], step: pd.Timedelta) -> DataSpan | None:
        """See :meth:`SpanRule.bounds`."""
        if not spans:
            return None
        first = min(start for start, _ in spans).floor(step)
        last = max(end for _, end in spans).ceil(step)
        return first, last


@span_registry.register
class OverlapSpan(SpanRule):
    """Cover only the time when *every* series has data, narrowed inwards to grid points.

    Use it for comparisons that need all sensors at once (neighbour checks, spatial analysis).
    Series without usable data are not counted, so they do not empty the overlap.
    """

    rule_id: ClassVar[str] = "overlap"

    def bounds(self, spans: Sequence[DataSpan], step: pd.Timedelta) -> DataSpan | None:
        """See :meth:`SpanRule.bounds`."""
        if not spans:
            return None
        first = max(start for start, _ in spans).ceil(step)
        last = min(end for _, end in spans).floor(step)
        if last < first:
            logger.warning("The series do not overlap on a common grid point; no grid.")
            return None
        return first, last


@dataclass(frozen=True, slots=True)
class GridPolicy:
    """How a :class:`TimeGrid` is derived from data: step and span rule.

    Parameters
    ----------
    step_s : float
        Grid step in seconds, at least 1 s and a whole number of nanoseconds. Default 1800 s
        (30 min, MIGRATION_PLAN §2.7).
    span : SpanRule
        Which span to cover. Default :class:`UnionSpan`.
    """

    step_s: float = DEFAULT_GRID_STEP_S
    span: SpanRule = field(default_factory=UnionSpan)

    def __post_init__(self) -> None:
        validate_step_s(self.step_s)

    def grid_for(self, spans: Sequence[DataSpan]) -> TimeGrid | None:
        """Build the grid covering ``spans`` according to the span rule.

        Parameters
        ----------
        spans : sequence of (pandas.Timestamp, pandas.Timestamp)
            First and last usable instant (UTC) of every series that has data.

        Returns
        -------
        TimeGrid or None
            The grid, or ``None`` if the span rule finds nothing to cover.
        """
        step = pd.Timedelta(seconds=self.step_s)
        bounds = self.span.bounds(spans, step)
        if bounds is None:
            return None
        return TimeGrid(bounds[0], bounds[1], self.step_s)


def validate_step_s(step_s: float) -> float:
    """Check that a grid step is usable.

    Parameters
    ----------
    step_s : float
        Grid step in seconds.

    Returns
    -------
    float
        ``step_s`` unchanged.

    Raises
    ------
    ValueError
        If ``step_s`` is not finite, below :data:`MIN_GRID_STEP_S` (1 s) or not a whole number
        of nanoseconds.
    """
    if not (math.isfinite(step_s) and step_s >= MIN_GRID_STEP_S):
        raise ValueError(
            f"Grid step must be finite and at least {MIN_GRID_STEP_S} s, got {step_s}."
        )
    step_ns = step_s * _NS_PER_S
    if abs(step_ns - round(step_ns)) > _WHOLE_NS_TOLERANCE:
        raise ValueError(f"Grid step must be a whole number of nanoseconds, got {step_s} s.")
    return step_s


def usable_span(series: MeasurementSeries, exclude_mask: int) -> DataSpan | None:
    """Return the first and last usable instant of a series.

    Parameters
    ----------
    series : MeasurementSeries
        The series.
    exclude_mask : int
        :class:`~sivin.core.flags.QcFlag` bits that make a row unusable.

    Returns
    -------
    (pandas.Timestamp, pandas.Timestamp) or None
        Inclusive span (UTC), or ``None`` if no row is usable (see
        :meth:`TimeGrid.from_series`).
    """
    frame = series.frame
    has_value = frame[Column.TEMP].notna() | frame[Column.RH].notna()
    times = frame.loc[series.valid_mask(exclude_mask) & has_value, Column.TIMESTAMP]
    if times.empty:
        return None
    return times.iloc[0], times.iloc[-1]


def epoch_ns(times: pd.DatetimeIndex | pd.Series) -> npt.NDArray[np.int64]:
    """Convert timezone-aware instants to integer nanoseconds since the Unix epoch.

    Parameters
    ----------
    times : pandas.DatetimeIndex or pandas.Series
        Timezone-aware instants.

    Returns
    -------
    numpy.ndarray of int64
        Nanoseconds since 1970-01-01T00:00:00Z.
    """
    naive_utc = pd.DatetimeIndex(times).tz_convert("UTC").tz_localize(None).as_unit("ns")
    return naive_utc.to_numpy(dtype="datetime64[ns]").astype(np.int64)


def _utc(value: pd.Timestamp, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tz is None:
        raise ValueError(f"Grid {name} must be timezone-aware, got {value!r}.")
    return timestamp.tz_convert("UTC").as_unit("ns")
