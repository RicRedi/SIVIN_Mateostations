"""The whole pipeline in one go: fetch → ingest → QC → indices, and the run log record."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from sivin.app.indices import IndicesReport, IndicesService
from sivin.app.ingest import IngestReport, IngestService
from sivin.app.outcome import Outcome, SetupError
from sivin.app.quality import QualityReport, QualityService
from sivin.core.ids import SensorId
from sivin.storage.runlog import RunLog, RunRecord

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
"""Returns the current time, timezone-aware."""


class ExportSource(Protocol):
    """Where ``sivin run`` gets its export files from (the portal, or a directory)."""

    def exports(
        self, sensors: Sequence[SensorId] | None
    ) -> tuple[tuple[Path, ...], tuple[str, ...]]:
        """Return the export files to ingest and one message per failed source item.

        Parameters
        ----------
        sensors : sequence of SensorId, optional
            Sensors to get exports for; all when omitted.

        Returns
        -------
        tuple
            ``(files, failures)``.

        Raises
        ------
        SetupError
            If nothing can be fetched at all (credentials, login).
        """
        ...


class RunRecorder:
    """Append the summary of a run to the run log (``data/runs/<YYYY-MM-DD>.jsonl``).

    Parameters
    ----------
    run_log : RunLog
        The store's run log.
    """

    __slots__ = ("_run_log",)

    def __init__(self, run_log: RunLog) -> None:
        self._run_log = run_log

    @staticmethod
    def record(
        started_at: datetime,
        finished_at: datetime,
        ingest: IngestReport,
        failures: Sequence[str] = (),
    ) -> RunRecord:
        """Build the record of a run.

        Parameters
        ----------
        started_at, finished_at : datetime.datetime
            Timezone-aware start and end of the run.
        ingest : IngestReport
            The ingest step: the **full names** of the processed files, validation counts,
            append counts and conflicts (the store keeps only short export identifiers).
        failures : sequence of str, optional
            Failures of the other steps (fetch, QC, indices).

        Returns
        -------
        RunRecord
            The record (not yet written).
        """
        return RunRecord(
            started_at=started_at,
            finished_at=finished_at,
            files=tuple(item.path.name for item in ingest.files),
            appends=ingest.appends,
            validation_issues=ingest.validation_counts,
            failures=(*failures, *ingest.failures),
            conflicts=ingest.conflicts,
        )

    def write(self, record: RunRecord) -> Path:
        """Append the record to the run log.

        Parameters
        ----------
        record : RunRecord
            The record.

        Returns
        -------
        pathlib.Path
            The run-log file.
        """
        return self._run_log.append(record)


@dataclass(frozen=True)
class RunReport:
    """Outcome of :meth:`RunService.run`.

    Attributes
    ----------
    fetch_failures : tuple of str
        Devices not downloaded, or why fetching failed altogether.
    ingest : IngestReport
        The ingest step.
    quality : QualityReport
        The QC step.
    indices : IndicesReport
        The indices step.
    record : RunRecord
        The run-log record (written unless ``dry_run``).
    dry_run : bool
        Nothing was written.
    """

    fetch_failures: tuple[str, ...]
    ingest: IngestReport
    quality: QualityReport
    indices: IndicesReport
    record: RunRecord
    dry_run: bool = False

    @property
    def outcome(self) -> Outcome:
        """The most severe outcome of the steps."""
        return Outcome.worst(
            (
                Outcome.of(self.fetch_failures),
                self.ingest.outcome,
                self.quality.outcome,
                self.indices.outcome,
            )
        )


class RunService:
    """Fetch, ingest, check and compute the indices; one failing sensor never stops the run.

    Parameters
    ----------
    source : ExportSource
        Provides the export files (portal or directory).
    ingest : IngestService
        Parses, validates and appends.
    quality : QualityService
        Checks every stored sensor and writes its events.
    indices : IndicesService
        Computes the season's indices from the QC results.
    recorder : RunRecorder
        Writes the run-log record.
    clock : Clock
        Current time (aware).
    dry_run : bool, optional
        Write nothing (the services must be built with the same flag).
    """

    __slots__ = ("_clock", "_dry_run", "_indices", "_ingest", "_quality", "_recorder", "_source")

    def __init__(
        self,
        source: ExportSource,
        ingest: IngestService,
        quality: QualityService,
        indices: IndicesService,
        recorder: RunRecorder,
        clock: Clock,
        dry_run: bool = False,
    ) -> None:
        self._source = source
        self._ingest = ingest
        self._quality = quality
        self._indices = indices
        self._recorder = recorder
        self._clock = clock
        self._dry_run = dry_run

    def run(self, season: int, sensors: Sequence[SensorId] | None = None) -> RunReport:
        """Run the pipeline.

        A portal failure (missing credentials, failed login) is recorded and the run goes on
        with the data already stored, so a broken portal never removes data (plan WP-4.1).

        Parameters
        ----------
        season : int
            Season year of the indices.
        sensors : sequence of SensorId, optional
            Restrict fetch, QC and indices to these sensors; all when omitted.

        Returns
        -------
        RunReport
            The report of every step and the run-log record.
        """
        started_at = self._clock()
        try:
            files, fetch_failures = self._source.exports(sensors)
        except SetupError as error:
            logger.error("Fetching failed, continuing with the stored data: %s", error)
            files, fetch_failures = (), (f"fetch: {error}",)
        ingest = self._ingest.ingest(files)
        quality = self._quality.run(sensors)
        checked = {
            sensor: item.result
            for sensor, item in quality.sensors.items()
            if item.result is not None
        }
        indices = self._indices.run(season, sensors, checked=checked)
        record = RunRecorder.record(
            started_at,
            self._clock(),
            ingest,
            (*fetch_failures, *quality.failures, *indices.failures),
        )
        if not self._dry_run:
            path = self._recorder.write(record)
            logger.info("Run recorded in %s.", path)
        return RunReport(tuple(fetch_failures), ingest, quality, indices, record, self._dry_run)
