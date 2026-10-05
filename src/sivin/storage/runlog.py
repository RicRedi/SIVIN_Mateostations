"""Append-only JSON Lines log of pipeline runs (``<root>/runs/<YYYY-MM-DD>.jsonl``)."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Self

from sivin.core.ids import SensorId
from sivin.storage.errors import StoreFormatError
from sivin.storage.merge import AppendCounts

logger = logging.getLogger(__name__)

RUNS_DIR: Final = "runs"
"""Directory below the store root that holds the run logs."""

RUN_LOG_SUFFIX: Final = ".jsonl"
"""File-name suffix of a run log (JSON Lines)."""

_UTC_SUFFIX: Final = "+00:00"


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Summary of one pipeline run, one line of the run log.

    Attributes
    ----------
    started_at, finished_at : datetime.datetime
        Timezone-aware start and end of the run; stored in UTC.
    files : tuple of str
        Names of the files the run downloaded or processed.
    appends : Mapping of SensorId to AppendCounts
        Row counts of the store append per sensor.
    validation_issues : Mapping of str to int
        Number of input-validation findings per category (e.g. per severity), as reported by
        the input validator (WP-1.2).
    failures : tuple of str
        One message per failure (file not written, sensor not downloaded, ...).

    Raises
    ------
    ValueError
        If a time is naive or the run ends before it starts.
    """

    started_at: datetime
    finished_at: datetime
    files: tuple[str, ...] = ()
    appends: Mapping[SensorId, AppendCounts] = field(default_factory=dict)
    validation_issues: Mapping[str, int] = field(default_factory=dict)
    failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("started_at", "finished_at"):
            moment: datetime = getattr(self, name)
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware, got {moment!r}.")
            object.__setattr__(self, name, moment.astimezone(UTC))
        if self.finished_at < self.started_at:
            raise ValueError("finished_at is before started_at.")
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "failures", tuple(self.failures))
        object.__setattr__(self, "appends", MappingProxyType(dict(sorted(self.appends.items()))))
        issues = dict(sorted(self.validation_issues.items()))
        object.__setattr__(self, "validation_issues", MappingProxyType(issues))

    @property
    def day(self) -> date:
        """UTC calendar date of :attr:`started_at`; selects the log file."""
        return self.started_at.date()

    def to_dict(self) -> dict[str, Any]:
        """Return the record as JSON-compatible data.

        Returns
        -------
        dict
            Times as ISO 8601 UTC strings with ``Z``; sensors keyed by serial.
        """
        return {
            "started_at": _format_utc(self.started_at),
            "finished_at": _format_utc(self.finished_at),
            "files": list(self.files),
            "appends": {str(sensor): counts.to_dict() for sensor, counts in self.appends.items()},
            "validation_issues": dict(self.validation_issues),
            "failures": list(self.failures),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build a record from :meth:`to_dict` output.

        Parameters
        ----------
        data : Mapping
            Parsed JSON object.

        Returns
        -------
        RunRecord
            The record.

        Raises
        ------
        KeyError, TypeError, ValueError
            If a field is missing or has the wrong type.
        """
        return cls(
            started_at=datetime.fromisoformat(data["started_at"]),
            finished_at=datetime.fromisoformat(data["finished_at"]),
            files=tuple(data["files"]),
            appends={
                SensorId(sensor): AppendCounts.from_dict(counts)
                for sensor, counts in data["appends"].items()
            },
            validation_issues=dict(data["validation_issues"]),
            failures=tuple(data["failures"]),
        )


class RunLog:
    """Append-only run log, one JSON Lines file per UTC date of the run start.

    Parameters
    ----------
    root : pathlib.Path
        Store directory (``data/`` in production); logs live in ``root/runs``.
    """

    __slots__ = ("_directory",)

    def __init__(self, root: Path) -> None:
        self._directory = root / RUNS_DIR

    def path_for(self, day: date) -> Path:
        """Return the log file of a UTC date.

        Parameters
        ----------
        day : datetime.date
            UTC calendar date.

        Returns
        -------
        pathlib.Path
            ``root/runs/<YYYY-MM-DD>.jsonl``.
        """
        return self._directory / f"{day.isoformat()}{RUN_LOG_SUFFIX}"

    def append(self, record: RunRecord) -> Path:
        """Append one record as a single line and flush it to disk.

        Parameters
        ----------
        record : RunRecord
            The run summary.

        Returns
        -------
        pathlib.Path
            The file appended to.
        """
        path = self.path_for(record.day)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        logger.debug("Appended a run record to %s.", path)
        return path

    def read(self, day: date) -> list[RunRecord]:
        """Read all records of a UTC date, in the order they were appended.

        Parameters
        ----------
        day : datetime.date
            UTC calendar date.

        Returns
        -------
        list of RunRecord
            Empty when no run was logged that day.

        Raises
        ------
        StoreFormatError
            If a line is not a valid record.
        """
        path = self.path_for(day)
        if not path.exists():
            return []
        records = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                records.append(RunRecord.from_dict(json.loads(line)))
            except (KeyError, TypeError, ValueError, AttributeError) as error:
                raise StoreFormatError(f"{path}:{number}: invalid run record: {error}") from error
        return records


def _format_utc(moment: datetime) -> str:
    """Format an aware UTC datetime as ISO 8601 with ``Z``."""
    return moment.isoformat().replace(_UTC_SUFFIX, "Z")
