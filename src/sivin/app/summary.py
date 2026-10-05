"""Summary of a pipeline run for people: the run record plus the current QC warnings.

``sivin report`` (WP-4.1) reads the last run record of the run log
(``<paths.data_dir>/runs/<YYYY-MM-DD>.jsonl``) and the derived events files
(``<paths.derived_dir>/events/<sensor_id>.json``) and turns them into a :class:`RunSummary`.
A :class:`~sivin.app.summary_formats.SummaryFormat` renders it, e.g. as the Markdown job summary
of the scheduled workflow. Nothing here writes a file.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from sivin.app.json_files import read_document
from sivin.app.quality import EVENTS_FILE, STATUS_FAILED
from sivin.core.ids import SensorId
from sivin.storage.merge import AppendCounts
from sivin.storage.runlog import RUN_LOG_SUFFIX, RunLog, RunRecord

logger = logging.getLogger(__name__)

LATEST_RUN: Final = "latest"
"""Value of ``--run`` that selects the most recent run record."""

WARNING_SEVERITY: Final = "warning"
"""``severity`` of a QC event that the summary lists as a warning (``docs/storage.md``)."""

DEFAULT_MAX_ITEMS: Final = 50
"""Default cap of listed items per section; keeps a job summary short and far below GitHub's
1 MiB limit for ``$GITHUB_STEP_SUMMARY`` even with long failure messages."""


class SummarySettings(BaseModel):
    """Settings of the run summary (proposed configuration section ``report``).

    Attributes
    ----------
    max_items : int
        Most items listed per section (files, failures, warnings) [count].
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_items: int = Field(
        DEFAULT_MAX_ITEMS,
        ge=1,
        description="Most items listed per section of the run summary (failures, rejected "
        "files, warnings); the rest is counted [count]. Keeps the Actions job summary short.",
    )


class ExitStatus(StrEnum):
    """Names and meanings of the exit codes of ``sivin`` (``docs/cli.md``) for the summary."""

    OK = "OK"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    USAGE_ERROR = "USAGE_ERROR"
    SETUP_ERROR = "SETUP_ERROR"
    DATA_SOURCE_UNAVAILABLE = "DATA_SOURCE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INTERRUPTED = "INTERRUPTED"
    UNKNOWN = "UNKNOWN"


_EXIT_STATUSES: Final = MappingProxyType(
    {
        0: (ExitStatus.OK, "Everything succeeded."),
        1: (ExitStatus.PARTIAL_FAILURE, "The run finished, but some items failed (see below)."),
        2: (ExitStatus.USAGE_ERROR, "Invalid command line; the workflow file needs fixing."),
        3: (
            ExitStatus.SETUP_ERROR,
            "Nothing was processed: invalid configuration, sensor registry or off-site log.",
        ),
        4: (
            ExitStatus.DATA_SOURCE_UNAVAILABLE,
            "The portal could not be used (credentials, login, portal or browser); the stored "
            "data were processed and published again.",
        ),
        5: (ExitStatus.INTERNAL_ERROR, "Unexpected error (a bug); see the job log."),
        130: (ExitStatus.INTERRUPTED, "The run was interrupted."),
    }
)
"""Exit code → (name, meaning). 130 = 128 + SIGINT (Click's ``Aborted!``)."""


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """The exit code of the command whose run is summarised.

    Attributes
    ----------
    code : int
        Process exit code.
    """

    code: int

    @property
    def status(self) -> ExitStatus:
        """The name of the code (:attr:`ExitStatus.UNKNOWN` for a code ``sivin`` never uses)."""
        return _EXIT_STATUSES.get(self.code, (ExitStatus.UNKNOWN, ""))[0]

    @property
    def meaning(self) -> str:
        """One sentence on what the code means for the published data."""
        return _EXIT_STATUSES.get(self.code, (ExitStatus.UNKNOWN, "Unknown exit code."))[1]


class FailureKind(StrEnum):
    """The pipeline step a failure message of the run record comes from."""

    FETCH = "fetch"
    REJECTED = "rejected"
    STORE = "store"
    QC = "qc"
    INDICES = "indices"
    SITE = "site"
    OTHER = "other"


