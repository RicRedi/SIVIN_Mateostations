"""Ingest: parse and validate export files, quarantine rejected ones, append the rest.

MIGRATION_PLAN §2.7: a file with a validation error is never written to the store; it is put
into quarantine with its report, and the run continues with the next file.
"""

from __future__ import annotations

import logging
import shutil
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

from sivin.app.json_files import JsonFileWriter
from sivin.app.outcome import Outcome
from sivin.config.sections import QuarantineMode
from sivin.core.ids import SensorId
from sivin.ingest.parsers.base import (
    AmbiguousExportError,
    ParsedExport,
    ParserRegistry,
    UnsupportedExportError,
)
from sivin.ingest.parsers.columns import ParserSettings
from sivin.ingest.validation import InputValidator, Severity, ValidationIssue, ValidationReport
from sivin.registry.registry import SensorRegistry
from sivin.storage.conflicts import ConflictDecision
from sivin.storage.errors import StoreError
from sivin.storage.merge import AppendCounts
from sivin.storage.store import MeasurementStore

logger = logging.getLogger(__name__)

REPORT_SUFFIX: Final = ".report.json"
"""Suffix of the validation report written next to a quarantined file."""

UNREGISTERED_SENSOR_RULE: Final = "sensor-registered"
"""Rule id of the ingest check that the sensor of a file is in the registry (plan §2.7)."""

UNSUPPORTED_FORMAT_RULE: Final = "export-format"
"""Rule id given to a file that no registered parser accepts."""


class ExportReader:
    """Parse and validate one export file with the parser that accepts it.

    Parameters
    ----------
    parsers : ParserRegistry
        The registered export parsers.
    settings : ParserSettings
        Parser settings (``ingest.parsers``).
    validator : InputValidator
        Input validation with the ``ingest.validation`` thresholds.
    """

    __slots__ = ("_parsers", "_settings", "_validator")

    def __init__(
        self, parsers: ParserRegistry, settings: ParserSettings, validator: InputValidator
    ) -> None:
        self._parsers = parsers
        self._settings = settings
        self._validator = validator

    def read(self, path: Path) -> ParsedExport:
        """Read one file; an unknown format is a rejected file, not an exception.

        Parameters
        ----------
        path : pathlib.Path
            The export file.

        Returns
        -------
        ParsedExport
            Series and validation report; no series if the file is rejected.
        """
        try:
            parser = self._parsers.for_file(path, self._settings, self._validator)
        except (UnsupportedExportError, AmbiguousExportError) as error:
            issue = ValidationIssue(UNSUPPORTED_FORMAT_RULE, Severity.ERROR, str(error))
            return ParsedExport((), path, ValidationReport((issue,)))
        return parser.parse(path)


class Quarantine:
    """Keeps rejected export files together with their validation report.

    ``<directory>/<file name>`` is the file (copied or moved) and
    ``<directory>/<file name>.report.json`` its report: file, reason and every finding.

    Parameters
    ----------
    directory : pathlib.Path
        Quarantine directory (``paths.quarantine_dir``).
    mode : QuarantineMode
        Copy (default) or move the file.
    writer : JsonFileWriter, optional
        Writes the report.
    """

    __slots__ = ("_directory", "_mode", "_writer")

    def __init__(
        self, directory: Path, mode: QuarantineMode, writer: JsonFileWriter | None = None
    ) -> None:
        self._directory = directory
        self._mode = mode
        self._writer = writer if writer is not None else JsonFileWriter()

    def put(self, path: Path, report: ValidationReport) -> Path:
        """Put a rejected file into quarantine.

        Parameters
        ----------
        path : pathlib.Path
            The rejected export file.
        report : ValidationReport
            Why it was rejected.

        Returns
        -------
        pathlib.Path
            The quarantined copy (or moved file).
        """
        self._directory.mkdir(parents=True, exist_ok=True)
        target = self._directory / path.name
        if path.resolve() != target.resolve():
            if self._mode is QuarantineMode.MOVE:
                shutil.move(path, target)
            else:
                shutil.copy2(path, target)
        self._writer.write(
            target.with_name(target.name + REPORT_SUFFIX),
            {
                "file": path.name,
                "source_path": str(path),
                "accepted": False,
                "issues": [_issue_dict(issue) for issue in report.issues],
            },
        )
        logger.warning("Quarantined %s (%s) in %s.", path.name, self._mode, self._directory)
        return target


