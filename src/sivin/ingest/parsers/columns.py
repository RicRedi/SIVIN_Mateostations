"""Column headers of export files and the parser settings.

The provider's exports name their columns in Czech (``Datum a čas``, ``Teplota (°C)``,
``Vlhkost (%)``, ``Srážky (mm)``, ``Celkové srážky (mm)``, ``Nabití baterie (V)``); other tools
write German or English names, with or without a unit. A :class:`ColumnMapping` maps any
configured alias to the canonical column, ignoring case, diacritics and surrounding whitespace.
A unit in parentheses or brackets must be one of the accepted units of the column, so
``Teplota (°F)`` is never read as °C.

Timestamp, temperature and humidity are **required** (:data:`REQUIRED_CANONICAL_COLUMNS`);
precipitation, the cumulative precipitation counter and the battery voltage are **optional**
(:data:`OPTIONAL_CANONICAL_COLUMNS`, WP-1.9): a file without them is still valid, and a
problem with one of them (an unknown unit, two headers for it) only drops that column.

The formats are reconstructed from legacy code; the CSV header names were confirmed by one real
export (MIGRATION_PLAN §0.6.1), the other layouts are unverified, so every name is configurable.
"""

from __future__ import annotations

import codecs
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from sivin.core.defaults import DEFAULT_SAMPLING_INTERVAL_S, DEFAULT_TIMEZONE
from sivin.core.ids import SensorId


class CanonicalColumn(StrEnum):
    """The columns a parser reads from a table."""

    TIMESTAMP = "timestamp"
    TEMP = "temp_c"
    RH = "rh_pct"
    PRECIP = "precip_mm"
    PRECIP_TOTAL = "precip_total_mm"
    BATTERY = "battery_v"


REQUIRED_CANONICAL_COLUMNS: Final = (
    CanonicalColumn.TIMESTAMP,
    CanonicalColumn.TEMP,
    CanonicalColumn.RH,
)
"""Columns every table must have; a table without one of them is rejected."""

OPTIONAL_CANONICAL_COLUMNS: Final = (
    CanonicalColumn.PRECIP,
    CanonicalColumn.PRECIP_TOTAL,
    CanonicalColumn.BATTERY,
)
"""Columns read when present (owner decision Q9, 2026-10-05); older exports lack them."""


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
            "'Datum a čas' is the name used by the provider's exports (confirmed by the first "
            "real export, MIGRATION_PLAN §0.6.1)."
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
    precip_mm: tuple[str, ...] = Field(
        (
            "Srážky",
            "Srážka",
            "Srážky za interval",
            "Niederschlag",
            "Niederschlagsmenge",
            "Regen",
            "Precipitation",
            "Rain",
            "Rainfall",
        ),
        min_length=1,
        description=(
            "Header names of the optional column of precipitation in the interval since the "
            "previous sample (values in mm). 'Srážky (mm)' is the name used by the provider's "
            "exports (confirmed by the first real export, MIGRATION_PLAN §0.6.1)."
        ),
    )
    precip_total_mm: tuple[str, ...] = Field(
        (
            "Celkové srážky",
            "Srážky celkem",
            "Kumulativní srážky",
            "Niederschlag gesamt",
            "Gesamtniederschlag",
            "Kumulierter Niederschlag",
            "Total precipitation",
            "Cumulative precipitation",
            "Precipitation total",
            "Total rain",
            "Rain total",
        ),
        min_length=1,
        description=(
            "Header names of the optional column of the device's cumulative precipitation "
            "counter (values in mm). 'Celkové srážky (mm)' is the name used by the provider's "
            "exports (confirmed by the first real export)."
        ),
    )
    battery_v: tuple[str, ...] = Field(
        (
            "Nabití baterie",
            "Napětí baterie",
            "Baterie",
            "Batterie",
            "Batteriespannung",
            "Battery",
            "Battery voltage",
        ),
        min_length=1,
        description=(
            "Header names of the optional battery voltage column (values in V). "
            "'Nabití baterie (V)' is the name used by the provider's exports (confirmed by the "
            "first real export)."
        ),
    )
    precip_units: tuple[str, ...] = Field(
        ("mm",),
        description=(
            "Units accepted after a precipitation or cumulative precipitation header, "
            "e.g. 'Srážky (mm)'."
        ),
    )
    battery_units: tuple[str, ...] = Field(
        ("V",),
        description="Units accepted after a battery header, e.g. 'Nabití baterie (V)'.",
    )


