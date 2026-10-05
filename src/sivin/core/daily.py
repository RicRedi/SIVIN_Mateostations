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
"""Temperature and humidity columns of :attr:`DailyWeather.frame` (site contract, §2.6).

These columns are required by the constructor. :data:`AUXILIARY_DAILY_COLUMNS` follow them.
"""

AUXILIARY_DAILY_COLUMNS: Final = ("precip_sum_mm", "battery_min_v")
"""Daily aggregates of the auxiliary variables (WP-1.9), after :data:`DAILY_COLUMNS`.

Optional on input: a frame without them gets ``NaN`` columns, so frames built before WP-1.9
(e.g. ``frame[list(DAILY_COLUMNS)]``) still construct a :class:`DailyWeather`.
"""

ALL_DAILY_COLUMNS: Final = (*DAILY_COLUMNS, *AUXILIARY_DAILY_COLUMNS)
"""All columns of :attr:`DailyWeather.frame`, in order."""

COUNT_COLUMNS: Final = ("temp_n_samples", "rh_n_samples", "n_samples")
"""Integer columns (``int64``); all other columns are ``float64``."""

COVERAGE_COLUMNS: Final = ("temp_coverage", "rh_coverage", "coverage")
"""Columns holding a share of the day, 0-1."""

DATE_INDEX_NAME: Final = "date"
"""Name of the index of :attr:`DailyWeather.frame` (local calendar date)."""

_VARIABLES: Final = (("temp", Column.TEMP), ("rh", Column.RH))
"""Column-name prefix and source column of each aggregated variable."""

_ROW_LEVEL_ALIAS_PREFIXES: Final = ("temp_", "rh_")
"""Prefixes of the per-variable count and coverage columns, which equal the row-level ones."""


