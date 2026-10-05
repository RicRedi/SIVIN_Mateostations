"""Climate indices of a season: QC'd data → daily weather → index context → results file."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import pandas as pd

from sivin.analytics.base import ClimateIndex, IndexContext, IndexRegistry, IndexResult
from sivin.app.json_files import JsonFileWriter
from sivin.app.outcome import Outcome, UnknownIndexError
from sivin.app.quality import SENSOR_ERRORS, QualityService
from sivin.config.sections import AnalyticsConfig, TimeConfig
from sivin.core.daily import DailyWeather
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries
from sivin.core.timeutil import LocalTimeConverter
from sivin.quality.pipeline import QualityResult
from sivin.registry.model import Placement
from sivin.registry.registry import SensorRegistry

logger = logging.getLogger(__name__)

PREVIOUS_YEARS_LOADED: Final = 1
"""Calendar years before the season year loaded into the index context (count).

``winter_freeze`` of season *N* covers the winter ending in *N*, from November of *N - 1*
(``docs/indices/winter_freeze.md``); loading the whole previous year covers any configured
start of the dormant season."""

INDICES_SUFFIX: Final = ".json"
"""File suffix of a derived indices file, ``<season>.json``."""

_LAST_MONTH: Final = 12
_LAST_DAY: Final = 31


@dataclass(frozen=True, slots=True)
class SeasonWindow:
    """The local calendar days whose data an index context of a season holds.

    Attributes
    ----------
    season : int
        The season year.
    first : datetime.date
        January 1 of ``season - PREVIOUS_YEARS_LOADED``.
    last : datetime.date
        December 31 of ``season``.
    """

    season: int
    first: date
    last: date

    @classmethod
    def of(cls, season: int) -> SeasonWindow:
        """Return the window of a season year.

        Parameters
        ----------
        season : int
            The season year.

        Returns
        -------
        SeasonWindow
            From January 1 of the previous year to December 31 of the season year.
        """
        return cls(
            season, date(season - PREVIOUS_YEARS_LOADED, 1, 1), date(season, _LAST_MONTH, _LAST_DAY)
        )

    def bounds_utc(self, timezone: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Return the inclusive UTC bounds of the window's local days.

        Parameters
        ----------
        timezone : str
            IANA zone of the local days (``time.display_timezone``).

        Returns
        -------
        tuple of pandas.Timestamp
            First instant of :attr:`first` and the last nanosecond of :attr:`last`.
        """
        converter = LocalTimeConverter(timezone)
        start, _ = converter.day_bounds_utc(self.first)
        _, end = converter.day_bounds_utc(self.last)
        return start, end - pd.Timedelta(1, unit="ns")


class IndexContextFactory:
    """Build the :class:`~sivin.analytics.base.IndexContext` of a sensor and season.

    Parameters
    ----------
    time : TimeConfig
        Display zone (local days) and nominal interval (daily coverage).
    analytics : AnalyticsConfig
        Coverage thresholds and exclusion masks.
    registry : SensorRegistry
        Latitude and elevation come from the placement in force at the last sample.
    """

    __slots__ = ("_analytics", "_registry", "_time")

    def __init__(
        self, time: TimeConfig, analytics: AnalyticsConfig, registry: SensorRegistry
    ) -> None:
        self._time = time
        self._analytics = analytics
        self._registry = registry

    @property
    def timezone(self) -> str:
        """IANA zone of the local calendar days (``time.display_timezone``)."""
        return self._time.display_timezone

    def build(self, series: MeasurementSeries, season: int) -> IndexContext:
        """Return the context of one sensor's QC'd series for one season.

        Parameters
        ----------
        series : MeasurementSeries
            Quality-controlled measurements (flags set) of the season window.
        season : int
            The season year.

        Returns
        -------
        IndexContext
            Daily weather, raw series, position and the configured thresholds.
        """
        daily = DailyWeather.from_series(
            series,
            self._time.display_timezone,
            self._time.expected_interval_s,
            self._analytics.exclude_mask,
            self._analytics.auxiliary_exclude_mask,
        )
        placement = self.placement(series)
        return IndexContext(
            sensor_id=series.sensor_id,
            year=season,
            daily=daily,
            series=series,
            latitude_deg=None if placement is None else placement.lat_deg,
            elevation_m=None if placement is None else placement.elevation_m,
            timezone=self._time.display_timezone,
            min_daily_coverage=self._analytics.min_daily_coverage,
            min_season_coverage=self._analytics.min_season_coverage,
            exclude_mask=self._analytics.exclude_mask,
        )

    def placement(self, series: MeasurementSeries) -> Placement | None:
        """Return the placement of the series' sensor at its last sample.

        Parameters
        ----------
        series : MeasurementSeries
            Measurements of one sensor.

        Returns
        -------
        Placement or None
            The placement in force at the last sample, else the sensor's last placement;
            ``None`` for a sensor that is not in the registry.
        """
        if series.sensor_id not in self._registry:
            return None
        sensor = self._registry.get(series.sensor_id)
        if not series.is_empty:
            found = sensor.placement_at(series.timestamps.iloc[-1])
            if found is not None:
                return found
        return sensor.last_placement


