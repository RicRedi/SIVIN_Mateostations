"""Quality control of the stored measurements, with the off-site log, and the derived events."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final

import numpy as np
import pandas as pd

from sivin.app.json_files import JsonFileWriter, read_document
from sivin.app.outcome import Outcome
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries, TimestampLike
from sivin.quality.events import QualityEvent
from sivin.quality.pipeline import QualityPipeline, QualityResult
from sivin.registry.registry import SensorRegistry
from sivin.storage.store import MeasurementStore

logger = logging.getLogger(__name__)

EVENTS_SUFFIX: Final = ".json"
"""File suffix of a derived events file, ``<sensor_id>.json``."""

SENSOR_ERRORS: Final = (ValueError, LookupError, ArithmeticError, OSError)
"""Errors that fail one sensor but not the whole command (malformed store file, schema or
parameter problems in one sensor's data). Programming errors (``TypeError``, ...) propagate."""


def iso_utc(moment: pd.Timestamp | None) -> str | None:
    """Format a UTC instant as ISO 8601 with ``Z`` (``None`` stays ``None``).

    Parameters
    ----------
    moment : pandas.Timestamp or None
        A timezone-aware instant.

    Returns
    -------
    str or None
        E.g. ``"2026-03-01T21:27:05Z"``.
    """
    if moment is None:
        return None
    return moment.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def event_dict(event: QualityEvent) -> dict[str, object]:
    """Return one QC event as JSON data (format in ``docs/storage.md``).

    Parameters
    ----------
    event : QualityEvent
        The event.

    Returns
    -------
    dict
        ``type``, ``t``, ``t_end``, ``source``, ``severity``, ``confidence``, ``detail``,
        ``origin``; times as ISO 8601 UTC.
    """
    return {
        "type": str(event.kind),
        "t": iso_utc(event.t_utc),
        "t_end": iso_utc(event.end_utc),
        "source": str(event.source),
        "severity": str(event.severity),
        "confidence": event.confidence,
        "detail": event.detail,
        "origin": event.origin,
    }


STATUS_OK: Final = "ok"
"""``status`` of a derived entry computed successfully in the last run that processed it."""

STATUS_FAILED: Final = "failed"
"""``status`` of a derived entry whose last computation failed (the previous result is kept)."""


class EventsWriter:
    """Write ``<derived>/events/<sensor_id>.json``: the QC events and flag counts of a sensor.

    The file is replaced only by a complete result over the sensor's whole stored record. A
    failed computation keeps the previous content and adds ``status: "failed"`` and ``error``;
    ``computed_at`` stays the time of the last successful computation (MIGRATION_PLAN WP-1.7
    review: an unattended run must never lose a derived result).

    Parameters
    ----------
    directory : pathlib.Path
        The events directory.
    writer : JsonFileWriter, optional
        Writes the JSON atomically.
    """

    __slots__ = ("_directory", "_writer")

    def __init__(self, directory: Path, writer: JsonFileWriter | None = None) -> None:
        self._directory = directory
        self._writer = writer if writer is not None else JsonFileWriter()

    def path_for(self, sensor_id: SensorId) -> Path:
        """Return the events file of a sensor.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.

        Returns
        -------
        pathlib.Path
            ``<directory>/<sensor_id>.json``.
        """
        return self._directory / f"{sensor_id}{EVENTS_SUFFIX}"

    def write(self, result: QualityResult, computed_at: datetime) -> Path:
        """Write the events of one QC result over the whole record.

        Parameters
        ----------
        result : QualityResult
            Result of the pipeline for one sensor.
        computed_at : datetime.datetime
            Time of the computation (aware).

        Returns
        -------
        pathlib.Path
            The file written.
        """
        series = result.series
        times = series.timestamps
        document = {
            "sensor_id": str(series.sensor_id),
            "status": STATUS_OK,
            "computed_at": iso_utc(pd.Timestamp(computed_at)),
            "first_t": iso_utc(times.iloc[0]) if len(times) else None,
            "last_t": iso_utc(times.iloc[-1]) if len(times) else None,
            "n_samples": len(series),
            "flag_counts": flag_counts(result.series),
            "values_set_aside": result.values_set_aside,
            "events": [event_dict(event) for event in result.events],
        }
        return self._writer.write(self.path_for(series.sensor_id), document)

    def mark_failed(self, sensor_id: SensorId, error: str) -> Path:
        """Record a failed computation, keeping the previous result.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.
        error : str
            Why it failed.

        Returns
        -------
        pathlib.Path
            The file written.
        """
        path = self.path_for(sensor_id)
        previous = read_document(path)
        document: dict[str, object] = (
            previous
            if previous is not None
            else {"sensor_id": str(sensor_id), "computed_at": None, "events": []}
        )
        document["status"] = STATUS_FAILED
        document["error"] = error
        return self._writer.write(path, document)


def flag_counts(series: MeasurementSeries) -> dict[str, int]:
    """Count the rows carrying each single QC flag (zero counts left out).

    Parameters
    ----------
    series : MeasurementSeries
        Flagged measurements.

    Returns
    -------
    dict of str to int
        Flag name → number of rows (count).
    """
    qc = series.frame[Column.QC].to_numpy()
    single = [flag for flag in QcFlag if flag and not flag & (flag - 1)]
    counts = {str(flag.name): int(np.count_nonzero(qc & int(flag))) for flag in single}
    return {name: count for name, count in counts.items() if count}


def restricted(
    result: QualityResult, start: datetime | None, end: datetime | None
) -> QualityResult:
    """Return the part of a whole-record QC result inside ``[start, end]``.

    Parameters
    ----------
    result : QualityResult
        Result over the whole record.
    start, end : datetime.datetime or None
        Inclusive aware bounds; unbounded when ``None``.

    Returns
    -------
    QualityResult
        Rows inside the bounds, the events that overlap them and their flag counts;
        ``values_set_aside`` stays the count of the whole record.
    """
    if start is None and end is None:
        return result
    lower = pd.Timestamp(start) if start is not None else pd.Timestamp.min.tz_localize("UTC")
    upper = pd.Timestamp(end) if end is not None else pd.Timestamp.max.tz_localize("UTC")
    series = result.series.between(lower, upper) if not result.series.is_empty else result.series
    events = tuple(
        event
        for event in result.events
        if event.t_utc <= upper
        and (event.end_utc if event.end_utc is not None else event.t_utc) >= lower
    )
    counts = {flag: count for flag, count in result.flag_counts.items()}
    qc = series.frame[Column.QC].to_numpy()
    for flag in counts:
        counts[flag] = int(np.count_nonzero(qc & int(flag)))
    return QualityResult(series, events, counts, result.deployment, result.values_set_aside)


@dataclass(frozen=True)
class SensorQuality:
    """QC outcome of one sensor.

    Attributes
    ----------
    sensor_id : SensorId
        The sensor.
    result : QualityResult or None
        Flagged series and events; ``None`` if the sensor failed or has no data.
    events_file : pathlib.Path or None
        The events file written (``None`` in a dry run, without data or on failure).
    failure : str or None
        Why the sensor failed; ``None`` on success.
    whole : QualityResult or None
        The result over the whole record (``result`` may be restricted to the report bounds).
    """

    sensor_id: SensorId
    result: QualityResult | None = None
    events_file: Path | None = None
    failure: str | None = None
    whole: QualityResult | None = None


@dataclass(frozen=True)
class QualityReport:
    """Outcome of :meth:`QualityService.run`.

    Attributes
    ----------
    sensors : Mapping of SensorId to SensorQuality
        One entry per processed sensor.
    dry_run : bool
        No file was written.
    """

    sensors: Mapping[SensorId, SensorQuality] = field(default_factory=dict)
    dry_run: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "sensors", MappingProxyType(dict(self.sensors)))

    @property
    def failures(self) -> tuple[str, ...]:
        """One message per failed sensor."""
        return tuple(
            f"qc {sensor}: {item.failure}"
            for sensor, item in self.sensors.items()
            if item.failure is not None
        )

    @property
    def outcome(self) -> Outcome:
        """:attr:`Outcome.PARTIAL_FAILURE` if any sensor failed."""
        return Outcome.of(self.failures)


