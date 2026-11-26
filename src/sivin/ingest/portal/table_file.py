"""Writing rows read from the device table as a file in the layout of the portal's CSV export.

The file goes into the download directory next to the downloaded exports, so the existing
ingest path (parser, validation, quarantine, store, run record) handles it unchanged. Its name
``MeteoData_<device number> <serial> (<label>)_<YYYYMMDD>_<HHMMSS>.csv`` names the sensor for
:class:`~sivin.core.ids.SensorId`, carries the time it was written (the store's short source
identifier, :class:`~sivin.storage.source.ExportSourceIds`) and the label marks the origin.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from sivin.core.ids import SENSOR_NAME_PATTERN
from sivin.ingest.portal.errors import TableReadError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.settings import PortalTableSettings
from sivin.ingest.portal.table import TableReading

logger = logging.getLogger(__name__)

TITLE_ROW: Final = ("Meteo Data", "")
"""First row of the export, written as ``Meteo Data;`` (MIGRATION_PLAN §0.6.1)."""

TRAILER_ROW: Final = ("", "")
"""Last row of the export, written as ``;``."""

DELIMITER: Final = ";"
LINE_END: Final = "\r\n"
ENCODING: Final = "utf-8"
"""Delimiter, line end and encoding of the real CSV export (CRLF, UTF-8)."""

FILE_PREFIX: Final = "MeteoData_"
FILE_SUFFIX: Final = ".csv"
FILE_TIME_FORMAT: Final = "%Y%m%d_%H%M%S"
"""Export time in the file name, local wall-clock time like the portal's own exports."""

PARTIAL_SUFFIX: Final = ".tmp"
"""Ending of the file while it is written; ignored by the download watcher and by the ingest."""

MAX_COPY_NUMBER: Final = 99
"""Highest `` (n)`` copy suffix tried when a file of the same name exists (count)."""


class TableCsvWriter:
    """Write a :class:`~sivin.ingest.portal.table.TableReading` as a portal CSV export.

    Parameters
    ----------
    settings : PortalTableSettings
        ``file_label`` and ``source_timezone`` (zone of the time in the file name).
    directory : pathlib.Path
        The download directory (absolute).
    """

    __slots__ = ("_directory", "_settings", "_zone")

    def __init__(self, settings: PortalTableSettings, directory: Path) -> None:
        self._settings = settings
        self._directory = directory
        self._zone = ZoneInfo(settings.source_timezone)

    def write(self, device: PortalDevice, reading: TableReading, now_utc: datetime) -> Path:
        """Write the rows into a new file.

        Parameters
        ----------
        device : PortalDevice
            The device; its name must name a sensor.
        reading : TableReading
            Columns and rows (newest first, as in the export).
        now_utc : datetime.datetime
            Time of writing (timezone-aware), for the file name.

        Returns
        -------
        pathlib.Path
            The written file.

        Raises
        ------
        TableReadError
            If the device name names no sensor, or every candidate file name exists.
        OSError
            If the file cannot be written.
        """
        path = self._free_path(self.file_name(device, now_utc))
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator=LINE_END)
        writer.writerow(TITLE_ROW)
        writer.writerow(reading.columns)
        writer.writerows(row.cells for row in reading.rows)
        writer.writerow(TRAILER_ROW)
        partial = path.with_name(path.name + PARTIAL_SUFFIX)
        partial.write_bytes(buffer.getvalue().encode(ENCODING))
        partial.replace(path)
        logger.info("Wrote %d table row(s) of %s to %s.", len(reading.rows), device, path.name)
        return path

    def file_name(self, device: PortalDevice, now_utc: datetime) -> str:
        """Return the file name for a device.

        Parameters
        ----------
        device : PortalDevice
            The device.
        now_utc : datetime.datetime
            Time of writing (timezone-aware).

        Returns
        -------
        str
            ``MeteoData_<device number> <serial> (<label>)_<YYYYMMDD>_<HHMMSS>.csv``. A label
            of the device name (``8615620 77799986 (VUT)``) is replaced by ``file_label``:
            ``SensorId`` accepts one label only.

        Raises
        ------
        TableReadError
            If the device name names no sensor.
        ValueError
            If ``now_utc`` is naive.
        """
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware.")
        stamp = now_utc.astimezone(UTC).astimezone(self._zone).strftime(FILE_TIME_FORMAT)
        parts = SENSOR_NAME_PATTERN.fullmatch(device.name.strip())
        if parts is None or device.sensor_id is None:
            raise TableReadError(
                f"The device name {device.name!r} does not name a sensor, so a table file "
                "cannot be attributed to one."
            )
        device_number = parts["device"]
        base = f"{device_number} {parts['serial']}" if device_number else parts["serial"]
        return f"{FILE_PREFIX}{base} ({self._settings.file_label})_{stamp}{FILE_SUFFIX}"

    def _free_path(self, name: str) -> Path:
        """Return a path that does not exist yet, adding `` (n)`` like a browser does."""
        path = self._directory / name
        stem = name.removesuffix(FILE_SUFFIX)
        for number in range(1, MAX_COPY_NUMBER + 1):
            if not path.exists():
                return path
            path = self._directory / f"{stem} ({number}){FILE_SUFFIX}"
        if not path.exists():
            return path
        raise TableReadError(f"Too many files named like {name!r} in {self._directory}.")
