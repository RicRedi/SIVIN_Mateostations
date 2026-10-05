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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import QC_DTYPE, MeasurementSeries
from sivin.core.timeutil import LocalTimeConverter
from sivin.ingest.parsers.base import ExportParser, ParsedExport
from sivin.ingest.parsers.cells import DateOrderCheck, NumberParser, TimestampParser
from sivin.ingest.parsers.columns import CanonicalColumn, ColumnMapping, HeaderMatch, ParserSettings
from sivin.ingest.parsers.order import RowOrder, RowOrderAnalyser
from sivin.ingest.parsers.sources import CellGrid, Row
from sivin.ingest.validation import (
    BoolArray,
    ExportInspection,
    FloatArray,
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
        Decides whether a table is reversed, which rows are out of sequence and how backward
        steps are repaired; one built from ``settings`` when omitted.
    now_utc : datetime.datetime, optional
        The run time (timezone-aware), the base of the latest plausible timestamp; the current
        time when omitted. Ignored if ``settings.latest_timestamp`` is set.
    """

    __slots__ = (
        "_converter",
        "_date_order",
        "_mapping",
        "_numbers",
        "_order",
        "_range",
        "_search_rows",
        "_timestamps",
    )

    def __init__(
        self,
        settings: ParserSettings,
        converter: LocalTimeConverter | None = None,
        order: RowOrderAnalyser | None = None,
        now_utc: datetime | None = None,
    ) -> None:
        self._mapping = ColumnMapping(settings.aliases)
        self._numbers = NumberParser()
        self._timestamps = TimestampParser(settings.day_first)
        self._date_order = DateOrderCheck(
            settings.day_first, settings.expected_interval_s * settings.long_step_factor
        )
        self._range = PlausibleRange.from_settings(settings, now_utc or datetime.now(UTC))
        self._converter = converter or LocalTimeConverter(settings.source_timezone)
        self._order = order or RowOrderAnalyser(
            settings.source_timezone,
            settings.newest_first_min_share,
            settings.newest_first_min_steps,
            settings.max_backward_step_s,
        )
        self._search_rows = settings.header_search_rows

    def inspect(self, table: SensorTable) -> TableInspection:
        """Locate the header, map and parse the columns and convert the timestamps.

        Implausible timestamps are set aside, a table that is clearly newest first is
        reversed, out-of-sequence rows (far earlier than the rows before them, or isolated far
        ahead) are set aside, and the remaining
        backward steps are repaired (by default: converted in separate monotonic segments).
        See :mod:`sivin.ingest.parsers.order`.

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
            optional_column_problems=header.optional_problems,
            source_rows=data.source_rows,
            short_rows=data.short_rows,
        )
        if not header.is_complete:
            return with_header
        cells = data.cells[CanonicalColumn.TIMESTAMP]
        local = self._timestamps.parse(cells)
        date_order_problem = self._date_order.problem(cells, local)
        implausible = self._range.outside(local)
        order = self._order.analyse(local.mask(implausible))
        if order.newest_first:
            data = _reversed(data)
            local = local.iloc[::-1].reset_index(drop=True)
            implausible = implausible[::-1].copy()
        return replace(
            with_header,
            source_rows=data.source_rows,
            reversed_order=order.newest_first,
            backward_rows=data.source_rows[order.backward_steps],
            order_undecided=order.undecided,
            date_order_problem=date_order_problem,
            times=self._time_column(
                header.headers[CanonicalColumn.TIMESTAMP], local, implausible, order
            ),
            temp=self._value_column(header, data, CanonicalColumn.TEMP),
            rh=self._value_column(header, data, CanonicalColumn.RH),
            precip=self._optional_column(header, data, CanonicalColumn.PRECIP),
            precip_total=self._optional_column(header, data, CanonicalColumn.PRECIP_TOTAL),
            battery=self._optional_column(header, data, CanonicalColumn.BATTERY),
        )

    def assemble(self, table: TableInspection, source_name: str) -> MeasurementSeries:
        """Build the series of a table that passed validation.

        Rows without a UTC timestamp and rows whose daylight-saving conversion is unresolved
        are dropped; a repeated timestamp keeps its last row (``MeasurementSeries.from_records``
        does that and logs it); rows without a temperature **or** without a humidity get
        ``MISSING`` (whole-row validity, owner decision 2026-10-05) and daylight-saving rows
        get ``TIMESTAMP_SUSPECT``. The optional columns (precipitation, counter, battery) are
        carried over when the table has them and are ``NaN`` otherwise; a missing optional
        value never sets ``MISSING`` (owner decision Q9).

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
        incomplete = np.isnan(table.temp.parsed) | np.isnan(table.rh.parsed)
        qc = np.where(incomplete, int(QcFlag.MISSING), int(QcFlag.OK)) | np.where(
            table.times.suspect, int(QcFlag.TIMESTAMP_SUSPECT), int(QcFlag.OK)
        )
        return MeasurementSeries.from_records(
            table.sensor_id,
            pd.DatetimeIndex(utc[keep]),
            table.temp.parsed[keep],
            table.rh.parsed[keep],
            qc=qc[keep].astype(QC_DTYPE),
            source=source_name,
            precip_mm=_kept(table.precip, keep),
            precip_total_mm=_kept(table.precip_total, keep),
            battery_v=_kept(table.battery, keep),
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

    def _time_column(
        self, header: str, local: pd.Series, implausible: BoolArray, order: RowOrder
    ) -> TimeColumn:
        converted = local.mask(implausible | order.out_of_sequence)
        results = [self._converter.to_utc(converted.iloc[segment]) for segment in order.segments]
        unresolved = np.concatenate([_as_bool(result.unresolved) for result in results])
        return TimeColumn(
            header=header,
            local=local,
            utc=pd.concat([result.timestamps_utc for result in results]),
            suspect=np.concatenate([_as_bool(result.suspect) for result in results]),
            unresolved=unresolved | self._order.incomplete_transitions(converted, order),
            implausible=implausible,
            out_of_sequence=order.out_of_sequence,
        )

    def _value_column(
        self, header: HeaderMatch, data: _DataRows, column: CanonicalColumn
    ) -> ValueColumn:
        values, unparseable = self._numbers.parse(data.cells[column])
        return ValueColumn(header.headers[column], values, unparseable)

    def _optional_column(
        self, header: HeaderMatch, data: _DataRows, column: CanonicalColumn
    ) -> ValueColumn | None:
        if column not in header.positions:
            return None
        return self._value_column(header, data, column)


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


@dataclass(frozen=True)
class PlausibleRange:
    """The range of plausible naive local timestamps.

    Attributes
    ----------
    earliest, latest : datetime.datetime
        Inclusive bounds, naive local wall-clock time.
    """

    earliest: datetime
    latest: datetime

    @classmethod
    def from_settings(cls, settings: ParserSettings, now_utc: datetime) -> PlausibleRange:
        """Build the range of ``settings`` for a run at ``now_utc``.

        Parameters
        ----------
        settings : ParserSettings
            ``earliest_timestamp``, ``latest_timestamp`` or ``max_future_s``, and the zone.
        now_utc : datetime.datetime
            Timezone-aware run time.

        Returns
        -------
        PlausibleRange
            The range; ``latest`` is the run time plus ``max_future_s`` in local time unless
            ``latest_timestamp`` is set.
        """
        latest = settings.latest_timestamp
        if latest is None:
            future = now_utc + timedelta(seconds=settings.max_future_s)
            latest = future.astimezone(ZoneInfo(settings.source_timezone)).replace(tzinfo=None)
        return cls(settings.earliest_timestamp, latest)

    def outside(self, local: pd.Series) -> BoolArray:
        """Tell which readable timestamps lie outside the range.

        Parameters
        ----------
        local : pandas.Series
            Naive local timestamps (``NaT`` is not outside).

        Returns
        -------
        numpy.ndarray of bool
            ``True`` for implausible rows.
        """
        outside = (local < pd.Timestamp(self.earliest)) | (local > pd.Timestamp(self.latest))
        return np.asarray(outside.to_numpy(), dtype=np.bool_)


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


def _kept(column: ValueColumn | None, keep: BoolArray) -> FloatArray | None:
    """The values of an optional column in the kept rows, or ``None`` without the column."""
    return None if column is None else column.parsed[keep]


def _as_bool(mask: pd.Series) -> BoolArray:
    return np.asarray(mask.to_numpy(), dtype=np.bool_)