_FAILURE_PATTERNS: Final = (
    (FailureKind.FETCH, re.compile(r"fetch[ :]")),
    (FailureKind.QC, re.compile(r"qc ")),
    (FailureKind.INDICES, re.compile(r"indices ")),
    (FailureKind.SITE, re.compile(r"site[ :]")),
    (FailureKind.REJECTED, re.compile(r"[^:]+: rejected: ")),
    (FailureKind.STORE, re.compile(r"[^:]+: store: ")),
)
"""Prefixes of the failure messages written by the application services (``sivin.app``):
``fetch <device>: …`` / ``fetch: …``, ``qc <sensor>: …``, ``indices <sensor>…``,
``site <sensor>: …`` / ``site: …``, ``<file>: rejected: …`` and ``<file>: store: …``."""


def classify_failure(message: str) -> FailureKind:
    """Return the step a failure message of the run record belongs to.

    Parameters
    ----------
    message : str
        One entry of :attr:`RunRecord.failures`.

    Returns
    -------
    FailureKind
        The first kind whose prefix matches; :attr:`FailureKind.OTHER` otherwise.
    """
    for kind, pattern in _FAILURE_PATTERNS:
        if pattern.match(message):
            return kind
    return FailureKind.OTHER


@dataclass(frozen=True, slots=True)
class WarningGroup:
    """The QC warnings of one kind for one sensor, from its derived events file.

    Attributes
    ----------
    sensor_id : str
        Canonical sensor id.
    kind : str
        Event ``type``, e.g. ``low_battery`` or ``unlogged_off_site``.
    count : int
        Number of such warnings over the sensor's whole stored record [count].
    latest_t : str or None
        Start of the most recent one (ISO 8601 UTC, as stored).
    latest_t_end : str or None
        End of the most recent one, if it is an interval.
    latest_detail : str
        Description of the most recent one (QC text).
    """

    sensor_id: str
    kind: str
    count: int
    latest_t: str | None
    latest_t_end: str | None
    latest_detail: str


@dataclass(frozen=True, slots=True)
class DerivedFailure:
    """A derived events file whose last computation failed (the previous result is kept).

    Attributes
    ----------
    sensor_id : str
        Canonical sensor id.
    error : str
        The recorded error (already publishable, see ``docs/storage.md``).
    """

    sensor_id: str
    error: str


@dataclass(frozen=True)
class RunSummary:
    """Everything the job summary shows.

    Attributes
    ----------
    record : RunRecord or None
        The selected run record; ``None`` when the run wrote none (e.g. exit code 3).
    outcome : RunOutcome or None
        Exit code of the summarised command, when the caller knows it.
    warnings : tuple of WarningGroup
        QC warnings per sensor and kind, most recent first.
    derived_failures : tuple of DerivedFailure
        Events files marked ``failed``.
    display_timezone : str
        IANA zone for the local time of the run start.
    settings : SummarySettings
        Limits of the rendering.
    """

    record: RunRecord | None
    outcome: RunOutcome | None = None
    warnings: tuple[WarningGroup, ...] = ()
    derived_failures: tuple[DerivedFailure, ...] = ()
    display_timezone: str = "UTC"
    settings: SummarySettings = field(default_factory=SummarySettings)

    @property
    def failures_by_kind(self) -> Mapping[FailureKind, tuple[str, ...]]:
        """Failure messages of the record per step, in the order of :class:`FailureKind`."""
        if self.record is None:
            return MappingProxyType({})
        grouped: dict[FailureKind, list[str]] = {}
        for message in self.record.failures:
            grouped.setdefault(classify_failure(message), []).append(message)
        return MappingProxyType(
            {kind: tuple(grouped[kind]) for kind in FailureKind if kind in grouped}
        )

    @property
    def rejected_files(self) -> tuple[str, ...]:
        """Failure messages of rejected export files."""
        return self.failures_by_kind.get(FailureKind.REJECTED, ())

    @property
    def other_failures(self) -> tuple[str, ...]:
        """Every failure message except the rejected files."""
        return tuple(
            message
            for kind, messages in self.failures_by_kind.items()
            if kind is not FailureKind.REJECTED
            for message in messages
        )

    @property
    def appends(self) -> Mapping[SensorId, AppendCounts]:
        """Store append counts per sensor (empty without a record)."""
        return self.record.appends if self.record is not None else MappingProxyType({})

    @property
    def new_rows(self) -> int:
        """Rows added to the store in this run over all sensors [count]."""
        return sum(counts.new_rows for counts in self.appends.values())


