"""Steps shared by all tabular export formats.

:class:`TabularExportReader` turns the raw cells of one table into a
:class:`~sivin.ingest.validation.TableInspection` (header located, columns mapped, numbers and
timestamps parsed, local time converted to UTC) and, after validation, into a
:class:`~sivin.core.schema.MeasurementSeries`. :class:`TabularExportParser` is the template of
every concrete parser: check the file, load its tables, inspect, validate, assemble. A concrete
parser only says how its tables are loaded and which sensor each belongs to.
"""

from __future__ import annotations

import logging
import stat
from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import QC_DTYPE, MeasurementSeries
from sivin.core.timeutil import LocalTimeConverter
from sivin.ingest.parsers.base import ExportParser, ParsedExport
from sivin.ingest.parsers.cells import NumberParser, TimestampParser
from sivin.ingest.parsers.columns import CanonicalColumn, ColumnMapping, HeaderMatch, ParserSettings
from sivin.ingest.parsers.order import RowOrder, RowOrderAnalyser
from sivin.ingest.parsers.sources import CellGrid, Row
from sivin.ingest.validation import (
    BoolArray,
    ExportInspection,
    InputValidator,
    RowArray,
    TableInspection,
    TimeColumn,
    ValueColumn,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SensorTable:
    """A table together with the sensor it belongs to.

    Attributes
    ----------
    grid : CellGrid
        The raw cells.
    sensor_id : SensorId or None
        The sensor; ``None`` if it could not be resolved.
    sensor_problem : str or None
        Why the sensor could not be resolved.
    """

    grid: CellGrid
    sensor_id: SensorId | None
    sensor_problem: str | None = None


@dataclass(frozen=True)
class LoadedTables:
    """What a parser loaded from one file, before interpretation.

    Attributes
    ----------
    tables : tuple of SensorTable
        The tables to read.
    read_problem : str or None
        Why the file could not be read; then ``tables`` is empty.
    missing_tables : tuple of str
        Expected tables that are not in the file.
    ignored_tables : tuple of str
        Tables in the file that are not read.
    """

    tables: tuple[SensorTable, ...] = ()
    read_problem: str | None = None
    missing_tables: tuple[str, ...] = ()
    ignored_tables: tuple[str, ...] = ()


@dataclass(frozen=True)
class _DataRows:
    """The non-blank rows below a header, in the order they will be converted."""

    source_rows: RowArray
    cells: dict[CanonicalColumn, list[object]]
    short_rows: RowArray


class TabularExportReader:
    """Interpret the cells of one table and build its measurement series.

    Parameters
    ----------
    settings : ParserSettings
        Column aliases, header search depth, date order and source time zone.
    converter : LocalTimeConverter, optional
        Local-to-UTC conversion; one for ``settings.source_timezone`` when omitted.
    order : RowOrderAnalyser, optional
        Decides whether a table is reversed and how backward steps are repaired; one with
        :class:`~sivin.ingest.parsers.order.SplitAtBackwardSteps` when omitted.
    """

    __slots__ = ("_converter", "_mapping", "_numbers", "_order", "_search_rows", "_timestamps")

    def __init__(
        self,
        settings: ParserSettings,
        converter: LocalTimeConverter | None = None,
        order: RowOrderAnalyser | None = None,
    ) -> None:
        self._mapping = ColumnMapping(settings.aliases)
        self._numbers = NumberParser()
        self._timestamps = TimestampParser(settings.day_first)
        self._converter = converter or LocalTimeConverter(settings.source_timezone)
        self._order = order or RowOrderAnalyser(
            settings.source_timezone, settings.newest_first_min_share
        )
        self._search_rows = settings.header_search_rows

    def inspect(self, table: SensorTable) -> TableInspection:
        """Locate the header, map and parse the columns and convert the timestamps.

        A table that is clearly newest first is reversed. Rows that still step back in local
        time (clock correction, overlapping exports) are handled by the row-order repair
        strategy: by default the rows are converted in separate monotonic segments.

        Parameters
        ----------
        table : SensorTable
            The raw table and its sensor.

        Returns
        -------
        TableInspection
            Everything the validator needs; parsed columns are ``None`` when the header or a
            required column is missing.
        """
        base = TableInspection(
            name=table.grid.name,
            sensor_id=table.sensor_id,
            sensor_problem=table.sensor_problem,
            header_search_rows=self._search_rows,
        )
        header = self._mapping.locate_header(table.grid.rows, self._search_rows)
        if header is None:
            return base
        data = self._data_rows(table.grid.rows, header)
        with_header = replace(
            base,
            header_row=header.row_index + 1,
            missing_columns=tuple(str(column) for column in header.missing),
            column_problems=header.problems,
            source_rows=data.source_rows,
            short_rows=data.short_rows,
        )
        if not header.is_complete:
            return with_header
        local = self._timestamps.parse(data.cells[CanonicalColumn.TIMESTAMP])
        order = self._order.analyse(local)
        if order.newest_first:
            data = _reversed(data)
            local = local.iloc[::-1].reset_index(drop=True)
        return replace(
            with_header,
            source_rows=data.source_rows,
            reversed_order=order.newest_first,
            backward_rows=data.source_rows[order.backward_steps],
            times=self._time_column(header.headers[CanonicalColumn.TIMESTAMP], local, order),
            temp=self._value_column(header, data, CanonicalColumn.TEMP),
            rh=self._value_column(header, data, CanonicalColumn.RH),
        )

    def assemble(self, table: TableInspection, source_name: str) -> MeasurementSeries:
        """Build the series of a table that passed validation.

        Rows without a UTC timestamp and rows whose daylight-saving conversion is unresolved
        are dropped; a repeated timestamp keeps its last row (``MeasurementSeries.from_records``
        does that and logs it); rows without any measured value get ``MISSING`` and
        daylight-saving rows get ``TIMESTAMP_SUSPECT``.

        Parameters
        ----------
        table : TableInspection
            A table inspected by :meth:`inspect` whose file passed validation.
        source_name : str
            Name of the source file, stored in the ``source`` column.

        Returns
        -------
        MeasurementSeries
            The validated series.

        Raises
        ------
        ValueError
            If the table has no sensor or no parsed columns (it cannot have passed validation).
        """
        if table.sensor_id is None or table.times is None or table.temp is None or table.rh is None:
            raise ValueError(f"Table {table.name!r} was not validated successfully.")
        utc = table.times.utc
        keep = utc.notna().to_numpy() & ~table.times.unresolved
        all_missing = np.isnan(table.temp.parsed) & np.isnan(table.rh.parsed)
        qc = np.where(all_missing, int(QcFlag.MISSING), int(QcFlag.OK)) | np.where(
            table.times.suspect, int(QcFlag.TIMESTAMP_SUSPECT), int(QcFlag.OK)
        )
        return MeasurementSeries.from_records(
            table.sensor_id,
            pd.DatetimeIndex(utc[keep]),
            table.temp.parsed[keep],
            table.rh.parsed[keep],
            qc=qc[keep].astype(QC_DTYPE),
            source=source_name,
        )

    def _data_rows(self, rows: Sequence[Row], header: HeaderMatch) -> _DataRows:
        last_needed = max(header.positions.values())
        numbered = [
            (number, row)
            for number, row in enumerate(rows[header.row_index + 1 :], start=header.row_index + 2)
            if not _is_blank(row)
        ]
        cells = {
            column: [row[position] if position < len(row) else None for _, row in numbered]
            for column, position in header.positions.items()
        }
        return _DataRows(
            source_rows=np.array([number for number, _ in numbered], dtype=np.int64),
            cells=cells,
            short_rows=np.array(
                [number for number, row in numbered if len(row) <= last_needed], dtype=np.int64
            ),
        )

    def _time_column(self, header: str, local: pd.Series, order: RowOrder) -> TimeColumn:
        results = [self._converter.to_utc(local.iloc[segment]) for segment in order.segments]
        return TimeColumn(
            header=header,
            local=local,
            utc=pd.concat([result.timestamps_utc for result in results]),
            suspect=np.concatenate([_as_bool(result.suspect) for result in results]),
            unresolved=np.concatenate([_as_bool(result.unresolved) for result in results]),
        )

    def _value_column(
        self, header: HeaderMatch, data: _DataRows, column: CanonicalColumn
    ) -> ValueColumn:
        values, unparseable = self._numbers.parse(data.cells[column])
        return ValueColumn(header.headers[column], values, unparseable)


class TabularExportParser(ExportParser):
    """Template of the parsers of tabular exports (CSV files and workbooks).

    :meth:`parse` checks the file, loads its tables (:meth:`_load`, implemented per format),
    inspects them with a :class:`TabularExportReader`, validates the result and assembles the
    series only if the file passed validation.

    Parameters
    ----------
    settings : ParserSettings, optional
        Parser settings; defaults when omitted.
    validator : InputValidator, optional
        The validator; one with default settings when omitted.
    reader : TabularExportReader, optional
        The shared reading steps; one built from ``settings`` when omitted.
    """

    def __init__(
        self,
        settings: ParserSettings | None = None,
        validator: InputValidator | None = None,
        reader: TabularExportReader | None = None,
    ) -> None:
        super().__init__(settings, validator)
        self._reader = reader or TabularExportReader(self.settings)

    def parse(self, path: Path) -> ParsedExport:
        """Read, validate and convert one export file (see :meth:`ExportParser.parse`)."""
        inspection = self._inspect(path)
        report = self.validator.validate(inspection)
        if not report.is_acceptable:
            logger.warning(
                "Export %s rejected by %s with %d error(s).",
                path.name,
                self.format_id,
                len(report.errors),
            )
            return ParsedExport((), path, report)
        series = tuple(self._reader.assemble(table, path.name) for table in inspection.tables)
        logger.info(
            "Export %s read by %s: %d series, %d row(s), %d warning(s).",
            path.name,
            self.format_id,
            len(series),
            sum(len(one) for one in series),
            len(report.warnings),
        )
        return ParsedExport(series, path, report)

    @abstractmethod
    def _load(self, path: Path) -> LoadedTables:
        """Load the raw tables of an existing, non-empty file and resolve their sensors.

        Parameters
        ----------
        path : pathlib.Path
            The export file.

        Returns
        -------
        LoadedTables
            The tables, or the reason why the file cannot be read.
        """

    def _inspect(self, path: Path) -> ExportInspection:
        size_bytes = _file_size(path)
        if not size_bytes:
            return ExportInspection(path, size_bytes)
        loaded = self._load(path)
        return ExportInspection(
            source=path,
            size_bytes=size_bytes,
            read_problem=loaded.read_problem,
            tables=tuple(self._reader.inspect(table) for table in loaded.tables),
            missing_tables=loaded.missing_tables,
            ignored_tables=loaded.ignored_tables,
        )


def _file_size(path: Path) -> int | None:
    """Return the size of a regular file in bytes, or ``None`` if there is none."""
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_size if stat.S_ISREG(status.st_mode) else None


def _is_blank(row: Row) -> bool:
    return all(cell is None or (isinstance(cell, str) and not cell.strip()) for cell in row)


def _reversed(data: _DataRows) -> _DataRows:
    return _DataRows(
        source_rows=data.source_rows[::-1].copy(),
        cells={column: values[::-1] for column, values in data.cells.items()},
        short_rows=data.short_rows,
    )


def _as_bool(mask: pd.Series) -> BoolArray:
    return np.asarray(mask.to_numpy(), dtype=np.bool_)