def _issue_dict(issue: ValidationIssue) -> dict[str, object]:
    return {
        "rule": issue.rule,
        "severity": str(issue.severity),
        "message": issue.message,
        "row": issue.row,
        "table": issue.table,
    }


@dataclass(frozen=True)
class FileOutcome:
    """What happened to one export file.

    Attributes
    ----------
    path : pathlib.Path
        The file.
    report : ValidationReport
        Validation findings (including the ingest's own rules).
    rows : Mapping of SensorId to int
        Rows parsed per sensor (count).
    appends : Mapping of SensorId to AppendCounts
        Store counts per sensor; empty for a rejected file or a dry run.
    conflicts : tuple of ConflictDecision
        Recorded value conflicts of the appends.
    quarantined : pathlib.Path or None
        Where the rejected file was put; ``None`` if it was accepted (or in a dry run).
    failure : str or None
        Why the file was not (completely) imported; ``None`` on success.
    """

    path: Path
    report: ValidationReport
    rows: Mapping[SensorId, int] = field(default_factory=dict)
    appends: Mapping[SensorId, AppendCounts] = field(default_factory=dict)
    conflicts: tuple[ConflictDecision, ...] = ()
    quarantined: Path | None = None
    failure: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", MappingProxyType(dict(self.rows)))
        object.__setattr__(self, "appends", MappingProxyType(dict(self.appends)))

    @property
    def accepted(self) -> bool:
        """``True`` if the file passed validation and every append succeeded."""
        return self.failure is None


@dataclass(frozen=True)
class IngestReport:
    """Outcome of :meth:`IngestService.ingest`.

    Attributes
    ----------
    files : tuple of FileOutcome
        One entry per file, in the order given.
    dry_run : bool
        Nothing was written (store, quarantine).
    """

    files: tuple[FileOutcome, ...] = ()
    dry_run: bool = False

    @property
    def failures(self) -> tuple[str, ...]:
        """One message per file that was rejected or not completely imported."""
        return tuple(
            f"{item.path.name}: {item.failure}" for item in self.files if item.failure is not None
        )

    @property
    def outcome(self) -> Outcome:
        """:attr:`Outcome.PARTIAL_FAILURE` if any file failed."""
        return Outcome.of(self.failures)

    @property
    def appends(self) -> dict[SensorId, AppendCounts]:
        """Store counts summed per sensor over all files."""
        total: dict[SensorId, AppendCounts] = {}
        for item in self.files:
            for sensor_id, counts in item.appends.items():
                total[sensor_id] = total.get(sensor_id, AppendCounts()) + counts
        return total

    @property
    def conflicts(self) -> tuple[ConflictDecision, ...]:
        """Recorded conflicts of all appends."""
        return tuple(decision for item in self.files for decision in item.conflicts)

    @property
    def validation_counts(self) -> dict[str, int]:
        """Number of findings per ``<severity>:<rule>`` over all files."""
        counts = Counter(
            f"{issue.severity}:{issue.rule}" for item in self.files for issue in item.report.issues
        )
        return dict(sorted(counts.items()))


