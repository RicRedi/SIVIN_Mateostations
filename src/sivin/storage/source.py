"""Short identifiers of the export a stored row came from (the ``source`` column).

Owner decision of 2026-10-05: the ``source`` column of the store holds a **short export
identifier** instead of the full export file name; the full name is recorded in the run log
(``RunRecord.files``). The identifier is

* the export time from the file name, ``YYYYMMDDTHHMMSS``: the portal names its exports
  ``MeteoData_<device> <serial> (<label>)_<YYYYMMDD>_<HHMMSS>.<ext>`` (also with underscores
  instead of spaces, and with a browser copy suffix `` (1)``), e.g. ``20260301T223842``; a
  bare ``YYYYMMDD_HHMMSS`` is read the same way;
* otherwise ``h`` followed by the first 12 hexadecimal digits of the SHA-256 of the file name
  (without directories), e.g. ``h3f2a9c1b0d4e`` for ``MeteoData_8615620 77678271.xlsx``.

Shortening is idempotent: an identifier is returned unchanged, so values written by this
version and full file names written before it (WP-1.4 to WP-1.9) read back as the same kind
of identifier.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import PureWindowsPath
from typing import Final

from sivin.core.schema import Column, MeasurementSeries

EXPORT_TIME_PATTERN: Final = re.compile(
    r"(?:^|_)(?P<date>[0-9]{8})_(?P<time>[0-9]{6})(?: \([0-9]+\))?(?:\.[A-Za-z0-9]+)?$"
)
"""Export time at the end of a portal file name, ``..._YYYYMMDD_HHMMSS[ (n)].ext``, or a bare
``YYYYMMDD_HHMMSS``."""

TIMESTAMP_ID_PATTERN: Final = re.compile(r"[0-9]{8}T[0-9]{6}")
"""A short identifier made from the export time, ``YYYYMMDDTHHMMSS``."""

HASH_ID_PREFIX: Final = "h"
"""First character of a short identifier made from a hash of the file name."""

HASH_ID_DIGITS: Final = 12
"""Hexadecimal digits of the SHA-256 kept in a hash identifier (48 bits; project choice: unique
enough for the few hundred export names of a sensor, short in every stored row)."""

HASH_ID_PATTERN: Final = re.compile(rf"{HASH_ID_PREFIX}[0-9a-f]{{{HASH_ID_DIGITS}}}")
"""A short identifier made from a hash of the file name."""


class ExportSourceIds:
    """Turn export file names into the short identifiers stored in the ``source`` column."""

    __slots__ = ()

    def of(self, source: str) -> str:
        """Return the short identifier of one source.

        Parameters
        ----------
        source : str
            An export file name or path, an identifier already, or ``""`` (unknown source).

        Returns
        -------
        str
            ``YYYYMMDDTHHMMSS`` when the name carries the export time, the hash identifier
            otherwise; an identifier and ``""`` are returned unchanged.
        """
        if not source or self.is_identifier(source):
            return source
        name = PureWindowsPath(source).name
        match = EXPORT_TIME_PATTERN.search(name)
        if match is not None:
            return f"{match['date']}T{match['time']}"
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        return f"{HASH_ID_PREFIX}{digest[:HASH_ID_DIGITS]}"

    @staticmethod
    def is_identifier(source: str) -> bool:
        """Tell whether a source value already is a short identifier.

        Parameters
        ----------
        source : str
            A value of the ``source`` column.

        Returns
        -------
        bool
            ``True`` for ``YYYYMMDDTHHMMSS`` and ``h`` + 12 hexadecimal digits.
        """
        return bool(TIMESTAMP_ID_PATTERN.fullmatch(source) or HASH_ID_PATTERN.fullmatch(source))

    def shorten(self, series: MeasurementSeries) -> MeasurementSeries:
        """Replace every source of a series by its short identifier.

        Parameters
        ----------
        series : MeasurementSeries
            Measurements whose ``source`` column may hold file names.

        Returns
        -------
        MeasurementSeries
            The same series when nothing changes (no ``source`` column, or identifiers only),
            otherwise a new series with shortened sources.
        """
        frame = series.frame
        if Column.SOURCE not in frame.columns:
            return series
        sources = frame[Column.SOURCE].astype("str")
        mapping = {value: self.of(value) for value in sources.unique()}
        if all(value == short for value, short in mapping.items()):
            return series
        frame[Column.SOURCE] = sources.map(mapping)
        return MeasurementSeries(series.sensor_id, frame)