class RunSelectionError(ValueError):
    """Raised for a ``--run`` value that is neither ``latest`` nor a date ``YYYY-MM-DD``."""


@dataclass(frozen=True, slots=True)
class RunSelection:
    """Which run record to summarise: the latest one, or the last one of a UTC date.

    Attributes
    ----------
    day : datetime.date or None
        UTC date of the run start; ``None`` selects the most recent record of any date.
    since : datetime.datetime or None
        Ignore records started before this instant (aware). The workflow passes its own start,
        so a run that wrote no record is not summarised with yesterday's record.
    """

    day: date | None = None
    since: datetime | None = None

    def __post_init__(self) -> None:
        if self.since is not None and self.since.utcoffset() is None:
            raise RunSelectionError(f"since must be timezone-aware, got {self.since!r}.")

    @classmethod
    def parse(cls, run: str, since: str | None = None) -> RunSelection:
        """Build a selection from the command-line values.

        Parameters
        ----------
        run : str
            ``latest`` or a UTC date ``YYYY-MM-DD``.
        since : str, optional
            ISO 8601 instant; a value without offset is taken as UTC.

        Returns
        -------
        RunSelection
            The selection.

        Raises
        ------
        RunSelectionError
            If a value cannot be parsed.
        """
        try:
            day = None if run == LATEST_RUN else date.fromisoformat(run)
        except ValueError as error:
            raise RunSelectionError(
                f"--run must be '{LATEST_RUN}' or a date YYYY-MM-DD, got {run!r}."
            ) from error
        moment = None
        if since is not None:
            try:
                moment = datetime.fromisoformat(since)
            except ValueError as error:
                raise RunSelectionError(
                    f"--since must be an ISO 8601 time, got {since!r}."
                ) from error
            if moment.utcoffset() is None:
                moment = moment.replace(tzinfo=UTC)
        return cls(day, moment)

    def accepts(self, record: RunRecord) -> bool:
        """Tell whether ``record`` is recent enough.

        Parameters
        ----------
        record : RunRecord
            A run record.

        Returns
        -------
        bool
            ``False`` if it started before :attr:`since`.
        """
        return self.since is None or record.started_at >= self.since


class RunRecordFinder:
    """Find a run record in the run log of the store.

    Parameters
    ----------
    run_log : RunLog
        The store's run log.
    directory : pathlib.Path
        The directory of the run-log files (``<paths.data_dir>/runs``).
    """

    __slots__ = ("_directory", "_run_log")

    def __init__(self, run_log: RunLog, directory: Path) -> None:
        self._run_log = run_log
        self._directory = directory

    def days(self) -> list[date]:
        """Return the UTC dates that have a run-log file, newest first.

        Returns
        -------
        list of datetime.date
            Files whose name is not ``<YYYY-MM-DD>.jsonl`` are ignored.
        """
        if not self._directory.is_dir():
            return []
        days = []
        for path in self._directory.glob(f"*{RUN_LOG_SUFFIX}"):
            try:
                days.append(date.fromisoformat(path.stem))
            except ValueError:
                logger.debug("Ignored %s: not a run-log file name.", path.name)
        return sorted(days, reverse=True)

    def find(self, selection: RunSelection) -> RunRecord | None:
        """Return the newest record matching ``selection``.

        Parameters
        ----------
        selection : RunSelection
            Date and lower time bound.

        Returns
        -------
        RunRecord or None
            The record that started last (the last line of its file wins a tie); ``None``
            if there is none.
        """
        days = [selection.day] if selection.day is not None else self.days()
        for day in days:
            records = [record for record in self._run_log.read(day) if selection.accepts(record)]
            if records:
                return max(reversed(records), key=lambda record: record.started_at)
        return None


