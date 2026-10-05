"""Time represented by each raw sample, for duration-weighted hour metrics.

The sensors sample about every 1825 s, but not exactly, and samples go missing. Counting rows
(as the legacy ``frost_events_count`` did) therefore does not measure time. Here each sample is
read as a step function (zero-order hold): its value holds from its own timestamp until the next
sample of the series, at most ``max_sample_duration_s``. Hours in a temperature band are the
summed durations of the samples whose value lies in the band.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.analytics.ripening.params import SampleDurationParams
from sivin.core.schema import Column, MeasurementSeries
from sivin.core.timeutil import LocalTimeConverter

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR: Final = 3600.0
"""Seconds in one hour."""

_NS_PER_S: Final = 1_000_000_000
"""Nanoseconds in one second."""

PIECE_COLUMNS: Final = ("date", "duration_s", "value")
"""Columns of :meth:`SampleDurations.pieces`."""

type FloatArray = npt.NDArray[np.float64]
"""One-dimensional array of ``float64`` values."""

type Condition = Callable[[FloatArray], npt.NDArray[np.bool_]]
"""Element-wise test of sample values, e.g. ``lambda temp_c: temp_c <= 0.0``."""


def masked_values(series: MeasurementSeries, column: Column, exclude_mask: int) -> FloatArray:
    """Return one column of a series with excluded samples set to ``NaN``.

    Parameters
    ----------
    series : MeasurementSeries
        Raw measurements.
    column : Column
        ``Column.TEMP`` (°C) or ``Column.RH`` (%).
    exclude_mask : int
        :class:`~sivin.core.flags.QcFlag` bits that exclude a sample.

    Returns
    -------
    numpy.ndarray of float
        Values in the unit of ``column``, aligned with the rows of ``series``; ``NaN`` where the
        value is missing or the row is excluded.
    """
    values = series.frame[column].to_numpy(dtype=np.float64, copy=True)
    values[~series.valid_mask(exclude_mask).to_numpy()] = np.nan
    return values


class SampleDurations:
    """Split the time covered by valid samples into pieces per local calendar day.

    Sample ``i`` represents the interval ``[t_i, t_i + d_i)`` with
    ``d_i = min(t_{i+1} - t_i, max_sample_duration_s)``; the last sample of the series has
    ``d = min(last_sample_duration_s, max_sample_duration_s)``. Durations are taken from the
    whole series (excluded rows included), so an excluded or missing value leaves its own
    interval uncounted instead of stretching its predecessor. An interval that crosses a local
    midnight is split there, so every piece belongs to exactly one local day.

    Parameters
    ----------
    params : SampleDurationParams
        Duration caps.
    timezone : str
        IANA zone that defines the local calendar days.
    """

    __slots__ = ("_converter", "_params")

    def __init__(self, params: SampleDurationParams, timezone: str) -> None:
        self._params = params
        self._converter = LocalTimeConverter(timezone)

    @property
    def params(self) -> SampleDurationParams:
        """The duration caps."""
        return self._params

    def durations_s(self, series: MeasurementSeries) -> FloatArray:
        """Return the duration each row of a series represents.

        Parameters
        ----------
        series : MeasurementSeries
            Raw measurements.

        Returns
        -------
        numpy.ndarray of float
            Duration in seconds per row, before the split at local midnight.
        """
        times_ns = _utc_ns(series)
        if times_ns.size == 0:
            return np.empty(0, dtype=np.float64)
        gaps_s = np.diff(times_ns).astype(np.float64) / _NS_PER_S
        gaps_s = np.append(gaps_s, self._params.last_sample_duration_s)
        capped: FloatArray = np.minimum(gaps_s, self._params.max_sample_duration_s)
        return capped

    def pieces(self, series: MeasurementSeries, values: FloatArray) -> pd.DataFrame:
        """Return the time covered by the valid samples, split at local midnight.

        Parameters
        ----------
        series : MeasurementSeries
            Raw measurements; only the timestamps are used.
        values : numpy.ndarray of float
            One value per row of ``series`` (any unit); ``NaN`` marks a row that does not count.

        Returns
        -------
        pandas.DataFrame
            Columns ``date`` (local :class:`datetime.date`), ``duration_s`` (s) and ``value``
            (the sample value); one row per sample, two for a sample crossing midnight.

        Raises
        ------
        ValueError
            If ``values`` does not have one element per row.
        """
        if values.shape != (len(series),):
            raise ValueError(f"Expected {len(series)} values, got shape {values.shape}.")
        valid = ~np.isnan(values)
        if not valid.any():
            return _empty_pieces()
        starts_ns = _utc_ns(series)[valid]
        ends_ns = starts_ns + np.round(self.durations_s(series)[valid] * _NS_PER_S).astype(np.int64)
        sample_values = values[valid]
        days, midnights_ns = self._midnights(starts_ns[0], ends_ns[-1])
        next_midnight = np.searchsorted(midnights_ns, starts_ns, side="right")
        first_end_ns = np.minimum(ends_ns, midnights_ns[next_midnight])
        crosses = ends_ns > midnights_ns[next_midnight]
        day_array = np.asarray(days, dtype=object)
        return pd.DataFrame(
            {
                "date": np.concatenate(
                    [day_array[next_midnight - 1], day_array[next_midnight[crosses]]]
                ),
                "duration_s": np.concatenate(
                    [
                        (first_end_ns - starts_ns) / _NS_PER_S,
                        (ends_ns[crosses] - midnights_ns[next_midnight[crosses]]) / _NS_PER_S,
                    ]
                ),
                "value": np.concatenate([sample_values, sample_values[crosses]]),
            },
            columns=list(PIECE_COLUMNS),
        )

    def hours_by_day(
        self,
        series: MeasurementSeries,
        values: FloatArray,
        condition: Condition,
        days: list[date] | None = None,
    ) -> pd.Series:
        """Return per local day the hours during which ``condition`` holds.

        Parameters
        ----------
        series : MeasurementSeries
            Raw measurements; only the timestamps are used.
        values : numpy.ndarray of float
            One value per row; ``NaN`` marks a row that does not count.
        condition : callable
            Element-wise test of the values, e.g. ``lambda temp_c: temp_c <= 0.0``.
        days : list of datetime.date, optional
            Local days to report (in this order); days without data get 0 h. When omitted,
            every day with valid data is reported, in increasing order.

        Returns
        -------
        pandas.Series of float
            Hours (h) per local date, index named ``date``.
        """
        return self.sum_hours(self.pieces(series, values), condition, days)

    @staticmethod
    def sum_hours(
        pieces: pd.DataFrame, condition: Condition, days: list[date] | None = None
    ) -> pd.Series:
        """Sum the pieces whose value satisfies ``condition``, per local day.

        Parameters
        ----------
        pieces : pandas.DataFrame
            Output of :meth:`pieces` (computed once, reused for several conditions).
        condition : callable
            Element-wise test of the values.
        days : list of datetime.date, optional
            Local days to report, see :meth:`hours_by_day`.

        Returns
        -------
        pandas.Series of float
            Hours (h) per local date, index named ``date``.
        """
        selected = pieces["duration_s"].where(condition(pieces["value"].to_numpy()), 0.0)
        hours = selected.groupby(pieces["date"]).sum() / SECONDS_PER_HOUR
        if days is not None:
            hours = hours.reindex(pd.Index(days, dtype=object), fill_value=0.0)
        hours.index.name = "date"
        return hours.astype(np.float64)

    def _midnights(self, first_ns: int, last_ns: int) -> tuple[list[date], npt.NDArray[np.int64]]:
        """Local days touched by ``[first_ns, last_ns]`` and their starts, plus one more start."""
        stamps = pd.Series(pd.to_datetime([first_ns, last_ns], unit="ns", utc=True))
        first_day, last_day = self._converter.local_dates(stamps)
        days = [first_day + timedelta(days=k) for k in range((last_day - first_day).days + 2)]
        midnights = [self._converter.day_bounds_utc(day)[0].value for day in days]
        return days, np.asarray(midnights, dtype=np.int64)


def _utc_ns(series: MeasurementSeries) -> npt.NDArray[np.int64]:
    """Timestamps of a series as integer nanoseconds since the Unix epoch (UTC)."""
    return series.timestamps.to_numpy(dtype="datetime64[ns]").view(np.int64)


def _empty_pieces() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype=object),
            "duration_s": pd.Series(dtype=np.float64),
            "value": pd.Series(dtype=np.float64),
        }
    )