class IndexSelection:
    """The indices to compute, built from ``analytics.indices``.

    Parameters
    ----------
    registry : IndexRegistry
        The registered indices.
    params : Mapping of str to Mapping
        Resolved parameters per index id (``analytics.indices``).
    """

    __slots__ = ("_params", "_registry")

    def __init__(self, registry: IndexRegistry, params: Mapping[str, Mapping[str, Any]]) -> None:
        self._registry = registry
        self._params = params

    def create(self, index_ids: Sequence[str] | None = None) -> dict[str, ClimateIndex[Any]]:
        """Instantiate the requested indices with their configured parameters.

        Parameters
        ----------
        index_ids : sequence of str, optional
            Index ids; every registered index when omitted.

        Returns
        -------
        dict of str to ClimateIndex
            In the order requested (sorted ids by default).

        Raises
        ------
        UnknownIndexError
            If an id is not registered.
        """
        ids = list(dict.fromkeys(index_ids)) if index_ids else list(self._registry.ids())
        unknown = [index_id for index_id in ids if index_id not in self._registry]
        if unknown:
            raise UnknownIndexError(
                f"unknown index {', '.join(unknown)}; registered: {', '.join(self._registry.ids())}"
            )
        return {
            index_id: self._registry.create(index_id, self._params.get(index_id))
            for index_id in ids
        }


def result_dict(result: IndexResult) -> dict[str, object]:
    """Return one index result as JSON data (format in ``docs/storage.md``).

    Parameters
    ----------
    result : IndexResult
        The result.

    Returns
    -------
    dict
        ``value``, ``unit``, ``coverage``, ``complete``, ``class``, ``estimated``,
        ``details`` (the daily curve is not written).
    """
    return {
        "value": result.value,
        "unit": result.unit,
        "coverage": result.coverage,
        "complete": result.complete,
        "class": result.classification,
        "estimated": result.estimated,
        "details": dict(result.details),
    }


@dataclass(frozen=True)
class IndicesReport:
    """Outcome of :meth:`IndicesService.run`.

    Attributes
    ----------
    window : SeasonWindow
        The season and the local days loaded.
    results : Mapping of SensorId to Mapping of str to IndexResult
        Results per sensor and index id; sensors without data in the window are absent.
    failures : tuple of str
        One message per sensor or index that failed.
    file : pathlib.Path or None
        The results file (``None`` in a dry run).
    """

    window: SeasonWindow
    results: Mapping[SensorId, Mapping[str, IndexResult]] = field(default_factory=dict)
    failures: tuple[str, ...] = ()
    file: Path | None = None

    def __post_init__(self) -> None:
        frozen = {sensor: MappingProxyType(dict(r)) for sensor, r in self.results.items()}
        object.__setattr__(self, "results", MappingProxyType(frozen))

    @property
    def outcome(self) -> Outcome:
        """:attr:`Outcome.PARTIAL_FAILURE` if any sensor or index failed."""
        return Outcome.of(self.failures)

    def document(self) -> dict[str, object]:
        """Return the content of ``indices/<season>.json``.

        Returns
        -------
        dict
            ``season``, the loaded local days and ``sensors`` → index id → result.
        """
        return {
            "season": self.window.season,
            "data_from": self.window.first.isoformat(),
            "data_to": self.window.last.isoformat(),
            "sensors": {
                str(sensor): {index_id: result_dict(r) for index_id, r in results.items()}
                for sensor, results in self.results.items()
            },
        }