class WarningCollector:
    """Collect the QC warnings and failed computations from the derived events files.

    Parameters
    ----------
    directory : pathlib.Path
        ``<paths.derived_dir>/events``.
    """

    __slots__ = ("_directory",)

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def documents(self) -> list[dict[str, Any]]:
        """Return the readable events files (``<8 digits>.json``), sorted by sensor.

        Returns
        -------
        list of dict
            Parsed documents; unreadable files are skipped with a warning.
        """
        if not self._directory.is_dir():
            return []
        paths = sorted(
            path
            for path in self._directory.glob("*.json")
            if EVENTS_FILE.fullmatch(path.name) is not None
        )
        return [document for path in paths if (document := read_document(path)) is not None]

    def collect(self) -> tuple[tuple[WarningGroup, ...], tuple[DerivedFailure, ...]]:
        """Group the warning events per sensor and kind; list the failed files.

        Returns
        -------
        tuple
            ``(warnings, failures)``; warnings sorted by the start of their latest event,
            most recent first, then by sensor and kind.
        """
        groups: list[WarningGroup] = []
        failures: list[DerivedFailure] = []
        for document in self.documents():
            sensor = str(document.get("sensor_id", "?"))
            if document.get("status") == STATUS_FAILED:
                failures.append(DerivedFailure(sensor, str(document.get("error", ""))))
            groups.extend(warning_groups(sensor, document.get("events", [])))
        groups.sort(key=lambda group: (group.sensor_id, group.kind))
        groups.sort(key=lambda group: group.latest_t or "", reverse=True)
        return tuple(groups), tuple(failures)


def warning_groups(sensor_id: str, events: Sequence[Any]) -> list[WarningGroup]:
    """Group the warning events of one sensor by kind.

    Parameters
    ----------
    sensor_id : str
        Canonical sensor id.
    events : sequence
        The ``events`` list of an events file; entries that are not objects are ignored.

    Returns
    -------
    list of WarningGroup
        One group per kind with a ``warning`` severity.
    """
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        if isinstance(event, Mapping) and event.get("severity") == WARNING_SEVERITY:
            by_kind.setdefault(str(event.get("type", "?")), []).append(event)
    groups = []
    for kind, items in sorted(by_kind.items()):
        latest = max(items, key=lambda item: str(item.get("t") or ""))
        groups.append(
            WarningGroup(
                sensor_id,
                kind,
                len(items),
                _text_or_none(latest.get("t")),
                _text_or_none(latest.get("t_end")),
                str(latest.get("detail") or ""),
            )
        )
    return groups


def _text_or_none(value: object) -> str | None:
    return None if value is None else str(value)


class RunSummaryService:
    """Build the :class:`RunSummary` of a run from the run log and the derived events.

    Parameters
    ----------
    finder : RunRecordFinder
        Finds the run record.
    warnings : WarningCollector
        Reads the events files.
    display_timezone : str
        IANA zone for the local start time.
    settings : SummarySettings, optional
        Limits of the rendering.
    redact : callable, optional
        Hides the credentials in every text taken from the files (file names, failures, event
        details, errors). Applied **before** a format escapes the text, because an escaped
        secret (e.g. ``a\\_b`` in Markdown) would no longer match the console's redactor.
        Identity when omitted.
    """

    __slots__ = ("_finder", "_redact", "_settings", "_warnings", "_zone")

    def __init__(
        self,
        finder: RunRecordFinder,
        warnings: WarningCollector,
        display_timezone: str,
        settings: SummarySettings | None = None,
        redact: Callable[[str], str] | None = None,
    ) -> None:
        self._redact = redact if redact is not None else _same
        self._finder = finder
        self._warnings = warnings
        self._zone = display_timezone
        self._settings = settings if settings is not None else SummarySettings()

    def summarise(self, selection: RunSelection, outcome: RunOutcome | None = None) -> RunSummary:
        """Return the summary of the selected run.

        Parameters
        ----------
        selection : RunSelection
            Which record.
        outcome : RunOutcome, optional
            Exit code of the summarised command.

        Returns
        -------
        RunSummary
            Record (or ``None``), warnings and failed derived files.
        """
        redact = self._redact
        record = self._finder.find(selection)
        if record is None:
            logger.warning("No run record matches the selection.")
        else:
            record = replace(
                record,
                files=tuple(map(redact, record.files)),
                failures=tuple(map(redact, record.failures)),
            )
        warnings, failures = self._warnings.collect()
        return RunSummary(
            record,
            outcome,
            tuple(replace(group, latest_detail=redact(group.latest_detail)) for group in warnings),
            tuple(replace(item, error=redact(item.error)) for item in failures),
            self._zone,
            self._settings,
        )


def _same(text: str) -> str:
    return text