class IngestService:
    """Parse, validate, quarantine or append each export file; one bad file never stops it.

    Parameters
    ----------
    reader : ExportReader
        Parses and validates a file.
    store : MeasurementStore
        Where accepted series are appended.
    registry : SensorRegistry
        A file whose sensor is not registered is rejected (plan §2.7).
    quarantine : Quarantine
        Keeps rejected files.
    dry_run : bool, optional
        Parse and validate only; write nothing.
    """

    __slots__ = ("_dry_run", "_quarantine", "_reader", "_registry", "_store")

    def __init__(
        self,
        reader: ExportReader,
        store: MeasurementStore,
        registry: SensorRegistry,
        quarantine: Quarantine,
        dry_run: bool = False,
    ) -> None:
        self._reader = reader
        self._store = store
        self._registry = registry
        self._quarantine = quarantine
        self._dry_run = dry_run

    def ingest(self, paths: Iterable[Path]) -> IngestReport:
        """Process the files in order.

        Parameters
        ----------
        paths : iterable of pathlib.Path
            Export files.

        Returns
        -------
        IngestReport
            One outcome per file.
        """
        return IngestReport(tuple(self._one(path) for path in paths), self._dry_run)

    def _one(self, path: Path) -> FileOutcome:
        parsed = self._reader.read(path)
        report = self._with_registry_check(parsed)
        if not report.is_acceptable:
            reason = "; ".join(issue.message for issue in report.errors)
            quarantined = None if self._dry_run else self._quarantine.put(path, report)
            logger.warning("Rejected %s: %s", path.name, reason)
            return FileOutcome(path, report, quarantined=quarantined, failure=f"rejected: {reason}")
        rows = {series.sensor_id: len(series) for series in parsed.series}
        if self._dry_run:
            logger.info("Dry run: %s is valid (%s).", path.name, _rows_text(rows))
            return FileOutcome(path, report, rows)
        return self._append(path, parsed, report, rows)

    def _append(
        self,
        path: Path,
        parsed: ParsedExport,
        report: ValidationReport,
        rows: Mapping[SensorId, int],
    ) -> FileOutcome:
        appends: dict[SensorId, AppendCounts] = {}
        conflicts: list[ConflictDecision] = []
        for series in parsed.series:
            try:
                result = self._store.append(series)
            except StoreError as error:
                logger.error(
                    "Appending %s (sensor %s) failed: %s", path.name, series.sensor_id, error
                )
                return FileOutcome(
                    path, report, rows, appends, tuple(conflicts), failure=f"store: {error}"
                )
            appends[series.sensor_id] = result.counts
            conflicts.extend(result.conflicts)
        logger.info("Imported %s (%s).", path.name, _rows_text(rows))
        return FileOutcome(path, report, rows, appends, tuple(conflicts))

    def _with_registry_check(self, parsed: ParsedExport) -> ValidationReport:
        unknown = sorted(
            {str(s.sensor_id) for s in parsed.series if s.sensor_id not in self._registry}
        )
        if not unknown:
            return parsed.report
        issue = ValidationIssue(
            UNREGISTERED_SENSOR_RULE,
            Severity.ERROR,
            f"sensor(s) {', '.join(unknown)} not in the sensor registry; add them to "
            "sensors/sensors.geojson first",
        )
        return ValidationReport((*parsed.report.issues, issue))


def _rows_text(rows: Mapping[SensorId, int]) -> str:
    return ", ".join(f"{sensor}: {count} rows" for sensor, count in rows.items()) or "no rows"


def export_files(directory: Path, patterns: Sequence[str]) -> list[Path]:
    """Return the export files of a directory, sorted by name.

    Parameters
    ----------
    directory : pathlib.Path
        Where to look (not recursive).
    patterns : sequence of str
        Glob patterns, e.g. ``("*.csv", "*.xlsx")`` (``ingest.file_patterns``).

    Returns
    -------
    list of pathlib.Path
        Matching regular files; hidden files are skipped.
    """
    found = {
        path
        for pattern in patterns
        for path in directory.glob(pattern)
        if path.is_file() and not path.name.startswith(".")
    }
    return sorted(found)


class DirectoryExports:
    """Export source of ``sivin run --skip-fetch``: the export files already in a directory.

    Parameters
    ----------
    directory : pathlib.Path
        The directory (normally ``ingest.portal.download_dir``).
    patterns : sequence of str
        Glob patterns (``ingest.file_patterns``).
    """

    __slots__ = ("_directory", "_patterns")

    def __init__(self, directory: Path, patterns: Sequence[str]) -> None:
        self._directory = directory
        self._patterns = tuple(patterns)

    def exports(
        self, sensors: Sequence[SensorId] | None
    ) -> tuple[tuple[Path, ...], tuple[str, ...]]:
        """Return the export files of the directory (see :class:`~sivin.app.run.ExportSource`).

        Parameters
        ----------
        sensors : sequence of SensorId, optional
            Not used: every file is ingested; the ingest rejects unknown sensors.

        Returns
        -------
        tuple
            ``(files, ())``; no file is a failure.
        """
        if not self._directory.is_dir():
            logger.info("%s does not exist; nothing to ingest.", self._directory)
            return (), ()
        return tuple(export_files(self._directory, self._patterns)), ()
