"""Daily weather aggregates of one sensor (input of most climate indices)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Final, Self

import numpy as np
import pandas as pd

from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries, SchemaError
from sivin.core.timeutil import LocalTimeConverter

logger = logging.getLogger(__name__)

DAILY_COLUMNS: Final = (
    "temp_min",
    "temp_mean",
    "temp_max",
    "rh_min",
    "rh_mean",
    "rh_max",
    "n_samples",
    "coverage",
)
"""Columns of :attr:`DailyWeather.frame`; names follow the site contract (MIGRATION_PLAN §2.6)."""

DATE_INDEX_NAME: Final = "date"
"""Name of the index of :attr:`DailyWeather.frame` (local calendar date)."""

_AGGREGATES: Final = {
    "temp_min": (Column.TEMP, "min"),
    "temp_mean": (Column.TEMP, "mean"),
    "temp_max": (Column.TEMP, "max"),
    "rh_min": (Column.RH, "min"),
    "rh_mean": (Column.RH, "mean"),
    "rh_max": (Column.RH, "max"),
    "n_samples": (Column.TEMP, "size"),
}


class DailyWeather:
    """Daily aggregates of one sensor, by local calendar day of a display time zone.

    The frame is indexed by local date (:class:`datetime.date`, index name ``date``) and covers
    every day from the first to the last sample; days without a valid sample are present with
    ``n_samples = 0``, ``coverage = 0`` and ``NaN`` aggregates.

    ==============  =====  ===============================================================
    column          unit   meaning
    ==============  =====  ===============================================================
    ``temp_min``    °C     minimum of the valid samples
    ``temp_mean``   °C     **arithmetic mean of the valid samples** (not ``(min + max) / 2``)
    ``temp_max``    °C     maximum of the valid samples
    ``rh_min``      %      minimum of the valid samples
    ``rh_mean``     %      arithmetic mean of the valid samples
    ``rh_max``      %      maximum of the valid samples
    ``n_samples``   —      number of valid samples
    ``coverage``    0-1    ``min(1, n_samples * expected_interval_s / day_length_s)``
    ==============  =====  ===============================================================

    A sample is *valid* when no flag of the exclusion mask is set and both ``temp_c`` and
    ``rh_pct`` are present (not ``NaN``). ``day_length_s`` is the real length of the local day,
    i.e. 23 h or 25 h on daylight-saving transition days.

    Parameters
    ----------
    sensor_id : SensorId
        The sensor the aggregates belong to.
    frame : pandas.DataFrame
        Aggregates with exactly the columns above, indexed by unique increasing local dates.
    timezone : str
        IANA zone that defines the local calendar days.

    Raises
    ------
    SchemaError
        If the frame does not have the expected columns or index.
    """

    __slots__ = ("_frame", "_sensor_id", "_timezone")

    def __init__(self, sensor_id: SensorId, frame: pd.DataFrame, timezone: str) -> None:
        self._sensor_id = sensor_id
        self._timezone = LocalTimeConverter(timezone).timezone
        self._frame = _validated_daily(frame)

    @classmethod
    def from_series(
        cls,
        series: MeasurementSeries,
        timezone: str,
        expected_interval_s: float,
        exclude_mask: int,
    ) -> Self:
        """Aggregate a measurement series to local calendar days.

        Parameters
        ----------
        series : MeasurementSeries
            Measurements of one sensor.
        timezone : str
            IANA zone defining the calendar days, e.g. ``"Europe/Prague"``.
        expected_interval_s : float
            Nominal sampling interval in seconds (e.g. 1825 s), used for ``coverage``.
        exclude_mask : int
            :class:`~sivin.core.flags.QcFlag` bits that exclude a sample.

        Returns
        -------
        DailyWeather
            One row per local day from the first to the last sample.

        Raises
        ------
        ValueError
            If ``expected_interval_s`` is not positive.
        """
        if expected_interval_s <= 0:
            raise ValueError(f"expected_interval_s must be positive, got {expected_interval_s}.")
        converter = LocalTimeConverter(timezone)
        if series.is_empty:
            return cls(series.sensor_id, _empty_daily_frame(), timezone)
        frame = series.frame
        dates = converter.local_dates(frame[Column.TIMESTAMP])
        valid = (
            series.valid_mask(exclude_mask) & frame[Column.TEMP].notna() & frame[Column.RH].notna()
        )
        grouped = frame.loc[valid].groupby(dates.loc[valid])
        daily = pd.DataFrame(
            {name: grouped[column].agg(how) for name, (column, how) in _AGGREGATES.items()}
        )
        all_days = pd.Index(
            pd.date_range(dates.iloc[0], dates.iloc[-1], freq="D").date, name=DATE_INDEX_NAME
        )
        daily = daily.reindex(all_days)
        daily["n_samples"] = daily["n_samples"].fillna(0).astype(np.int64)
        day_length_s = np.array([converter.day_length_s(day) for day in all_days])
        daily["coverage"] = np.minimum(
            1.0, daily["n_samples"].to_numpy() * expected_interval_s / day_length_s
        )
        return cls(series.sensor_id, daily, timezone)

    @property
    def sensor_id(self) -> SensorId:
        """The sensor the aggregates belong to."""
        return self._sensor_id

    @property
    def timezone(self) -> str:
        """IANA zone that defines the local calendar days."""
        return self._timezone

    @property
    def frame(self) -> pd.DataFrame:
        """A copy of the daily aggregates, indexed by local date."""
        return self._frame.copy()

    @property
    def dates(self) -> list[date]:
        """The local dates of the rows, in increasing order."""
        return list(self._frame.index)

    def __len__(self) -> int:
        return len(self._frame)

    def __repr__(self) -> str:
        return (
            f"DailyWeather(sensor_id={self._sensor_id}, timezone={self._timezone!r}, "
            f"days={len(self)})"
        )

    def complete_days(self, min_coverage: float) -> Self:
        """Keep only days whose coverage reaches a threshold.

        Parameters
        ----------
        min_coverage : float
            Minimum share of the day covered by valid samples, 0-1.

        Returns
        -------
        DailyWeather
            A new instance with days where ``coverage >= min_coverage``.
        """
        return self._derived(self._frame.loc[self._frame["coverage"] >= min_coverage])

    def between(self, start_date: date, end_date: date) -> Self:
        """Keep only days with ``start_date <= date <= end_date``.

        Parameters
        ----------
        start_date, end_date : datetime.date
            Inclusive bounds (local dates).

        Returns
        -------
        DailyWeather
            A new instance with the selected days.
        """
        dates = pd.Series(self._frame.index, index=self._frame.index)
        return self._derived(self._frame.loc[(dates >= start_date) & (dates <= end_date)])

    def _derived(self, frame: pd.DataFrame) -> Self:
        return type(self)(self._sensor_id, frame, self._timezone)


def _empty_daily_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        {name: pd.Series(dtype=np.float64) for name in DAILY_COLUMNS},
        index=pd.Index([], dtype=object, name=DATE_INDEX_NAME),
    )
    frame["n_samples"] = frame["n_samples"].astype(np.int64)
    return frame


def _validated_daily(frame: pd.DataFrame) -> pd.DataFrame:
    if list(frame.columns) != list(DAILY_COLUMNS):
        raise SchemaError(
            f"Daily frame must have columns {list(DAILY_COLUMNS)}, got {list(frame.columns)}."
        )
    if not all(type(day) is date for day in frame.index):
        raise SchemaError("Daily frame must be indexed by datetime.date values.")
    if not (frame.index.is_unique and frame.index.is_monotonic_increasing):
        raise SchemaError("Daily frame index must be unique and increasing.")
    copy = frame.copy()
    copy.index = pd.Index(list(frame.index), dtype=object, name=DATE_INDEX_NAME)
    return copy