class DailyWeather:
    """Daily aggregates of one sensor, by local calendar day of a display time zone.

    **Whole-row validity** (owner decision 2026-10-05, MIGRATION_PLAN §0.5): a sample counts
    only if **both** its temperature and its humidity are present (not ``NaN``) and no flag of
    the exclusion mask is set on its row (:meth:`MeasurementSeries.complete_mask`). A missing
    humidity value therefore also discards the temperature of the same sample, and vice versa.

    The frame is indexed by local date (:class:`datetime.date`, index name ``date``) and covers
    every day from the first to the last sample; days without valid values are present with
    zero counts, zero coverage and ``NaN`` aggregates.

    ===================  =====  ==========================================================
    column               unit   meaning
    ===================  =====  ==========================================================
    ``temp_min``         °C     minimum of the temperatures of the valid samples
    ``temp_mean``        °C     **arithmetic mean of the temperatures of the valid samples**
                                (not ``(min + max) / 2``)
    ``temp_max``         °C     maximum of the temperatures of the valid samples
    ``rh_min``           %      minimum of the humidities of the valid samples
    ``rh_mean``          %      arithmetic mean of the humidities of the valid samples
    ``rh_max``           %      maximum of the humidities of the valid samples
    ``n_samples``        —      number of valid samples
    ``coverage``         0-1    ``min(1, n_samples * expected_interval_s / day_length_s)``
    ``temp_n_samples``   —      equal to ``n_samples``
    ``rh_n_samples``     —      equal to ``n_samples``
    ``temp_coverage``    0-1    equal to ``coverage``
    ``rh_coverage``      0-1    equal to ``coverage``
    ``precip_sum_mm``    mm     sum of ``precip_mm`` of the valid samples; ``NaN`` if none
                                of them has a precipitation value
    ``battery_min_v``    V      minimum of ``battery_v`` of the valid samples; ``NaN`` if
                                none of them has a battery value
    ===================  =====  ==========================================================

    The two auxiliary aggregates use the same valid samples as temperature and humidity, so a
    day's precipitation sum covers the same part of the day as ``coverage``. A missing
    precipitation or battery value does not make a sample invalid (owner decision Q9); it is
    only left out of the sum or minimum. Precipitation recorded in a sample without
    temperature or humidity, or in an excluded sample (e.g. ``PRE_DEPLOYMENT``), is not
    counted.

    The per-variable columns ``temp_*``/``rh_*`` of counts and coverage are kept for API
    stability (they were independent before 2026-10-05); under the whole-row rule they always
    equal ``n_samples`` and ``coverage``, and the constructor enforces that. ``coverage`` is
    the column of the site contract (§2.6) and the one :meth:`complete_days` uses.
    ``day_length_s`` is the real length of the local day, i.e. 23 h or 25 h on daylight-saving
    transition days.

    Parameters
    ----------
    sensor_id : SensorId
        The sensor the aggregates belong to.
    frame : pandas.DataFrame
        Aggregates with the columns above, indexed by unique increasing local dates. The two
        auxiliary columns may be omitted (both or either); they are then filled with ``NaN``.
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
            Nominal sampling interval in seconds (e.g. 1830 s), used for ``coverage``.
        exclude_mask : int
            :class:`~sivin.core.flags.QcFlag` bits that exclude a sample. A sample without
            temperature or without humidity is excluded regardless of its flags; one without
            precipitation or battery voltage is not.

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
        valid = series.complete_mask(exclude_mask)
        all_days = pd.Index(
            pd.date_range(dates.iloc[0], dates.iloc[-1], freq="D").date, name=DATE_INDEX_NAME
        )
        day_length_s = np.array([converter.day_length_s(day) for day in all_days])
        daily = pd.DataFrame(index=all_days)
        valid_dates = dates.loc[valid]
        for prefix, column in _VARIABLES:
            grouped = frame.loc[valid, column].groupby(valid_dates)
            for statistic in ("min", "mean", "max"):
                daily[f"{prefix}_{statistic}"] = grouped.agg(statistic).astype(np.float64)
        precip = frame.loc[valid, Column.PRECIP].groupby(valid_dates)
        daily["precip_sum_mm"] = precip.sum(min_count=1).astype(np.float64)
        daily["battery_min_v"] = (
            frame.loc[valid, Column.BATTERY].groupby(valid_dates).min().astype(np.float64)
        )
        counts = valid_dates.groupby(valid_dates).size()
        n_samples = counts.reindex(all_days, fill_value=0).astype(np.int64)
        coverage = np.minimum(1.0, n_samples.to_numpy() * expected_interval_s / day_length_s)
        for prefix in (*_ROW_LEVEL_ALIAS_PREFIXES, ""):
            daily[f"{prefix}n_samples"] = n_samples
            daily[f"{prefix}coverage"] = coverage
        return cls(series.sensor_id, daily[list(ALL_DAILY_COLUMNS)], timezone)

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
        {name: pd.Series(dtype=np.float64) for name in ALL_DAILY_COLUMNS},
        index=pd.Index([], dtype=object, name=DATE_INDEX_NAME),
    )
    for column in COUNT_COLUMNS:
        frame[column] = frame[column].astype(np.int64)
    return frame


def _validated_daily(frame: pd.DataFrame) -> pd.DataFrame:
    given = [str(column) for column in frame.columns]
    expected = [*DAILY_COLUMNS, *(c for c in AUXILIARY_DAILY_COLUMNS if c in given)]
    if given != expected:
        raise SchemaError(
            f"Daily frame must have columns {list(DAILY_COLUMNS)}, optionally followed by "
            f"{list(AUXILIARY_DAILY_COLUMNS)}, got {given}."
        )
    frame = frame.copy()
    for column in AUXILIARY_DAILY_COLUMNS:
        if column not in given:
            frame[column] = np.full(len(frame), np.nan, dtype=np.float64)
    if not all(type(day) is date for day in frame.index):
        raise SchemaError("Daily frame must be indexed by datetime.date values.")
    if not (frame.index.is_unique and frame.index.is_monotonic_increasing):
        raise SchemaError("Daily frame index must be unique and increasing.")
    for column in ALL_DAILY_COLUMNS:
        expected_dtype = np.int64 if column in COUNT_COLUMNS else np.float64
        if frame[column].dtype != expected_dtype:
            raise SchemaError(
                f"Daily column '{column}' must be {np.dtype(expected_dtype)}, "
                f"got {frame[column].dtype}."
            )
    if (frame[list(COUNT_COLUMNS)] < 0).to_numpy().any():
        raise SchemaError("Daily sample counts must not be negative.")
    coverages = frame[list(COVERAGE_COLUMNS)].to_numpy()
    if np.isnan(coverages).any() or (coverages < 0).any() or (coverages > 1).any():
        raise SchemaError("Daily coverage must be within 0-1.")
    for prefix in _ROW_LEVEL_ALIAS_PREFIXES:
        if not (
            frame["n_samples"].equals(frame[f"{prefix}n_samples"])
            and frame["coverage"].equals(frame[f"{prefix}coverage"])
        ):
            raise SchemaError(
                f"'{prefix}n_samples' and '{prefix}coverage' must equal 'n_samples' and "
                "'coverage' (whole-row validity)."
            )
    copy = frame[list(ALL_DAILY_COLUMNS)].copy()
    copy.columns = pd.Index(list(ALL_DAILY_COLUMNS))
    copy.index = pd.Index(list(frame.index), dtype=object, name=DATE_INDEX_NAME)
    return copy
