"""Column headers of export files and the parser settings.

The provider's exports name their columns in Czech (``Datum a čas``, ``Teplota (°C)``,
``Vlhkost (%)``); other tools write German or English names, with or without a unit. A
:class:`ColumnMapping` maps any configured alias to the canonical column, ignoring case,
diacritics and surrounding whitespace. A unit in parentheses or brackets must be one of the
accepted units of the column, so ``Teplota (°F)`` is never read as °C.

The formats are reconstructed from legacy code and not verified on a real export (owner
questions Q1, Q2); every name is therefore configurable.
"""

from __future__ import annotations

import codecs
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from sivin.core.defaults import DEFAULT_TIMEZONE
from sivin.core.ids import SensorId


class CanonicalColumn(StrEnum):
    """The columns a parser needs from every table."""

    TIMESTAMP = "timestamp"
    TEMP = "temp_c"
    RH = "rh_pct"


_HEADER_WITH_UNIT: Final = re.compile(r"^(?P<name>.*?)\s*[(\[](?P<unit>[^)\]]*)[)\]]$")
"""A header followed by a unit in parentheses or brackets, e.g. ``Teplota (°C)``."""


def normalize_label(text: str) -> str:
    """Normalise a header or alias for comparison.

    Parameters
    ----------
    text : str
        A column header or alias.

    Returns
    -------
    str
        Lower case (``casefold``), without diacritics, with single spaces and no surrounding
        whitespace: ``"  Datum a  ČAS "`` becomes ``"datum a cas"``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(stripped.casefold().split())


def normalize_unit(text: str) -> str:
    """Normalise a unit for comparison: like :func:`normalize_label`, without any whitespace.

    Parameters
    ----------
    text : str
        A unit, e.g. ``"° C"`` or ``"℃"``.

    Returns
    -------
    str
        E.g. ``"°c"`` for all three spellings ``°C``, ``° C`` and ``℃``.
    """
    return normalize_label(text).replace(" ", "")


class ColumnAliases(BaseModel):
    """Accepted header names and units per canonical column (proposed ``ingest.parsers.aliases``).

    Names are compared after :func:`normalize_label`, units after :func:`normalize_unit`, so
    case, diacritics and extra whitespace do not matter.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: tuple[str, ...] = Field(
        (
            "Datum a čas",
            "Datum",
            "Čas",
            "Datum und Uhrzeit",
            "Datum/Uhrzeit",
            "Zeitstempel",
            "Zeit",
            "Date and time",
            "Date",
            "Time",
            "Datetime",
            "Timestamp",
        ),
        min_length=1,
        description=(
            "Header names of the local timestamp column (Czech, German, English). "
            "'Datum a čas' is the name used by the provider's exports according to the legacy "
            "scripts [to be verified on a real export, Q1]."
        ),
    )
    temp_c: tuple[str, ...] = Field(
        (
            "Teplota",
            "Teplota vzduchu",
            "Temperatur",
            "Lufttemperatur",
            "Temperature",
            "Air temperature",
            "Temp",
        ),
        min_length=1,
        description="Header names of the air temperature column (values in °C).",
    )
    rh_pct: tuple[str, ...] = Field(
        (
            "Vlhkost",
            "Relativní vlhkost",
            "Vlhkost vzduchu",
            "Luftfeuchtigkeit",
            "Relative Luftfeuchtigkeit",
            "Luftfeuchte",
            "Feuchtigkeit",
            "Humidity",
            "Relative humidity",
            "RH",
        ),
        min_length=1,
        description="Header names of the relative humidity column (values in %).",
    )
    temp_units: tuple[str, ...] = Field(
        ("°C", "C", "degC", "deg C", "℃"),
        description="Units accepted after a temperature header, e.g. 'Teplota (°C)'.",
    )
    rh_units: tuple[str, ...] = Field(
        ("%", "% RH", "%RH", "% rel.", "pct"),
        description="Units accepted after a relative humidity header, e.g. 'Vlhkost (%)'.",
    )
    timestamp_units: tuple[str, ...] = Field(
        (),
        description=(
            "Qualifiers accepted after a timestamp header. Empty by default, so that a header "
            "such as 'Datum a čas (UTC)' is rejected instead of being read in source_timezone."
        ),
    )


