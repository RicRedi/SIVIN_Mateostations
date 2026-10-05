"""Parsers of the data provider's portal exports: CSV and XLSX.

Layout reconstructed from the legacy scripts (``generate_animation.py``, ``chrome_driver.py``,
``sampl_freq_basic.py``): a title row (``Meteo Data;``), a header row with Czech names
(``Datum a čas``, ``Teplota (°C)``, ``Vlhkost (%)``, possibly more columns), values with a
decimal comma and local wall-clock timestamps. The CSV layout is **verified on one real export**
(sensor 77799986, MIGRATION_PLAN §0.6.1): it also has precipitation and battery columns, which
are ignored, is newest first and ends with a line ``;``. The XLSX layout is still unverified.
The header row is searched for, so the number of title rows does not matter. The sensor comes
from the file name, e.g. ``MeteoData_8615620 77678271 (VUT)_20260301_223857.csv`` or
``MeteoData_8615620_77799986_VUT_20260301_223842.csv``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sivin.core.ids import SensorId
from sivin.ingest.parsers.base import parser_registry
from sivin.ingest.parsers.sources import CsvGridReader, GridReadError, WorkbookReader
from sivin.ingest.parsers.tabular import LoadedTables, SensorTable, TabularExportParser

PORTAL_NAME_PREFIX: Final = "meteodata"
"""Case-folded prefix of the file names the portal gives its exports (``MeteoData_...``)."""

WORKBOOK_SUFFIXES: Final = frozenset({".xlsx", ".xlsm"})
"""File name extensions of Excel workbooks that openpyxl reads."""

CSV_SUFFIX: Final = ".csv"
"""File name extension of CSV exports."""


def is_portal_export_name(path: Path) -> bool:
    """Tell whether a file name looks like a portal export.

    Parameters
    ----------
    path : pathlib.Path
        The file.

    Returns
    -------
    bool
        ``True`` if the name starts with ``MeteoData`` (any case) or names a sensor
        (:meth:`SensorId.parse` accepts it).
    """
    if path.name.casefold().startswith(PORTAL_NAME_PREFIX):
        return True
    try:
        SensorId.parse(path.name)
    except ValueError:
        return False
    return True


def sensor_from_file_name(path: Path) -> tuple[SensorId | None, str | None]:
    """Resolve the sensor of a portal export from its file name.

    Parameters
    ----------
    path : pathlib.Path
        The export file.

    Returns
    -------
    tuple
        ``(sensor_id, None)``, or ``(None, reason)`` if the name names no sensor.
    """
    try:
        return SensorId.parse(path.name), None
    except ValueError as error:
        return None, str(error)


@parser_registry.register
class PortalCsvParser(TabularExportParser):
    """Portal export as ``;``-separated CSV (the only CSV format; any ``.csv`` file)."""

    format_id = "portal-csv"

    def can_parse(self, path: Path) -> bool:
        """Accept every ``.csv`` file (see :meth:`ExportParser.can_parse`)."""
        return path.suffix.casefold() == CSV_SUFFIX

    def _load(self, path: Path) -> LoadedTables:
        reader = CsvGridReader(self.settings.csv_delimiter, self.settings.csv_encodings)
        try:
            grid = reader.read(path)
        except GridReadError as error:
            return LoadedTables(read_problem=str(error))
        return LoadedTables((SensorTable(grid, *sensor_from_file_name(path)),))


@parser_registry.register
class PortalXlsxParser(TabularExportParser):
    """Portal export as an Excel workbook; the first worksheet is read, others are ignored."""

    format_id = "portal-xlsx"

    def can_parse(self, path: Path) -> bool:
        """Accept workbooks with a portal export name (see :meth:`ExportParser.can_parse`)."""
        return path.suffix.casefold() in WORKBOOK_SUFFIXES and is_portal_export_name(path)

    def _load(self, path: Path) -> LoadedTables:
        try:
            grids = WorkbookReader().read(path)
        except GridReadError as error:
            return LoadedTables(read_problem=str(error))
        return LoadedTables(
            tuple(SensorTable(grid, *sensor_from_file_name(path)) for grid in grids[:1]),
            ignored_tables=tuple(grid.name for grid in grids[1:]),
        )