class QualityService:
    """Read stored measurements, run quality control with the off-site log, write events.

    Data read from the store carry ``qc = 0`` (the store keeps no flags), so every consumer
    of stored data (indices, site export) gets them through :meth:`checked` first
    (``docs/architecture.md``, row validity).

    Parameters
    ----------
    store : MeasurementStore
        The measurement store.
    pipeline : QualityPipeline
        Checks, off-site log and detector (built from ``quality`` and ``offsite_log``).
    registry : SensorRegistry
        Placement ``from`` times are passed as known deployments.
    events : EventsWriter
        Writes the derived events.
    dry_run : bool, optional
        Compute, but write no file.
    """

    __slots__ = ("_clock", "_dry_run", "_events", "_pipeline", "_registry", "_store")

    def __init__(
        self,
        store: MeasurementStore,
        pipeline: QualityPipeline,
        registry: SensorRegistry,
        events: EventsWriter,
        clock: Callable[[], datetime],
        dry_run: bool = False,
    ) -> None:
        self._store = store
        self._pipeline = pipeline
        self._registry = registry
        self._events = events
        self._clock = clock
        self._dry_run = dry_run

    def sensors(self, wanted: Sequence[SensorId] | None = None) -> list[SensorId]:
        """Return the sensors to process: the wanted ones, or every sensor in the store.

        Parameters
        ----------
        wanted : sequence of SensorId, optional
            Requested sensors; all stored sensors when omitted.

        Returns
        -------
        list of SensorId
            Sorted, without duplicates.
        """
        return sorted(set(wanted)) if wanted else self._store.sensors()

    def checked(
        self,
        sensor_id: SensorId,
        start_utc: TimestampLike | None = None,
        end_utc: TimestampLike | None = None,
    ) -> QualityResult:
        """Read one sensor from the store and run quality control on it.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.
        start_utc, end_utc : timestamp, optional
            Timezone-aware inclusive bounds; the whole record when omitted.

        Returns
        -------
        QualityResult
            Flagged series (values set aside), events and flag counts.
        """
        series = self._store.read(sensor_id, start_utc, end_utc)
        return self._pipeline.run(series, self._known_deployments(series))

    def run(
        self,
        sensors: Sequence[SensorId] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> QualityReport:
        """Run quality control for every requested sensor and write its events.

        QC always runs over the sensor's **whole** stored record (the detector and the
        deployed checks need the context, and the events file must stay complete); ``start``
        and ``end`` only restrict what the report shows. Only the requested sensors' files are
        written; a failed sensor keeps its previous file with ``status: "failed"``.

        Parameters
        ----------
        sensors : sequence of SensorId, optional
            Sensors to check; every stored sensor when omitted.
        start, end : datetime.datetime, optional
            Timezone-aware inclusive bounds of the report.

        Returns
        -------
        QualityReport
            One entry per sensor; a sensor without data has no result and no failure.
        """
        outcomes = {
            sensor_id: self._one(sensor_id, start, end) for sensor_id in self.sensors(sensors)
        }
        return QualityReport(outcomes, self._dry_run)

    def _one(
        self, sensor_id: SensorId, start: datetime | None, end: datetime | None
    ) -> SensorQuality:
        try:
            result = self.checked(sensor_id)
        except SENSOR_ERRORS as error:
            logger.error("Quality control of sensor %s failed: %s", sensor_id, error)
            written = None if self._dry_run else self._events.mark_failed(sensor_id, str(error))
            return SensorQuality(sensor_id, events_file=written, failure=str(error))
        if result.series.is_empty:
            logger.info("Sensor %s: no stored data.", sensor_id)
            return SensorQuality(sensor_id)
        written = None if self._dry_run else self._events.write(result, self._clock())
        return SensorQuality(sensor_id, restricted(result, start, end), written, whole=result)

    def _known_deployments(self, series: MeasurementSeries) -> list[pd.Timestamp]:
        if series.sensor_id not in self._registry:
            return []
        placements = self._registry.get(series.sensor_id).placements
        return [pd.Timestamp(placement.from_utc) for placement in placements]