class ParserSettings(BaseModel):
    """Settings of the export parsers (proposed configuration section ``ingest.parsers``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_timezone: str = Field(
        DEFAULT_TIMEZONE,
        description=(
            "IANA zone of the wall-clock timestamps in the exports. The portal exports local "
            "time (owner decision Q2, 2026-10-05)."
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
            "with a timestamp column. The portal CSV has one title row ('Meteo Data;') before "
            "the header (confirmed by a real export); the XLSX layout is unverified (Q11)."
        ),
    )
    day_first: StrictBool = Field(
        True,
        description=(
            "Read numeric dates with '.' or '/' day first (5.1.2026 = 5 January 2026), as in "
            "the legacy sampl_freq_basic.py. ISO dates (2026-01-05) are always year first."
        ),
    )
    newest_first_min_share: float = Field(
        0.75,
        gt=0.5,
        le=1.0,
        description=(
            "Share (0-1, dimensionless) of the counted steps between consecutive timestamps "
            "that must go back in time for a table to be read as newest first and reversed. "
            "Steps inside the repeated hour of a fall-back transition are not counted. The first "
            "real export is newest first (MIGRATION_PLAN §0.6.1); the share is a project "
            "default [to be verified]."
        ),
    )
    newest_first_min_steps: StrictInt = Field(
        4,
        ge=1,
        description=(
            "Minimum number of counted non-zero steps (count) needed to decide that a table is "
            "newest first. A shorter table that steps back is read oldest first and reported. "
            "Project default [to be verified]."
        ),
    )
    max_backward_step_s: float = Field(
        7200.0,
        ge=3600.0,
        description=(
            "Rows more than this many seconds earlier than the latest accepted row (clock "
            "reset; exact copies from overlapping exports are kept), or isolated rows "
            "this far ahead of their neighbours (glitched timestamp), are dropped and reported. "
            "At least 3600 s, the length of the repeated hour of a fall-back transition. "
            "Project default [to be verified]."
        ),
    )
    earliest_timestamp: datetime = Field(
        datetime(2020, 1, 1),
        description=(
            "Earliest plausible local timestamp; earlier rows (e.g. after a device clock reset) "
            "are dropped and reported. The project started in 2025; project default "
            "[to be tuned]."
        ),
    )
    latest_timestamp: datetime | None = Field(
        None,
        description=(
            "Latest plausible local timestamp. None: the run time plus 'max_future_s', in "
            "source_timezone. Set explicitly only for reproducible tests or re-imports."
        ),
    )
    max_future_s: float = Field(
        86400.0,
        ge=0.0,
        description=(
            "Seconds after the run time up to which a timestamp is still plausible (clock "
            "drift, time zone confusion). Project default [to be tuned]."
        ),
    )
    expected_interval_s: float = Field(
        DEFAULT_SAMPLING_INTERVAL_S,
        gt=0.0,
        description=(
            "Nominal sampling interval in seconds (1830 s, the median step of the first real "
            "export, MIGRATION_PLAN §0.6.1); used by the day/month swap guard."
        ),
    )
    long_step_factor: float = Field(
        48.0,
        gt=1.0,
        description=(
            "A step between consecutive timestamps longer than expected_interval_s times this "
            "factor (dimensionless; 48 x 1830 s = 24.4 h) counts as long for the day/month swap "
            "guard. Project default [to be verified]."
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

    @field_validator("earliest_timestamp", "latest_timestamp")
    @classmethod
    def _naive_local(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("must be a naive local time in source_timezone")
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
        0-based column position of every canonical column that was found (optional columns
        only when they were found without a problem).
    headers : Mapping
        The header text of every canonical column in ``positions``.
    missing : tuple of CanonicalColumn
        Required canonical columns without an accepted header.
    problems : tuple of str
        Rejected units and ambiguous headers of required columns.
    optional_problems : tuple of str
        Rejected units and ambiguous headers of optional columns; such a column is not read.
    """

    row_index: int
    positions: Mapping[CanonicalColumn, int]
    headers: Mapping[CanonicalColumn, str]
    missing: tuple[CanonicalColumn, ...]
    problems: tuple[str, ...]
    optional_problems: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        """``True`` if every required canonical column was found unambiguously."""
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
            (CanonicalColumn.PRECIP, aliases.precip_mm),
            (CanonicalColumn.PRECIP_TOTAL, aliases.precip_total_mm),
            (CanonicalColumn.BATTERY, aliases.battery_v),
        ):
            for name in names:
                self._names.setdefault(normalize_label(name), column)
        precip_units = frozenset(map(normalize_unit, aliases.precip_units))
        self._units: dict[CanonicalColumn, frozenset[str]] = {
            CanonicalColumn.TIMESTAMP: frozenset(map(normalize_unit, aliases.timestamp_units)),
            CanonicalColumn.TEMP: frozenset(map(normalize_unit, aliases.temp_units)),
            CanonicalColumn.RH: frozenset(map(normalize_unit, aliases.rh_units)),
            CanonicalColumn.PRECIP: precip_units,
            CanonicalColumn.PRECIP_TOTAL: precip_units,
            CanonicalColumn.BATTERY: frozenset(map(normalize_unit, aliases.battery_units)),
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
        problems: dict[CanonicalColumn, list[str]] = {column: [] for column in CanonicalColumn}
        for position, cell in enumerate(cells):
            if cell.column is None:
                continue
            if not cell.accepted:
                problems[cell.column].append(
                    f"Column '{cell.text}': unit '{cell.unit}' is not accepted for {cell.column}."
                )
            elif cell.column in positions:
                problems[cell.column].append(
                    f"Columns '{headers[cell.column]}' and '{cell.text}' both denote {cell.column}."
                )
            else:
                positions[cell.column] = position
                headers[cell.column] = cell.text
        for column in OPTIONAL_CANONICAL_COLUMNS:
            if problems[column]:
                positions.pop(column, None)
                headers.pop(column, None)
        missing = tuple(column for column in REQUIRED_CANONICAL_COLUMNS if column not in positions)
        return HeaderMatch(
            row_index=row_index,
            positions=MappingProxyType(positions),
            headers=MappingProxyType(headers),
            missing=missing,
            problems=tuple(p for column in REQUIRED_CANONICAL_COLUMNS for p in problems[column]),
            optional_problems=tuple(
                p for column in OPTIONAL_CANONICAL_COLUMNS for p in problems[column]
            ),
        )
