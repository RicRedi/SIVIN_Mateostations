"""Build the files and the summary of one sensor from its quality-controlled data."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from sivin.core.daily import DailyWeather
from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries
from sivin.quality.pipeline import QualityResult
from sivin.site.columns import (
    VALUE_DECIMALS,
    local_years,
    rounded_value,
    unix_second,
    utc_month_keys,
)
from sivin.site.files import SiteFile
from sivin.site.model import LatestSample, SensorData, SensorSummary
from sivin.site.sensor_files import SensorFileWriter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DailyAggregation:
    """How ``daily.json`` aggregates a sensor (the values of ``time`` and ``analytics``).

    Attributes
    ----------
    timezone : str
        IANA zone of the local calendar days (``time.display_timezone``).
    expected_interval_s : float
        Nominal sampling interval in seconds (``time.expected_interval_s``), for ``coverage``.
    exclude_mask : int
        QC flags that exclude a sample from temperature and humidity
        (``analytics.exclude_mask``).
    auxiliary_exclude_mask : int
        QC flags that exclude a sample from precipitation and battery voltage
        (``analytics.auxiliary_exclude_mask``).
    """

    timezone: str
    expected_interval_s: float
    exclude_mask: int
    auxiliary_exclude_mask: int

    def of(self, series: MeasurementSeries) -> DailyWeather:
        """Aggregate a QC'd series to local days.

        Parameters
        ----------
        series : MeasurementSeries
            Quality-controlled measurements.

        Returns
        -------
        DailyWeather
            One row per local day from the first to the last sample.
        """
        return DailyWeather.from_series(
            series,
            self.timezone,
            self.expected_interval_s,
            self.exclude_mask,
            self.auxiliary_exclude_mask,
        )


class SummaryBuilder:
    """Summarise one sensor for the manifest and ``latest.json``.

    Parameters
    ----------
    timezone : str
        IANA zone of the calendar years of the default seasons.
    exclude_mask : int
        QC flags that make a sample invalid for ``latest.json`` (``analytics.exclude_mask``);
        a valid sample also needs both temperature and humidity (whole-row rule).
    """

    __slots__ = ("_exclude_mask", "_timezone")

    def __init__(self, timezone: str, exclude_mask: int) -> None:
        self._timezone = timezone
        self._exclude_mask = exclude_mask

    def summary(self, series: MeasurementSeries) -> SensorSummary:
        """Return the summary of a non-empty QC'd series.

        Parameters
        ----------
        series : MeasurementSeries
            Quality-controlled measurements (at least one row).

        Returns
        -------
        SensorSummary
            First and last time, UTC months, last valid sample, local years.
        """
        times = series.timestamps
        months = sorted({str(month) for month in utc_month_keys(times)})
        return SensorSummary(
            first_t=unix_second(times.iloc[0]),
            last_t=unix_second(times.iloc[-1]),
            raw_months=tuple(months),
            latest=self.latest(series),
            years=local_years(times.iloc[0], times.iloc[-1], self._timezone),
        )

    def latest(self, series: MeasurementSeries) -> LatestSample | None:
        """Return the last valid sample (both values present, no excluding flag).

        Parameters
        ----------
        series : MeasurementSeries
            Quality-controlled measurements.

        Returns
        -------
        LatestSample or None
            The sample, or ``None`` if the series has no valid sample.
        """
        valid = np.flatnonzero(series.complete_mask(self._exclude_mask).to_numpy())
        if valid.size == 0:
            return None
        row = series.frame.iloc[int(valid[-1])]
        return LatestSample(
            t=unix_second(row[Column.TIMESTAMP]),
            temp_c=rounded_value(float(row[Column.TEMP]), VALUE_DECIMALS),
            rh_pct=rounded_value(float(row[Column.RH]), VALUE_DECIMALS),
            qc=int(row[Column.QC]),
        )


@dataclass(frozen=True, slots=True)
class BuiltSensor:
    """The freshly built output of one sensor.

    Attributes
    ----------
    sensor_id : SensorId
        The sensor.
    result : QualityResult
        Its QC result (kept for the indices).
    files : tuple of SiteFile
        Its per-sensor files.
    summary : SensorSummary
        Its summary.
    """

    sensor_id: SensorId
    result: QualityResult
    files: tuple[SiteFile, ...]
    summary: SensorSummary


class SensorSiteBuilder:
    """Turn the QC result of one sensor into its files and summary.

    Parameters
    ----------
    daily : DailyAggregation
        Builds the daily aggregates.
    summaries : SummaryBuilder
        Builds the summary.
    writers : sequence of SensorFileWriter
        The per-sensor file kinds (raw months, daily, events).
    """

    __slots__ = ("_daily", "_summaries", "_writers")

    def __init__(
        self,
        daily: DailyAggregation,
        summaries: SummaryBuilder,
        writers: Sequence[SensorFileWriter],
    ) -> None:
        self._daily = daily
        self._summaries = summaries
        self._writers = tuple(writers)

    def build(self, sensor_id: SensorId, result: QualityResult) -> BuiltSensor | None:
        """Build one sensor.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.
        result : QualityResult
            QC result over its whole stored record.

        Returns
        -------
        BuiltSensor or None
            Its files and summary; ``None`` (logged) if it has no samples.
        """
        series = result.series
        if series.is_empty:
            logger.info("Sensor %s: no stored data; not published.", sensor_id)
            return None
        data = SensorData(sensor_id, result, self._daily.of(series))
        files = tuple(file for writer in self._writers for file in writer.files(data))
        return BuiltSensor(sensor_id, result, files, self._summaries.summary(series))
