"""Climate indices of a season: QC'd data → daily weather → index context → results file."""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import pandas as pd

from sivin.analytics.base import ClimateIndex, IndexContext, IndexRegistry, IndexResult
from sivin.app.json_files import JsonFileWriter, read_document
from sivin.app.outcome import Outcome, UnknownIndexError
from sivin.app.quality import SENSOR_ERRORS, STATUS_FAILED, STATUS_OK, QualityService, iso_utc
from sivin.config.sections import AnalyticsConfig, TimeConfig
from sivin.core.daily import DailyWeather
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries
from sivin.core.timeutil import LocalTimeConverter
from sivin.quality.pipeline import QualityResult
from sivin.registry.model import Placement
from sivin.registry.registry import SensorRegistry

logger = logging.getLogger(__name__)

SEASON_FILE: Final = re.compile(r"[0-9]{4}\.json")
"""Name of a season file of the indices directory; other files are never touched."""

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


def result_dict(result: IndexResult, computed_at: datetime) -> dict[str, object]:
    """Return one index result as JSON data (format in ``docs/storage.md``).

    Parameters
    ----------
    result : IndexResult
        The result.
    computed_at : datetime.datetime
        Time of the computation (aware).

    Returns
    -------
    dict
        ``value``, ``unit``, ``coverage``, ``complete``, ``class``, ``estimated``,
        ``details``, ``status`` (``"ok"``) and ``computed_at`` (the daily curve is not written).
    """
    return {
        "value": result.value,
        "unit": result.unit,
        "coverage": result.coverage,
        "complete": result.complete,
        "class": result.classification,
        "estimated": result.estimated,
        "details": dict(result.details),
        "status": STATUS_OK,
        "computed_at": iso_utc(pd.Timestamp(computed_at)),
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
    errors : Mapping of SensorId to Mapping of str to str
        Index id → why it failed, per sensor (a failed sensor lists every selected index).
    failures : tuple of str
        One message per sensor or index that failed.
    file : pathlib.Path or None
        The results file, if it was written (not in a dry run, not without any result).
    """

    window: SeasonWindow
    results: Mapping[SensorId, Mapping[str, IndexResult]] = field(default_factory=dict)
    errors: Mapping[SensorId, Mapping[str, str]] = field(default_factory=dict)
    failures: tuple[str, ...] = ()
    file: Path | None = None

    def __post_init__(self) -> None:
        frozen = {sensor: MappingProxyType(dict(r)) for sensor, r in self.results.items()}
        object.__setattr__(self, "results", MappingProxyType(frozen))
        errors = {sensor: MappingProxyType(dict(e)) for sensor, e in self.errors.items()}
        object.__setattr__(self, "errors", MappingProxyType(errors))

    @property
    def outcome(self) -> Outcome:
        """:attr:`Outcome.PARTIAL_FAILURE` if any sensor or index failed."""
        return Outcome.of(self.failures)

    @property
    def changes(self) -> bool:
        """``True`` if there is a result or an error to record."""
        return bool(self.results) or bool(self.errors)


class IndicesWriter:
    """Update ``<derived>/indices/<season>.json`` in place.

    Only the computed (sensor, index) entries are replaced; every other entry of an existing
    file stays as it is, so a run restricted with ``--sensor``/``--index`` never removes the
    results of the others. A failed entry keeps its previous values and gets
    ``status: "failed"`` and ``error``; its ``computed_at`` stays the time of the last
    successful computation (``null`` if there was none). A run without any result or error
    writes nothing. Entries of sensors no longer known are pruned on write.

    Parameters
    ----------
    directory : pathlib.Path
        The indices directory.
    writer : JsonFileWriter, optional
        Writes the JSON atomically.
    known : callable, optional
        Returns the ids of the sensors to keep (:class:`~sivin.app.quality.KnownSensors`); the
        entries of the others are pruned on write. Nothing is pruned when omitted.
    indices : collection of str, optional
        The registered index ids; entries of other (removed) indices are pruned on write.
        Nothing is pruned when omitted.
    """

    __slots__ = ("_directory", "_indices", "_known", "_writer")

    def __init__(
        self,
        directory: Path,
        writer: JsonFileWriter | None = None,
        known: Callable[[], frozenset[str]] | None = None,
        indices: Collection[str] | None = None,
    ) -> None:
        self._directory = directory
        self._writer = writer if writer is not None else JsonFileWriter()
        self._known = known
        self._indices = frozenset(indices) if indices is not None else None

    def path_for(self, season: int) -> Path:
        """Return the file of a season, ``<directory>/<season>.json``.

        Parameters
        ----------
        season : int
            The season year.

        Returns
        -------
        pathlib.Path
            The file.
        """
        return self._directory / f"{season}{INDICES_SUFFIX}"

    def update(self, report: IndicesReport, computed_at: datetime) -> Path | None:
        """Merge a report into the season's file.

        Parameters
        ----------
        report : IndicesReport
            Results and errors of the run.
        computed_at : datetime.datetime
            Time of the computation (aware).

        Returns
        -------
        pathlib.Path or None
            The file, or ``None`` if the report has nothing to record.
        """
        if not report.changes:
            return None
        path = self.path_for(report.window.season)
        document = read_document(path) or {}
        sensors_doc = document.get("sensors")
        sensors: dict[str, Any] = dict(sensors_doc) if isinstance(sensors_doc, dict) else {}
        for sensor, results in report.results.items():
            entries = dict(sensors.get(str(sensor), {}))
            for index_id, result in results.items():
                entries[index_id] = result_dict(result, computed_at)
            sensors[str(sensor)] = entries
        for sensor, errors in report.errors.items():
            entries = dict(sensors.get(str(sensor), {}))
            for index_id, error in errors.items():
                previous = entries.get(index_id)
                entry = dict(previous) if isinstance(previous, dict) else {"computed_at": None}
                entry.update(status=STATUS_FAILED, error=error)
                entries[index_id] = entry
            sensors[str(sensor)] = entries
        self._prune(sensors, report.window.season)
        self._prune_other_seasons(report.window.season)
        updated = {
            "season": report.window.season,
            "data_from": report.window.first.isoformat(),
            "data_to": report.window.last.isoformat(),
            "sensors": dict(sorted(sensors.items())),
        }
        return self._writer.write(path, updated)

    def _prune_other_seasons(self, current: int) -> None:
        """Prune the season files other than ``current`` (rewritten only when changed)."""
        if not self._directory.is_dir():
            return
        for path in sorted(self._directory.glob(f"*{INDICES_SUFFIX}")):
            if SEASON_FILE.fullmatch(path.name) is None or int(path.stem) == current:
                continue
            document = read_document(path)
            sensors_doc = None if document is None else document.get("sensors")
            if document is None or not isinstance(sensors_doc, dict):
                continue
            sensors = copy.deepcopy(sensors_doc)
            self._prune(sensors, int(path.stem))
            if sensors != sensors_doc:
                self._writer.write(path, {**document, "sensors": sensors})

    def _prune(self, sensors: dict[str, Any], season: int) -> None:
        if self._known is not None:
            known = self._known()
            stale = sorted(sensor for sensor in sensors if sensor not in known)
            for sensor in stale:
                del sensors[sensor]
            if stale:
                logger.info(
                    "Pruned the season %d indices of sensor(s) no longer in the registry or "
                    "the store: %s.",
                    season,
                    ", ".join(stale),
                )
        if self._indices is not None:
            removed: set[str] = set()
            for sensor, entries in list(sensors.items()):
                if not isinstance(entries, dict):
                    continue
                gone = [index_id for index_id in entries if index_id not in self._indices]
                removed.update(gone)
                sensors[sensor] = {k: v for k, v in entries.items() if k not in gone}
            if removed:
                logger.info(
                    "Pruned the season %d entries of index(es) no longer registered: %s.",
                    season,
                    ", ".join(sorted(removed)),
                )


class IndicesService:
    """Compute the climate indices of a season for every sensor and update its file.

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
    writer : IndicesWriter
        Updates ``<season>.json``.
    clock : callable
        Current time (aware).
    dry_run : bool, optional
        Compute, but write no file.
    error_text : callable, optional
        Turns an error into a publishable text (relative paths, redacted credentials).
    """

    __slots__ = (
        "_clock",
        "_contexts",
        "_dry_run",
        "_error_text",
        "_quality",
        "_selection",
        "_writer",
    )

    def __init__(
        self,
        quality: QualityService,
        contexts: IndexContextFactory,
        selection: IndexSelection,
        writer: IndicesWriter,
        clock: Callable[[], datetime],
        dry_run: bool = False,
        error_text: Callable[[BaseException], str] = str,
    ) -> None:
        self._error_text = error_text
        self._quality = quality
        self._contexts = contexts
        self._selection = selection
        self._writer = writer
        self._clock = clock
        self._dry_run = dry_run

    def run(
        self,
        season: int,
        sensors: Sequence[SensorId] | None = None,
        index_ids: Sequence[str] | None = None,
        checked: Mapping[SensorId, QualityResult] | None = None,
    ) -> IndicesReport:
        """Compute the indices of one season and update its file.

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
            Results, errors and the file written.

        Raises
        ------
        UnknownIndexError
            If an index id is not registered.
        """
        indices = self._selection.create(index_ids)
        window = SeasonWindow.of(season)
        start, end = window.bounds_utc(self._contexts.timezone)
        results: dict[SensorId, dict[str, IndexResult]] = {}
        errors: dict[SensorId, dict[str, str]] = {}
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
                text = self._error_text(error)
                failures.append(f"indices {sensor_id}: {text}")
                errors[sensor_id] = dict.fromkeys(indices, text)
                continue
            computed, failed = self._compute(context, indices, failures, self._error_text)
            results[sensor_id] = computed
            if failed:
                errors[sensor_id] = failed
        report = IndicesReport(window, results, errors, tuple(failures))
        if self._dry_run:
            return report
        path = self._writer.update(report, self._clock())
        return IndicesReport(window, report.results, report.errors, report.failures, path)

    @staticmethod
    def _compute(
        context: IndexContext,
        indices: Mapping[str, ClimateIndex[Any]],
        failures: list[str],
        error_text: Callable[[BaseException], str],
    ) -> tuple[dict[str, IndexResult], dict[str, str]]:
        computed: dict[str, IndexResult] = {}
        failed: dict[str, str] = {}
        for index_id, index in indices.items():
            try:
                computed[index_id] = index.compute(context)
            except SENSOR_ERRORS as error:
                logger.error("Index %s of sensor %s: %s", index_id, context.sensor_id, error)
                text = error_text(error)
                failures.append(f"indices {context.sensor_id} {index_id}: {text}")
                failed[index_id] = text
        return computed, failed
