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
    "temp_n_samples",
    "rh_n_samples",
    "temp_coverage",
    "rh_coverage",
    "n_samples",
    "coverage",
)
"""Columns of :attr:`DailyWeather.frame`; names follow the site contract (MIGRATION_PLAN §2.6)."""

COUNT_COLUMNS: Final = ("temp_n_samples", "rh_n_samples", "n_samples")
"""Integer columns (``int64``); all other columns are ``float64``."""

COVERAGE_COLUMNS: Final = ("temp_coverage", "rh_coverage", "coverage")
"""Columns holding a share of the day, 0-1."""

DATE_INDEX_NAME: Final = "date"
"""Name of the index of :attr:`DailyWeather.frame` (local calendar date)."""

_VARIABLES: Final = (("temp", Column.TEMP), ("rh", Column.RH))
"""Column-name prefix and source column of each aggregated variable."""


class DailyWeather:
    """Daily aggregates of one sensor, by local calendar day of a display time zone.

    Temperature and humidity are aggregated **independently**: a value is *valid* when it is
    present (not ``NaN``) and no flag of the exclusion mask is set on its row. A missing
    humidity value therefore does not discard the temperature of the same sample.

    The frame is indexed by local date (:class:`datetime.date`, index name ``date``) and covers
    every day from the first to the last sample; days without valid values are present with
    zero counts, zero coverage and ``NaN`` aggregates.

    ===================  =====  ==========================================================
    column               unit   meaning
    ===================  =====  ==========================================================
    ``temp_min``         °C     minimum of the valid temperatures
    ``temp_mean``        °C     **arithmetic mean of the valid temperatures**
                                (not ``(min + max) / 2``)
    ``temp_max``         °C     maximum of the valid temperatures
    ``rh_min``           %      minimum of the valid humidities
    ``rh_mean``          %      arithmetic mean of the valid humidities
    ``rh_max``           %      maximum of the valid humidities
    ``temp_n_samples``   —      number of valid temperatures
    ``rh_n_samples``     —      number of valid humidities
    ``temp_coverage``    0-1    ``min(1, temp_n_samples * expected_interval_s / day_length_s)``
    ``rh_coverage``      0-1    the same for humidity
    ``n_samples``        —      equal to ``temp_n_samples``
    ``coverage``         0-1    equal to ``temp_coverage``
    ===================  =====  ==========================================================

    ``n_samples`` and ``coverage`` are the temperature values because nearly all indices are
    temperature-based; ``coverage`` is the column of the site contract (§2.6) and the one
    :meth:`complete_days` uses. ``day_length_s`` is the real length of the local day, i.e.
    23 h or 25 h on daylight-saving transition days.

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
        If the frame does not have the expected columns, dtypes, value ranges or index.
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
        not_excluded = series.valid_mask(exclude_mask)
        all_days = pd.Index(
            pd.date_range(dates.iloc[0], dates.iloc[-1], freq="D").date, name=DATE_INDEX_NAME
        )
        day_length_s = np.array([converter.day_length_s(day) for day in all_days])
        daily = pd.DataFrame(index=all_days)
        for prefix, column in _VARIABLES:
            valid = not_excluded & frame[column].notna()
            grouped = frame.loc[valid, column].groupby(dates.loc[valid])
            for statistic in ("min", "mean", "max"):
                daily[f"{prefix}_{statistic}"] = grouped.agg(statistic).astype(np.float64)
            counts = grouped.size().reindex(all_days, fill_value=0).astype(np.int64)
            daily[f"{prefix}_n_samples"] = counts
            daily[f"{prefix}_coverage"] = np.minimum(
                1.0, counts.to_numpy() * expected_interval_s / day_length_s
            )
        daily["n_samples"] = daily["temp_n_samples"]
        daily["coverage"] = daily["temp_coverage"]
        return cls(series.sensor_id, daily[list(DAILY_COLUMNS)], timezone)

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
    for column in COUNT_COLUMNS:
        frame[column] = frame[column].astype(np.int64)
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
    for column in DAILY_COLUMNS:
        expected = np.int64 if column in COUNT_COLUMNS else np.float64
        if frame[column].dtype != expected:
            raise SchemaError(
                f"Daily column '{column}' must be {np.dtype(expected)}, got {frame[column].dtype}."
            )
    if (frame[list(COUNT_COLUMNS)] < 0).to_numpy().any():
        raise SchemaError("Daily sample counts must not be negative.")
    coverages = frame[list(COVERAGE_COLUMNS)].to_numpy()
    if np.isnan(coverages).any() or (coverages < 0).any() or (coverages > 1).any():
        raise SchemaError("Daily coverage must be within 0-1.")
    if not (
        frame["n_samples"].equals(frame["temp_n_samples"])
        and frame["coverage"].equals(frame["temp_coverage"])
    ):
        raise SchemaError("'n_samples' and 'coverage' must equal the temperature columns.")
    copy = frame.copy()
    copy.columns = pd.Index([str(column) for column in frame.columns])
    copy.index = pd.Index(list(frame.index), dtype=object, name=DATE_INDEX_NAME)
    return copy