class ParserSettings(BaseModel):
    """Settings of the export parsers (proposed configuration section ``ingest.parsers``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_timezone: str = Field(
        DEFAULT_TIMEZONE,
        description=(
            "IANA zone of the wall-clock timestamps in the exports. Not yet confirmed by a "
            "real export (owner question Q2)."
        ),
    )
    aliases: ColumnAliases = Field(
        default_factory=ColumnAliases, description="Accepted column names and units."
    )
    header_search_rows: StrictInt = Field(
        10,
        ge=1,
        description=(
            "Number of leading rows (count) searched for the header row, i.e. the first row "
            "with a timestamp column. The legacy CSV has one title row ('Meteo Data;') before "
            "the header; the XLSX layout is unverified (Q1)."
        ),
    )
    day_first: StrictBool = Field(
        True,
        description=(
            "Read numeric dates with '.' or '/' day first (5.1.2026 = 5 January 2026), as in "
            "the legacy sampl_freq_basic.py. ISO dates (2026-01-05) are always year first."
        ),
    )
    csv_delimiter: str = Field(
        ";", min_length=1, max_length=1, description="Field delimiter of CSV exports."
    )
    csv_encodings: tuple[str, ...] = Field(
        ("utf-8-sig", "cp1250"),
        min_length=1,
        description=(
            "Text encodings tried in order for CSV exports: UTF-8 (with or without BOM, used "
            "by the legacy reader), then Windows-1250 (Czech Windows) [to be verified]."
        ),
    )
    legacy_sheet_sensors: Mapping[str, str] = Field(
        default_factory=dict,
        description=(
            "Legacy workbook (data.xlsx): worksheet name -> 8-digit sensor serial, e.g. "
            "{'8271': '77678271'}. The 4-digit sheet names are ambiguous, so the caller "
            "resolves them (normally through the sensor registry). Empty: no legacy import."
        ),
    )

    @field_validator("source_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA time zone {value!r}") from error
        return value

    @field_validator("csv_encodings")
    @classmethod
    def _known_encodings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for encoding in value:
            try:
                codecs.lookup(encoding)
            except LookupError as error:
                raise ValueError(f"unknown text encoding {encoding!r}") from error
        return value

    @field_validator("legacy_sheet_sensors")
    @classmethod
    def _valid_serials(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        serials = list(value.values())
        for serial in serials:
            SensorId(serial)
        if len(set(serials)) != len(serials):
            raise ValueError("every sensor serial may be mapped from one worksheet only")
        return MappingProxyType(dict(value))

    @property
    def legacy_sheet_ids(self) -> dict[str, SensorId]:
        """The legacy worksheet mapping with :class:`SensorId` values."""
        return {sheet: SensorId(serial) for sheet, serial in self.legacy_sheet_sensors.items()}


@dataclass(frozen=True, slots=True)
class HeaderCell:
    """How one header cell was understood.

    Attributes
    ----------
    text : str
        The header as written in the file.
    column : CanonicalColumn or None
        The canonical column its name denotes, if any.
    unit : str or None
        The unit or qualifier in parentheses or brackets, if any.
    accepted : bool
        ``False`` if the name matched but the unit is not accepted for the column.
    """

    text: str
    column: CanonicalColumn | None
    unit: str | None = None
    accepted: bool = True


@dataclass(frozen=True)
class HeaderMatch:
    """The columns found in one header row.

    Attributes
    ----------
    row_index : int
        0-based index of the header row in the table.
    positions : Mapping
        0-based column position of every canonical column that was found.
    headers : Mapping
        The header text of every canonical column that was found.
    missing : tuple of CanonicalColumn
        Canonical columns without an accepted header.
    problems : tuple of str
        Rejected units and ambiguous headers.
    """

    row_index: int
    positions: Mapping[CanonicalColumn, int]
    headers: Mapping[CanonicalColumn, str]
    missing: tuple[CanonicalColumn, ...]
    problems: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        """``True`` if every canonical column was found unambiguously."""
        return not self.missing and not self.problems


class ColumnMapping:
    """Map source headers to canonical columns.

    Parameters
    ----------
    aliases : ColumnAliases
        Accepted names and units per column.
    """

    __slots__ = ("_names", "_units")

    def __init__(self, aliases: ColumnAliases) -> None:
        self._names: dict[str, CanonicalColumn] = {}
        for column, names in (
            (CanonicalColumn.TIMESTAMP, aliases.timestamp),
            (CanonicalColumn.TEMP, aliases.temp_c),
            (CanonicalColumn.RH, aliases.rh_pct),
        ):
            for name in names:
                self._names.setdefault(normalize_label(name), column)
        self._units: dict[CanonicalColumn, frozenset[str]] = {
            CanonicalColumn.TIMESTAMP: frozenset(map(normalize_unit, aliases.timestamp_units)),
            CanonicalColumn.TEMP: frozenset(map(normalize_unit, aliases.temp_units)),
            CanonicalColumn.RH: frozenset(map(normalize_unit, aliases.rh_units)),
        }

    def classify(self, cell: object) -> HeaderCell:
        """Tell which canonical column a header cell denotes.

        Parameters
        ----------
        cell : object
            A cell of a candidate header row (any type; only strings can be headers).

        Returns
        -------
        HeaderCell
            The interpretation; ``column`` is ``None`` for unknown headers.
        """
        if not isinstance(cell, str):
            return HeaderCell(text="" if cell is None else str(cell), column=None)
        text = cell.strip()
        column = self._names.get(normalize_label(text))
        if column is not None:
            return HeaderCell(text, column)
        match = _HEADER_WITH_UNIT.match(text)
        if match is None:
            return HeaderCell(text, None)
        column = self._names.get(normalize_label(match["name"]))
        if column is None:
            return HeaderCell(text, None)
        unit = match["unit"].strip()
        return HeaderCell(text, column, unit, normalize_unit(unit) in self._units[column])

    def locate_header(
        self, rows: Sequence[Sequence[object]], search_rows: int
    ) -> HeaderMatch | None:
        """Find the header row: the first row with a timestamp column name.

        Parameters
        ----------
        rows : sequence of sequence of object
            The cells of a table, row by row.
        search_rows : int
            Number of leading rows to search.

        Returns
        -------
        HeaderMatch or None
            The header, or ``None`` if none of the searched rows names a timestamp column.
        """
        for row_index, row in enumerate(rows[:search_rows]):
            cells = [self.classify(cell) for cell in row]
            if any(cell.column is CanonicalColumn.TIMESTAMP for cell in cells):
                return self._match(row_index, cells)
        return None

    @staticmethod
    def _match(row_index: int, cells: Sequence[HeaderCell]) -> HeaderMatch:
        positions: dict[CanonicalColumn, int] = {}
        headers: dict[CanonicalColumn, str] = {}
        problems: list[str] = []
        for position, cell in enumerate(cells):
            if cell.column is None:
                continue
            if not cell.accepted:
                problems.append(
                    f"Column '{cell.text}': unit '{cell.unit}' is not accepted for {cell.column}."
                )
            elif cell.column in positions:
                problems.append(
                    f"Columns '{headers[cell.column]}' and '{cell.text}' both denote {cell.column}."
                )
            else:
                positions[cell.column] = position
                headers[cell.column] = cell.text
        missing = tuple(column for column in CanonicalColumn if column not in positions)
        return HeaderMatch(
            row_index=row_index,
            positions=MappingProxyType(positions),
            headers=MappingProxyType(headers),
            missing=missing,
            problems=tuple(problems),
        )
