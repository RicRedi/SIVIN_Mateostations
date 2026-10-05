"""The :class:`SiteBuilder`: quality-controlled data → ``site/data`` (MIGRATION_PLAN §2.6).

One build:

1. reads the previous build state (unless ``full``) and keeps it only if the shared inputs
   (configuration, registry, off-site log, ``sivin`` version) are unchanged;
2. reuses every sensor whose stored files and written files are unchanged, and quality-checks
   and writes the others (raw months, daily, events);
3. decides the seasons (given, or every calendar year with data); if they differ from the last
   build, every sensor is rebuilt;
4. computes the indices of the rebuilt sensors for every season;
5. writes the site-wide files (manifest, registry copy, latest values, one indices file per
   season), removes files no longer produced and saves the new state.

Incremental and full builds give byte-identical files (tested).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol

from sivin.core.ids import SensorId
from sivin.quality.pipeline import QualityResult
from sivin.site.files import SiteFile, SiteOutput
from sivin.site.indices import IndexSource, index_entry
from sivin.site.model import IndexEntries, PublishedSensor, SiteSnapshot
from sivin.site.sensor_builder import BuiltSensor, SensorSiteBuilder
from sivin.site.site_files import SiteFileWriter
from sivin.site.state import STATE_FILE, BuildState, SensorState, StoreFingerprints

logger = logging.getLogger(__name__)

BUILD_ERRORS: Final = (ValueError, LookupError, ArithmeticError, OSError)
"""Errors that fail one sensor but not the build (malformed store file, schema or parameter
problems in one sensor's data), as in the other services; programming errors propagate."""


class CheckedSource(Protocol):
    """Reads one sensor from the store through quality control (``QualityService.checked``)."""

    def checked(self, sensor_id: SensorId) -> QualityResult:
        """Return the QC result over the sensor's whole stored record.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.

        Returns
        -------
        QualityResult
            Flagged series (values set aside) and events.
        """
        ...


@dataclass(frozen=True, slots=True)
class SiteInputs:
    """What is published, and the fingerprint of everything shared by all sensors.

    Attributes
    ----------
    sensors : Mapping of SensorId to str
        The sensors to publish (registry sensors with stored data) → registry status.
    registry : bytes
        The registry file, copied to ``sensors.geojson``.
    settings : str
        Fingerprint of the shared inputs (configuration, registry, off-site log, version).
    display_timezone : str
        IANA zone of the local days (``time.display_timezone``).
    """

    sensors: Mapping[SensorId, str]
    registry: bytes
    settings: str
    display_timezone: str


@dataclass(frozen=True)
class SiteReport:
    """Outcome of :meth:`SiteBuilder.build`.

    Attributes
    ----------
    out_dir : pathlib.Path
        The output directory.
    generated_at : datetime.datetime
        Time of the build.
    full : bool
        Everything was rebuilt (``--full``, no usable state, or changed shared inputs).
    seasons : tuple of int
        The seasons of the indices files.
    built : tuple of SensorId
        Sensors quality-checked and written in this build.
    reused : tuple of SensorId
        Sensors taken unchanged from the last build.
    written : tuple of str
        Files whose content changed (relative paths).
    removed : tuple of str
        Files deleted because they are no longer produced.
    failures : tuple of str
        One message per sensor or index that failed.
    """

    out_dir: Path
    generated_at: datetime
    full: bool
    seasons: tuple[int, ...]
    built: tuple[SensorId, ...]
    reused: tuple[SensorId, ...]
    written: tuple[str, ...]
    removed: tuple[str, ...]
    failures: tuple[str, ...]


class SiteBuilder:
    """Generate the static site data (module docstring).

    Parameters
    ----------
    source : CheckedSource
        Reads a sensor through quality control.
    indices : IndexSource
        Computes the climate indices.
    sensors : SensorSiteBuilder
        Builds the files and summary of one sensor.
    site_writers : sequence of SiteFileWriter
        The site-wide file kinds.
    fingerprints : StoreFingerprints
        Fingerprints of the stored files of each sensor.
    clock : callable
        Current time (aware), ``generated_at``.
    error_text : callable, optional
        Turns an error into a publishable text (relative paths, no credentials).
    """

    __slots__ = (
        "_clock",
        "_error_text",
        "_fingerprints",
        "_indices",
        "_sensors",
        "_site_writers",
        "_source",
    )

    def __init__(
        self,
        source: CheckedSource,
        indices: IndexSource,
        sensors: SensorSiteBuilder,
        site_writers: Sequence[SiteFileWriter],
        fingerprints: StoreFingerprints,
        clock: Callable[[], datetime],
        error_text: Callable[[BaseException], str] = str,
    ) -> None:
        self._source = source
        self._indices = indices
        self._sensors = sensors
        self._site_writers = tuple(site_writers)
        self._fingerprints = fingerprints
        self._clock = clock
        self._error_text = error_text

    def build(
        self,
        output: SiteOutput,
        inputs: SiteInputs,
        seasons: Sequence[int] | None = None,
        full: bool = False,
        checked: Mapping[SensorId, QualityResult] | None = None,
    ) -> SiteReport:
        """Build the site data into ``output``.

        Parameters
        ----------
        output : SiteOutput
            The output directory.
        inputs : SiteInputs
            Sensors, registry and shared fingerprint.
        seasons : sequence of int, optional
            Season years of the indices files; every calendar year with data when omitted.
        full : bool, optional
            Ignore the previous state and rebuild everything.
        checked : Mapping of SensorId to QualityResult, optional
            QC results already computed over the whole record (``sivin run``).

        Returns
        -------
        SiteReport
            What was built, reused, written and removed, and the failures.
        """
        generated_at = self._clock()
        previous = None if full else BuildState.parse(output.read(STATE_FILE))
        if previous is not None and previous.settings != inputs.settings:
            logger.info("Configuration, registry or off-site log changed: full site build.")
            previous = None
        given = checked or {}
        run = _BuildRun(
            self._sensors,
            self._indices,
            lambda sensor_id: given.get(sensor_id) or self._source.checked(sensor_id),
            self._error_text,
            output,
            inputs,
            previous,
            {sensor_id: self._fingerprints.of(sensor_id) for sensor_id in inputs.sensors},
        )
        run.build_sensors(run.changed())
        chosen = tuple(sorted(set(seasons))) if seasons else run.default_seasons()
        if previous is None or chosen != previous.seasons:
            run.build_sensors(run.reusable_ids())
        run.compute_indices(chosen)
        snapshot = SiteSnapshot(
            generated_at,
            inputs.display_timezone,
            run.published(),
            chosen,
            self._indices.specs(),
            inputs.registry,
        )
        site_files = [file for writer in self._site_writers for file in writer.files(snapshot)]
        written = run.write([*run.fresh_files(), *site_files])
        states = run.states()
        keep = {path for state in states.values() for path in state.outputs}
        removed = output.prune(keep | {file.path for file in site_files})
        output.write(BuildState(inputs.settings, chosen, states).to_file())
        logger.info(
            "Site data: %d sensor(s) built, %d reused, %d file(s) written, %d removed.",
            len(run.built),
            len(run.reused),
            len(written),
            len(removed),
        )
        return SiteReport(
            out_dir=output.root,
            generated_at=generated_at,
            full=previous is None,
            seasons=chosen,
            built=tuple(sorted(run.built)),
            reused=tuple(sorted(run.reused)),
            written=tuple(written),
            removed=tuple(removed),
            failures=tuple(run.failures),
        )


class _BuildRun:
    """The working state of one :meth:`SiteBuilder.build` call."""

    def __init__(
        self,
        sensors: SensorSiteBuilder,
        indices: IndexSource,
        load: Callable[[SensorId], QualityResult],
        error_text: Callable[[BaseException], str],
        output: SiteOutput,
        inputs: SiteInputs,
        previous: BuildState | None,
        fingerprints: Mapping[SensorId, str],
    ) -> None:
        self._sensors = sensors
        self._index_source = indices
        self._load = load
        self._error_text = error_text
        self._output = output
        self._inputs = inputs
        self._previous_states = dict(previous.sensors) if previous is not None else {}
        self._fingerprints = fingerprints
        self._fresh: dict[SensorId, BuiltSensor] = {}
        self._indices: dict[SensorId, dict[int, IndexEntries]] = {}
        self.failures: list[str] = []
        self.reused: set[SensorId] = {
            sensor_id for sensor_id in inputs.sensors if self._is_reusable(sensor_id)
        }
        self.built: set[SensorId] = set()

    def changed(self) -> list[SensorId]:
        """Sensors that cannot be reused, sorted."""
        return sorted(
            sensor_id for sensor_id in self._inputs.sensors if sensor_id not in self.reused
        )

    def reusable_ids(self) -> list[SensorId]:
        """Sensors still taken from the last build, sorted."""
        return sorted(self.reused)

    def build_sensors(self, sensor_ids: Iterable[SensorId]) -> None:
        """Quality-check and build the given sensors."""
        for sensor_id in sensor_ids:
            self.reused.discard(sensor_id)
            try:
                built = self._sensors.build(sensor_id, self._load(sensor_id))
            except BUILD_ERRORS as error:
                logger.error("Site data of sensor %s failed: %s", sensor_id, error)
                self.failures.append(f"site {sensor_id}: {self._error_text(error)}")
                continue
            if built is not None:
                self._fresh[sensor_id] = built
                self.built.add(sensor_id)

    def default_seasons(self) -> tuple[int, ...]:
        """Every calendar year with data of a published sensor."""
        years = {year for sensor in self.published() for year in sensor.summary.years}
        return tuple(sorted(years))

    def compute_indices(self, seasons: Sequence[int]) -> None:
        """Compute the indices of the freshly built sensors for every season."""
        if not self._fresh:
            return
        checked = {sensor_id: built.result for sensor_id, built in sorted(self._fresh.items())}
        for season in seasons:
            batch = self._index_source.compute(season, checked)
            self.failures.extend(batch.failures)
            for sensor_id, results in batch.results.items():
                entries = {index_id: index_entry(r) for index_id, r in sorted(results.items())}
                self._indices.setdefault(sensor_id, {})[season] = entries

    def states(self) -> dict[str, SensorState]:
        """The new state of every published sensor."""
        states: dict[str, SensorState] = {}
        for sensor_id in sorted(self._inputs.sensors):
            built = self._fresh.get(sensor_id)
            if built is not None:
                indices = self._indices.get(sensor_id, {})
                fingerprint = self._fingerprints[sensor_id]
                states[str(sensor_id)] = SensorState.of(
                    fingerprint, built.files, built.summary, indices
                )
            elif str(sensor_id) in self._previous_states:
                states[str(sensor_id)] = self._previous_states[str(sensor_id)]
        return states

    def published(self) -> tuple[PublishedSensor, ...]:
        """The published sensors with their status, summary and index entries."""
        return tuple(
            PublishedSensor(
                SensorId(sensor_id),
                self._inputs.sensors[SensorId(sensor_id)],
                state.summary,
                state.indices,
            )
            for sensor_id, state in self.states().items()
        )

    def fresh_files(self) -> list[SiteFile]:
        """The per-sensor files built in this run."""
        return [file for _, built in sorted(self._fresh.items()) for file in built.files]

    def write(self, files: Iterable[SiteFile]) -> list[str]:
        """Write the files whose content changed; return their paths."""
        return [file.path for file in files if self._output.write(file)]

    def _is_reusable(self, sensor_id: SensorId) -> bool:
        state = self._previous_states.get(str(sensor_id))
        if state is None or state.inputs != self._fingerprints[sensor_id]:
            return False
        return all(self._output.has(path, sha) for path, sha in state.outputs.items())
