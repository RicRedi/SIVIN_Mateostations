"""Parser of the legacy workbook ``data.xlsx`` used by the old analysis and plot scripts.

One worksheet per sensor, named by the legacy 4-digit suffix (``9986``, ``8271``, ``0065``,
``0921``), with the columns ``Datum a čas``, ``Teplota``, ``Vlhkost`` (read by
``vineyard_analyst.py`` with ``decimal=','``). The 4-digit suffix is ambiguous, so the caller
passes the worksheet -> sensor mapping (normally resolved through the sensor registry).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from sivin.core.ids import SensorId
from sivin.ingest.parsers.base import parser_registry
from sivin.ingest.parsers.columns import ParserSettings
from sivin.ingest.parsers.portal import WORKBOOK_SUFFIXES, is_portal_export_name
from sivin.ingest.parsers.sources import GridReadError, WorkbookReader
from sivin.ingest.parsers.tabular import (
    LoadedTables,
    SensorTable,
    TabularExportParser,
    TabularExportReader,
)
from sivin.ingest.validation import InputValidator


@parser_registry.register
class LegacyWorkbookParser(TabularExportParser):
    """Legacy multi-sensor workbook: one worksheet per sensor.

    Parameters
    ----------
    settings : ParserSettings, optional
        Parser settings; ``legacy_sheet_sensors`` is the default worksheet mapping.
    validator : InputValidator, optional
        The validator; one with default settings when omitted.
    reader : TabularExportReader, optional
        The shared reading steps; one built from ``settings`` when omitted.
    sheet_sensors : Mapping of str to SensorId, optional
        Worksheet name -> sensor; ``settings.legacy_sheet_ids`` when omitted. Mapped sheets
        missing from the workbook are an error, unmapped sheets are ignored with a warning.
    """

    format_id = "legacy-workbook"

    def __init__(
        self,
        settings: ParserSettings | None = None,
        validator: InputValidator | None = None,
        reader: TabularExportReader | None = None,
        sheet_sensors: Mapping[str, SensorId] | None = None,
    ) -> None:
        super().__init__(settings, validator, reader)
        self._sheet_sensors = dict(
            self.settings.legacy_sheet_ids if sheet_sensors is None else sheet_sensors
        )

    @property
    def sheet_sensors(self) -> Mapping[str, SensorId]:
        """Worksheet name -> sensor (a copy)."""
        return dict(self._sheet_sensors)

    def can_parse(self, path: Path) -> bool:
        """Accept workbooks without a portal export name, if a mapping is configured.

        See :meth:`ExportParser.can_parse`.
        """
        return (
            bool(self._sheet_sensors)
            and path.suffix.casefold() in WORKBOOK_SUFFIXES
            and not is_portal_export_name(path)
        )

    def _load(self, path: Path) -> LoadedTables:
        try:
            grids = WorkbookReader().read(path)
        except GridReadError as error:
            return LoadedTables(read_problem=str(error))
        present = {grid.name for grid in grids}
        return LoadedTables(
            tables=tuple(
                SensorTable(grid, self._sheet_sensors[grid.name])
                for grid in grids
                if grid.name in self._sheet_sensors
            ),
            missing_tables=tuple(sheet for sheet in self._sheet_sensors if sheet not in present),
            ignored_tables=tuple(
                grid.name for grid in grids if grid.name not in self._sheet_sensors
            ),
        )
