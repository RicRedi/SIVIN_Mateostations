"""Quality control of the stored measurements, with the off-site log, and the derived events."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pandas as pd

from sivin.app.json_files import JsonFileWriter
from sivin.app.outcome import Outcome
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries, TimestampLike
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


class EventsWriter:
    """Write ``<derived>/events/<sensor_id>.json``: the QC events and flag counts of a sensor.

    The file holds no run time, so an unchanged result gives the same bytes.

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

    def write(self, result: QualityResult) -> Path:
        """Write the events of one QC result.

        Parameters
        ----------
        result : QualityResult
            Result of the pipeline for one sensor.

        Returns
        -------
        pathlib.Path
            The file written.
        """
        series = result.series
        times = series.timestamps
        document = {
            "sensor_id": str(series.sensor_id),
            "first_t": iso_utc(times.iloc[0]) if len(times) else None,
            "last_t": iso_utc(times.iloc[-1]) if len(times) else None,
            "n_samples": len(series),
            "flag_counts": {
                str(flag.name): count for flag, count in result.flag_counts.items() if count
            },
            "values_set_aside": result.values_set_aside,
            "events": [event_dict(event) for event in result.events],
        }
        return self._writer.write(self.path_for(series.sensor_id), document)


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
    """

    sensor_id: SensorId
    result: QualityResult | None = None
    events_file: Path | None = None
    failure: str | None = None


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

    __slots__ = ("_dry_run", "_events", "_pipeline", "_registry", "_store")

    def __init__(
        self,
        store: MeasurementStore,
        pipeline: QualityPipeline,
        registry: SensorRegistry,
        events: EventsWriter,
        dry_run: bool = False,
    ) -> None:
        self._store = store
        self._pipeline = pipeline
        self._registry = registry
        self._events = events
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
        start_utc: TimestampLike | None = None,
        end_utc: TimestampLike | None = None,
    ) -> QualityReport:
        """Run quality control for every requested sensor and write its events.

        Parameters
        ----------
        sensors : sequence of SensorId, optional
            Sensors to check; every stored sensor when omitted.
        start_utc, end_utc : timestamp, optional
            Timezone-aware inclusive bounds.

        Returns
        -------
        QualityReport
            One entry per sensor; a sensor without data has no result and no failure.
        """
        outcomes = {
            sensor_id: self._one(sensor_id, start_utc, end_utc)
            for sensor_id in self.sensors(sensors)
        }
        return QualityReport(outcomes, self._dry_run)

    def _one(
        self, sensor_id: SensorId, start_utc: TimestampLike | None, end_utc: TimestampLike | None
    ) -> SensorQuality:
        try:
            result = self.checked(sensor_id, start_utc, end_utc)
        except SENSOR_ERRORS as error:
            logger.error("Quality control of sensor %s failed: %s", sensor_id, error)
            return SensorQuality(sensor_id, failure=str(error))
        if result.series.is_empty:
            logger.info("Sensor %s: no stored data in the requested range.", sensor_id)
            return SensorQuality(sensor_id)
        written = None if self._dry_run else self._events.write(result)
        return SensorQuality(sensor_id, result, written)

    def _known_deployments(self, series: MeasurementSeries) -> list[pd.Timestamp]:
        if series.sensor_id not in self._registry:
            return []
        placements = self._registry.get(series.sensor_id).placements
        return [pd.Timestamp(placement.from_utc) for placement in placements]
