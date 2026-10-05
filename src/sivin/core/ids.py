"""Canonical sensor identity (MIGRATION_PLAN §2.4).

The canonical identifier of a sensor is the 8-digit serial number of the device, e.g.
``77678271``. Several other spellings occur in the data provider's portal, in the GPX file and
in exported file names; :meth:`SensorId.parse` turns all of them into the canonical form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Final

SERIAL_DIGITS: Final = 8
"""Number of digits of a device serial number (all sensors deployed in 2025/2026)."""

LEGACY_SUFFIX_DIGITS: Final = 4
"""Length of the legacy short sensor name used by ``vineyard_analyst.yaml`` (e.g. ``8271``)."""

_SERIAL_PATTERN: Final = re.compile(rf"[0-9]{{{SERIAL_DIGITS}}}")

_LEGACY_SUFFIX_PATTERN: Final = re.compile(rf"[0-9]{{{LEGACY_SUFFIX_DIGITS}}}")

_EXPORT_TIMESTAMP: Final = r"[0-9]{8}_[0-9]{6}"
"""Export time stamp appended by the portal, e.g. ``20260301_223857`` (date and time of day)."""

_LABEL_WORD: Final = r"[^\W\d_](?:[^\W_]|-)*"
"""One word of a label: a Unicode letter, then letters, digits or hyphens (e.g. ``VÚT``, ``V2``)."""

_COPY_AND_EXTENSION: Final = r"""
    (?:\s*\((?P<copy>[0-9]+)\))?            # browser copy suffix, e.g. " (1)"
    (?:\.[A-Za-z0-9]+)?                     # file extension, e.g. ".csv" or ".xlsx"
"""

SENSOR_NAME_PATTERN: Final = re.compile(
    rf"""
    (?:MeteoData_)?                     # export file prefix
    (?:(?P<device>[0-9]+)\s+)?               # portal device number, e.g. "8615620 "
    (?P<serial>[0-9]{{{SERIAL_DIGITS}}})     # canonical serial number, e.g. "77678271"
    (?:\s*\((?P<label>[^)]*)\))?            # GPX / export label, e.g. " (VUT)" or "  (VUT)"
    (?:_(?P<exported>{_EXPORT_TIMESTAMP}))?  # export timestamp, e.g. "_20260301_223857"
    {_COPY_AND_EXTENSION}
    """,
    re.VERBOSE,
)
"""Every known spelling of a sensor name with spaces, matched against the whole base name.

Accepted spellings (MIGRATION_PLAN §2.4):

* ``77678271`` (canonical),
* ``8615620 77678271`` (device name in the portal),
* ``77678271 (VUT)`` (waypoint name in ``sensor_location.gpx``),
* ``MeteoData_8615620 77678271 (VUT)_20260301_223857.csv`` (exported file; the portal sometimes
  puts two spaces before the label, and a browser appends `` (1)`` to a repeated download).

Only ASCII digits are accepted.
"""

UNDERSCORE_FILE_NAME_PATTERN: Final = re.compile(
    rf"""
    MeteoData_                                     # export file prefix (required)
    (?:(?P<device>[0-9]{{1,{SERIAL_DIGITS - 1}}})_)?  # portal device number, e.g. "8615620_"
    (?P<serial>[0-9]{{{SERIAL_DIGITS}}})              # canonical serial number
    (?:_(?P<label>{_LABEL_WORD}(?:_{_LABEL_WORD})*))?  # label, e.g. "_VUT", "_VÚT", "_VUT_Brno"
    (?:_(?P<exported>{_EXPORT_TIMESTAMP}))?           # export timestamp
    {_COPY_AND_EXTENSION}
    """,
    re.VERBOSE,
)
"""Export file name with underscores instead of spaces and parentheses.

The first real export arrived as ``MeteoData_8615620_77799986_VUT_20260301_223842.csv``
(owner question Q8: it is not known whether the portal or the upload replaced the spaces).
The spelling is accepted only with the ``MeteoData_`` prefix, and it stays unambiguous because

* the device number is shorter than a serial (the portal's is 7 digits), so a run of
  eight digits after the prefix or after the device number is always the serial,
* a label is one or more ``_``-separated words, each starting with a (Unicode) letter, e.g.
  ``VUT``, ``VÚT`` or ``VUT_Brno``; a word never starts with a digit, so the label never
  swallows the digit groups of the export time, and
* the export time is two digit groups of fixed length (8 and 6) at the end.

So ``MeteoData_77799986_20260301.csv`` is rejected rather than read as sensor ``20260301``.
"""

_NAME_PATTERNS: Final = (SENSOR_NAME_PATTERN, UNDERSCORE_FILE_NAME_PATTERN)
"""All accepted spellings, tried in order.

A name without spaces and without a device number, e.g. ``MeteoData_77799986.csv``, matches
both patterns; both then read the same serial, so the order does not change the result.
"""


@dataclass(frozen=True, slots=True, order=True)
class SensorId:
    """Canonical identifier of a sensor: its 8-digit serial number.

    Parameters
    ----------
    serial : str
        Exactly eight decimal digits, e.g. ``"77678271"``.

    Raises
    ------
    ValueError
        If ``serial`` is not exactly eight digits.

    Examples
    --------
    >>> SensorId.parse("MeteoData_8615620 77678271  (VUT)_20260301_223857.csv")
    SensorId(serial='77678271')
    """

    serial: str

    def __post_init__(self) -> None:
        if not isinstance(self.serial, str) or _SERIAL_PATTERN.fullmatch(self.serial) is None:
            raise ValueError(
                f"A sensor serial number must be exactly {SERIAL_DIGITS} digits, "
                f"got {self.serial!r}."
            )

    @classmethod
    def parse(cls, text: str) -> SensorId:
        """Parse any known spelling of a sensor name or export file path.

        Parameters
        ----------
        text : str
            Canonical serial, portal device name, GPX waypoint name, export file name (with
            spaces or with underscores, see :data:`UNDERSCORE_FILE_NAME_PATTERN`), or a path
            (POSIX or Windows) to an export file. Surrounding whitespace is ignored.

        Returns
        -------
        SensorId
            The canonical identifier.

        Raises
        ------
        ValueError
            If ``text`` is not one of the known spellings. The legacy 4-digit short name
            (e.g. ``"8271"``) is rejected on purpose: it is not unique and can only be resolved
            through the sensor registry.
        """
        name = PureWindowsPath(text.strip()).name.strip()
        for pattern in _NAME_PATTERNS:
            match = pattern.fullmatch(name)
            if match is not None:
                return cls(match.group("serial"))
        if _LEGACY_SUFFIX_PATTERN.fullmatch(name) is not None:
            raise ValueError(
                f"{text!r} looks like a legacy {LEGACY_SUFFIX_DIGITS}-digit short sensor name. "
                "It is ambiguous; resolve it through the sensor registry instead."
            )
        raise ValueError(
            f"Cannot recognise a sensor id in {text!r}. Expected the {SERIAL_DIGITS}-digit "
            "serial, e.g. '77678271', '8615620 77678271', '77678271 (VUT)' or "
            "'MeteoData_8615620 77678271 (VUT)_20260301_223857.csv' or "
            "'MeteoData_8615620_77678271_VUT_20260301_223857.csv'."
        )

    @property
    def legacy_suffix(self) -> str:
        """Return the legacy short name: the last four digits of the serial.

        Returns
        -------
        str
            E.g. ``"8271"`` for ``77678271``.
        """
        return self.serial[-LEGACY_SUFFIX_DIGITS:]

    def __str__(self) -> str:
        return self.serial