class IndicesService:
    """Compute the climate indices of a season for every sensor and write them.

    The measurements are quality-controlled over the sensor's whole record first (the same
    flags as ``sivin qc``), then cut to the season window.

    Parameters
    ----------
    quality : QualityService
        Reads and checks stored data.
    contexts : IndexContextFactory
        Builds the index context.
    selection : IndexSelection
        The configured indices.
    directory : pathlib.Path
        Where ``<season>.json`` is written.
    writer : JsonFileWriter, optional
        Writes the JSON atomically.
    dry_run : bool, optional
        Compute, but write no file.
    """

    __slots__ = ("_contexts", "_directory", "_dry_run", "_quality", "_selection", "_writer")

    def __init__(
        self,
        quality: QualityService,
        contexts: IndexContextFactory,
        selection: IndexSelection,
        directory: Path,
        writer: JsonFileWriter | None = None,
        dry_run: bool = False,
    ) -> None:
        self._quality = quality
        self._contexts = contexts
        self._selection = selection
        self._directory = directory
        self._writer = writer if writer is not None else JsonFileWriter()
        self._dry_run = dry_run

    def run(
        self,
        season: int,
        sensors: Sequence[SensorId] | None = None,
        index_ids: Sequence[str] | None = None,
        checked: Mapping[SensorId, QualityResult] | None = None,
    ) -> IndicesReport:
        """Compute and write the indices of one season.

        Parameters
        ----------
        season : int
            The season year.
        sensors : sequence of SensorId, optional
            Sensors; every stored sensor when omitted.
        index_ids : sequence of str, optional
            Index ids; every configured index when omitted.
        checked : Mapping of SensorId to QualityResult, optional
            QC results already computed over the whole record (``sivin run``); the others
            are checked here.

        Returns
        -------
        IndicesReport
            Results, failures and the file written.

        Raises
        ------
        UnknownIndexError
            If an index id is not registered.
        """
        indices = self._selection.create(index_ids)
        window = SeasonWindow.of(season)
        start, end = window.bounds_utc(self._contexts.timezone)
        results: dict[SensorId, dict[str, IndexResult]] = {}
        failures: list[str] = []
        for sensor_id in self._quality.sensors(sensors):
            try:
                given = (checked or {}).get(sensor_id)
                result = given if given is not None else self._quality.checked(sensor_id)
                series = result.series.between(start, end)
                if series.is_empty:
                    logger.info("Sensor %s: no data for season %d.", sensor_id, season)
                    continue
                context = self._contexts.build(series, season)
            except SENSOR_ERRORS as error:
                logger.error("Indices of sensor %s: %s", sensor_id, error)
                failures.append(f"indices {sensor_id}: {error}")
                continue
            results[sensor_id] = self._compute(context, indices, failures)
        report = IndicesReport(window, results, tuple(failures))
        if self._dry_run:
            return report
        path = self._directory / f"{season}{INDICES_SUFFIX}"
        self._writer.write(path, report.document())
        return IndicesReport(window, report.results, report.failures, path)

    @staticmethod
    def _compute(
        context: IndexContext, indices: Mapping[str, ClimateIndex[Any]], failures: list[str]
    ) -> dict[str, IndexResult]:
        computed: dict[str, IndexResult] = {}
        for index_id, index in indices.items():
            try:
                computed[index_id] = index.compute(context)
            except SENSOR_ERRORS as error:
                logger.error("Index %s of sensor %s: %s", index_id, context.sensor_id, error)
                failures.append(f"indices {context.sensor_id} {index_id}: {error}")
        return computed
