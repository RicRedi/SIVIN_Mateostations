"""Owner-facing texts of the off-site log: the error type, file keys, examples and hints."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from sivin.registry.registry import SensorRegistry

ENTRIES_KEY: Final = "entries"
"""Top-level key of the log file: the list of entries."""

OPEN_END: Final = "open"
"""Value of ``to`` that marks a period that has not ended yet (``null`` is accepted too)."""

REGISTRY_FILE_NAME: Final = "sensors/sensors.geojson"
"""The sensor registry file, named in messages about unknown sensors."""

ENTRY_KEYS: Final = ("sensor", "from", "to", "reason", "note")
"""Keys of one entry, in file order."""

EXAMPLE_LINES: Final[Mapping[str, str]] = {
    "sensor": 'sensor: "77799986"',
    "from": 'from: "2026-03-01 08:00"',
    "to": f'to: "2026-03-05 16:00"   (or  to: {OPEN_END}  if the sensor is still off site)',
    "reason": "reason: service   (office, service, transport, storage or other)",
    "note": 'note: "battery replacement"',
}
"""One example line per key, shown when a key is missing."""

BLANK_HINTS: Final[Mapping[str, str]] = {
    "sensor": 'is empty - write the 8-digit serial in quotes, e.g. sensor: "77799986"',
    "from": 'is empty - write when the sensor left the vineyard, e.g. from: "2026-03-01 08:00"',
    "to": f"is empty - write a date/time, or '{OPEN_END}' if the sensor is still off site",
    "reason": "is empty - write office, service, transport, storage or other",
    "note": "is empty - write a note or delete the line",
}
"""What to do about a key written without a value (``to:`` and nothing after it)."""


class OffSiteLogError(ValueError):
    """Raised when the off-site log cannot be read or violates a rule; names entry and field."""


def unknown_sensor_message(name: str, registry: SensorRegistry) -> str:
    """Explain that the off-site log names a sensor that is not in the registry.

    Lists the known serials and says how a sensor leaves service: it stays in the registry
    with ``status: retired`` (its data and log entries stay valid), it is never deleted.

    Parameters
    ----------
    name : str
        The sensor name as written.
    registry : SensorRegistry
        The registry.

    Returns
    -------
    str
        The message, with the fix.
    """
    known = ", ".join(str(sensor_id) for sensor_id in registry.ids()) or "none"
    return (
        f"the off-site log names sensor {name!r}, which is not in the sensor registry "
        f"{REGISTRY_FILE_NAME} (known sensors: {known}); check the serial, or add the sensor "
        "to the registry. A sensor that left service stays in the registry with status "
        "'retired' instead of being deleted"
    )


def report(problems: Iterable[str]) -> str:
    """Join problems into the text of an :class:`OffSiteLogError`."""
    return "Invalid off-site log:\n" + "\n".join(f"  {p}" for p in dict.fromkeys(problems))
