"""Reading ``sensors/offsite_log.yaml`` into an :class:`~sivin.registry.offsite.OffSiteLog`.

Every error names the entry as ``entry #N`` (1-based) with its line and field, and says how
to fix it. Times in messages are local time of the log's zone with UTC in brackets.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import (
    ValidationError,
)

from sivin.core.defaults import DEFAULT_TIMEZONE
from sivin.registry.errors import AmbiguousSensorNameError, SensorLookupError
from sivin.registry.geojson import FILE_ENCODING
from sivin.registry.offsite.local_time import TIMEZONE_CONTEXT_KEY, LocalTimeReader
from sivin.registry.offsite.messages import (
    ENTRIES_KEY,
    ENTRY_KEYS,
    EXAMPLE_LINES,
    OffSiteLogError,
    report,
    unknown_sensor_message,
)
from sivin.registry.offsite.model import OffSiteLog, OffSitePeriod
from sivin.registry.offsite.strict_yaml import LocatedMapping, StrictLogLoader
from sivin.registry.registry import SensorRegistry

logger = logging.getLogger(__name__)


class OffSiteLogStore:
    """Read the off-site log file ``sensors/offsite_log.yaml``."""

    def load(
        self, path: Path, registry: SensorRegistry, timezone: str = DEFAULT_TIMEZONE
    ) -> OffSiteLog:
        """Read and validate the log file.

        Parameters
        ----------
        path : pathlib.Path
            The YAML file.
        registry : SensorRegistry
            Sensor registry; resolves every spelling of a sensor name (including a unique
            legacy short name) and rejects unknown sensors.
        timezone : str, optional
            IANA zone of local times in the file.

        Returns
        -------
        OffSiteLog
            The validated log.

        Raises
        ------
        OffSiteLogError
            If the file cannot be read or is invalid; the message names every offending entry
            (``entry #N``, 1-based, with its line) and field, and says how to fix it.
        """
        try:
            text = path.read_text(encoding=FILE_ENCODING)
        except OSError as error:
            raise OffSiteLogError(f"Cannot read off-site log {path}: {error}") from error
        try:
            log = self.loads(text, registry, timezone)
        except OffSiteLogError as error:
            raise OffSiteLogError(f"{path}: {error}") from error
        logger.info("Loaded %d off-site period(s) from %s", len(log), path)
        return log

    def loads(
        self, text: str, registry: SensorRegistry, timezone: str = DEFAULT_TIMEZONE
    ) -> OffSiteLog:
        """Validate the text of a log file (see :meth:`load`).

        Parameters
        ----------
        text : str
            YAML text.
        registry : SensorRegistry
            Sensor registry.
        timezone : str, optional
            IANA zone of local times.

        Returns
        -------
        OffSiteLog
            The validated log.

        Raises
        ------
        OffSiteLogError
            If the text is invalid.
        """
        try:
            LocalTimeReader(timezone)
        except ValueError as error:
            raise OffSiteLogError(str(error)) from error
        entries = _entries(_parse_yaml(text))
        labels = [_label(index, entry) for index, entry in enumerate(entries)]
        problems: list[str] = []
        periods: list[OffSitePeriod] = []
        for index, entry in enumerate(entries):
            reader = _EntryReader(index, labels[index], registry, timezone)
            period = reader.read(entry)
            problems += reader.problems
            if period is not None:
                periods.append(period)
        if problems:
            raise OffSiteLogError(report(problems))
        return OffSiteLog(periods, registry, timezone=timezone, labels=labels)


def _parse_yaml(text: str) -> Any:
    try:
        return yaml.load(text, Loader=StrictLogLoader)
    except yaml.YAMLError as error:
        raise OffSiteLogError(
            f"not valid YAML (indent with spaces, not tabs; put times and notes in quotes): {error}"
        ) from error


def _entries(raw: Any) -> list[Any]:
    """Return the list under ``entries`` or raise with a hint about the file structure."""
    hint = (
        f"the file must contain one key '{ENTRIES_KEY}:' with a list of entries "
        f"('- sensor: ...'); write '{ENTRIES_KEY}: []' when there are no periods"
    )
    if isinstance(raw, dict):
        unknown = sorted(str(key) for key in raw if key != ENTRIES_KEY)
        if unknown:
            lines = raw.key_lines if isinstance(raw, LocatedMapping) else {}
            where = ", ".join(f"{key!r} (line {lines.get(key, '?')})" for key in unknown)
            raise OffSiteLogError(f"unknown top-level key(s) {where}; {hint}")
    if not isinstance(raw, dict) or not isinstance(raw.get(ENTRIES_KEY), list):
        raise OffSiteLogError(hint)
    entries: list[Any] = raw[ENTRIES_KEY]
    return entries


def _label(index: int, entry: object) -> str:
    """``entry #N (line L)``: how messages name an entry (1-based, as a person counts)."""
    if isinstance(entry, LocatedMapping):
        return f"entry #{index + 1} (line {entry.line})"
    return f"entry #{index + 1}"


_FIX_HINTS: Final[Mapping[str, str]] = {
    "literal_error": " (lower case, exactly one of these)",
    "string_type": " - put the text in quotes",
}
"""Fix appended to pydantic messages by error type."""


class _EntryReader:
    """Validate one raw entry into an :class:`OffSitePeriod` and collect readable problems."""

    def __init__(self, index: int, label: str, registry: SensorRegistry, timezone: str) -> None:
        self._number = f"entry #{index + 1}"
        self._label = label
        self._registry = registry
        self._timezone = timezone
        self.problems: list[str] = []

    def read(self, entry: object) -> OffSitePeriod | None:
        if not isinstance(entry, dict):
            self.problems.append(
                f"{self._label}: must be a list item of keys, starting with "
                f"'- {EXAMPLE_LINES['sensor']}' followed by indented from/to/reason lines"
            )
            return None
        lines = entry.key_lines if isinstance(entry, LocatedMapping) else {}
        values = dict(entry)
        sensor_failed = self._resolve_sensor(values, lines)
        try:
            return OffSitePeriod.model_validate(
                values, context={TIMEZONE_CONTEXT_KEY: self._timezone}
            )
        except ValidationError as error:
            for issue in error.errors():
                field = str(issue["loc"][0]) if issue["loc"] else ""
                if not (sensor_failed and field == "sensor"):
                    self.problems.append(self._describe(issue, field, lines))
            return None

    def _resolve_sensor(self, values: dict[Any, Any], lines: Mapping[str, int]) -> bool:
        """Replace the sensor name by its canonical serial; ``True`` if that failed."""
        name = values.get("sensor")
        if not isinstance(name, str) or not name.strip():
            return False
        try:
            values["sensor"] = str(self._registry.get(name).id)
        except SensorLookupError as error:
            message = str(error)
            if not isinstance(error, AmbiguousSensorNameError):
                message = unknown_sensor_message(name, self._registry)
            self.problems.append(f"{self._where('sensor', lines)}: {message}")
            return True
        return False

    def _where(self, field: str, lines: Mapping[str, int]) -> str:
        line = lines.get(field)
        if line is None:
            return f"{self._label}, '{field}'"
        return f"{self._number}, '{field}' (line {line})"

    def _describe(self, issue: Mapping[str, Any], field: str, lines: Mapping[str, int]) -> str:
        kind = issue["type"]
        if kind == "missing":
            return (
                f"{self._label}: the key '{field}' is missing - add a line like "
                f"{EXAMPLE_LINES.get(field, field + ': ...')}"
            )
        if kind == "extra_forbidden":
            return (
                f"{self._where(field, lines)}: unknown key '{field}' - allowed keys are "
                f"{', '.join(ENTRY_KEYS)} (check the spelling)"
            )
        message = str(issue["msg"]).removeprefix("Value error, ")
        message += _FIX_HINTS.get(kind, "")
        if not field:
            return f"{self._label}: {message}"
        return f"{self._where(field, lines)}: {message}"
