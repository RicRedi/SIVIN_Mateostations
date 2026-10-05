"""Input validation of export files (MIGRATION_PLAN §2.7).

Every export file is inspected before anything is imported: an export parser reads the file
into an :class:`ExportInspection` (what was found: file size, tables, header, parsed columns,
converted timestamps) and :class:`InputValidator` runs every registered
:class:`ValidationRule` over it. The result is a :class:`ValidationReport`; a report with at
least one :attr:`Severity.ERROR` means the file must not be imported (it is quarantined), a
:attr:`Severity.WARNING` is recorded but the data are usable.

A new check is a new :class:`ValidationRule` subclass registered with
``@validation_rules.register``; the validator never needs to change.

The gross physical bounds checked here only guard against unit and column mix-ups (relative
humidity as a 0-1 fraction, temperature in °F or K). The fine-grained range checks belong to
quality control (WP-1.5).

The optional auxiliary columns (precipitation, cumulative precipitation, battery voltage;
WP-1.9) never reject a file: whole-row validity concerns temperature and humidity only (owner
decision Q9, 2026-10-05), so a problem with an auxiliary column is a WARNING and its affected
values are read as missing (unparseable cells and values outside the gross bounds alike).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Final, Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from sivin.core.ids import SensorId

logger = logging.getLogger(__name__)

BoolArray = npt.NDArray[np.bool_]
FloatArray = npt.NDArray[np.float64]
RowArray = npt.NDArray[np.int64]


class Severity(StrEnum):
    """Severity of a validation finding."""

    ERROR = "error"
    """The file must not be imported."""

    WARNING = "warning"
    """The file is usable; the finding is recorded (and affected values may be flagged)."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One finding of a validation rule.

    Attributes
    ----------
    rule : str
        Identifier of the rule (:attr:`ValidationRule.rule_id`), e.g. ``"required-columns"``.
    severity : Severity
        ``ERROR`` rejects the file, ``WARNING`` is informative.
    message : str
        Human-readable description, in English.
    row : int or None
        1-based row number in the source file (CSV line or spreadsheet row) of the first
        affected row, if the finding concerns rows.
    table : str or None
        Name of the table the finding concerns (worksheet name, or the file name for single-
        table formats); ``None`` for findings about the whole file.
    """

    rule: str
    severity: Severity
    message: str
    row: int | None = None
    table: str | None = None

    def __str__(self) -> str:
        where = "".join(
            (
                f" [{self.table}]" if self.table is not None else "",
                f" row {self.row}" if self.row is not None else "",
            )
        )
        return f"{self.severity.upper()} {self.rule}{where}: {self.message}"


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """All findings of the validation of one export file.

    Attributes
    ----------
    issues : tuple of ValidationIssue
        Findings in the order the rules produced them.
    """

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def is_acceptable(self) -> bool:
        """``True`` if no finding is an :attr:`Severity.ERROR`."""
        return not self.errors

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        """The findings with severity ``ERROR``."""
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        """The findings with severity ``WARNING``."""
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)

    def rules(self, severity: Severity | None = None) -> frozenset[str]:
        """Return the ids of the rules that produced findings.

        Parameters
        ----------
        severity : Severity, optional
            Only findings of this severity; all findings when omitted.

        Returns
        -------
        frozenset of str
            Rule identifiers.
        """
        return frozenset(
            issue.rule for issue in self.issues if severity is None or issue.severity is severity
        )

    def summary(self) -> str:
        """Return one line per finding, or ``"no findings"``.

        Returns
        -------
        str
            Text for logs and the run summary.
        """
        return "\n".join(str(issue) for issue in self.issues) or "no findings"


class ValidationSettings(BaseModel):
    """Thresholds of the input validation (proposed configuration section ``ingest.validation``).

    The defaults are project defaults, not taken from literature. The first real export
    (MIGRATION_PLAN §0.6.1) passes them without findings; they are to be tuned once exports of
    more sensors are available (owner question Q11).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_data_rows: StrictInt = Field(
        1,
        ge=1,
        description=(
            "Minimum number of data rows (count) below the header of every table; fewer means "
            "an empty or truncated export (ERROR)."
        ),
    )
    max_unparseable_value_share: float = Field(
        0.05,
        ge=0.0,
        le=1.0,
        description=(
            "Share of data rows (0-1, dimensionless) whose temperature or humidity cell is not "
            "empty but is not a number. Above it the file is rejected (ERROR); at or below it "
            "the values become missing (WARNING). Project default [to be verified]."
        ),
    )
    max_unparseable_timestamp_share: float = Field(
        0.05,
        ge=0.0,
        le=1.0,
        description=(
            "Share of data rows (0-1, dimensionless) without a readable timestamp. Above it the "
            "file is rejected (ERROR); at or below it the rows are dropped (WARNING). Project "
            "default [to be verified]."
        ),
    )
    temp_min_c: float = Field(
        -60.0,
        description=(
            "Gross lower bound of air temperature in °C; only guards against unit or column "
            "mix-ups, the climatological range check is quality control (WP-1.5). Project "
            "default, deliberately generous [to be verified]."
        ),
    )
    temp_max_c: float = Field(
        70.0,
        description=(
            "Gross upper bound of air temperature in °C (catches °F and K exports). Project "
            "default, deliberately generous [to be verified]."
        ),
    )
    rh_min_pct: float = Field(
        0.0, description="Lower bound of relative humidity in % (physical limit)."
    )
    rh_max_pct: float = Field(
        100.0, description="Upper bound of relative humidity in % (physical limit)."
    )
    max_implausible_timestamp_share: float = Field(
        0.05,
        ge=0.0,
        le=1.0,
        description=(
            "Share of data rows (0-1, dimensionless) with a timestamp outside the plausible "
            "range (ParserSettings.earliest_timestamp to the run time plus max_future_s), and "
            "also of rows out of sequence (rule out-of-sequence). Above it the file is rejected "
            "(ERROR); at or below it the rows are dropped (WARNING). Project default "
            "[to be verified]."
        ),
    )
    min_error_rows: StrictInt = Field(
        3,
        ge=0,
        description=(
            "A share threshold turns a finding into an ERROR only when more than this many rows "
            "(count) are affected, or all of them; so one footer or comment row in a short file "
            "is a WARNING. Project default [to be verified]."
        ),
    )
    max_out_of_bounds_share: float = Field(
        0.05,
        ge=0.0,
        le=1.0,
        description=(
            "Share of the present values of a variable (0-1, dimensionless) outside the gross "
            "bounds above which the file is rejected (ERROR); at or below it each such value is "
            "reported (WARNING) and left to quality control. Also the share of humidity values "
            "at or below 'rh_fraction_max_pct' that marks humidity given as a 0-1 fraction. "
            "Project default [to be verified]."
        ),
    )
    rh_fraction_max_pct: float = Field(
        1.0,
        ge=0.0,
        description=(
            "Relative humidity in % at or below which a value looks like a 0-1 fraction "
            "instead of a percentage (unit mix-up). Project default [to be verified]."
        ),
    )
    precip_min_mm: float = Field(
        0.0,
        description=(
            "Lower bound of the precipitation of one sample interval in mm (physical limit: "
            "an amount of precipitation cannot be negative). Values below it are reported "
            "(WARNING) and read as missing."
        ),
    )
    precip_max_mm: float = Field(
        500.0,
        description=(
            "Gross upper bound of the precipitation of one sample interval in mm; only guards "
            "against unit mix-ups and garbage, the plausibility check per interval is quality "
            "control (check 'precip_range'). Project default, deliberately generous "
            "[to be verified]."
        ),
    )
    precip_total_min_mm: float = Field(
        0.0,
        description=(
            "Lower bound of the cumulative precipitation counter in mm (a sum of "
            "non-negative amounts cannot be negative)."
        ),
    )
    precip_total_max_mm: float = Field(
        100_000.0,
        description=(
            "Gross upper bound of the cumulative precipitation counter in mm; only catches "
            "garbage and unit mix-ups (the first real export reads 323.0-326.4 mm). Project "
            "default, deliberately generous [to be verified]."
        ),
    )
    battery_min_v: float = Field(
        0.0,
        description="Gross lower bound of the battery voltage in V (a voltage reading below 0 V).",
    )
    battery_max_v: float = Field(
        10.0,
        description=(
            "Gross upper bound of the battery voltage in V; catches millivolts and column "
            "mix-ups (the first real export reads 3.0-3.7 V). Project default [to be verified "
            "against the device data sheet]."
        ),
    )

    @property
    def precip_bounds_mm(self) -> tuple[float, float]:
        """Inclusive gross bounds of the precipitation per interval in mm."""
        return self.precip_min_mm, self.precip_max_mm

    @property
    def precip_total_bounds_mm(self) -> tuple[float, float]:
        """Inclusive gross bounds of the cumulative precipitation counter in mm."""
        return self.precip_total_min_mm, self.precip_total_max_mm

    @property
    def battery_bounds_v(self) -> tuple[float, float]:
        """Inclusive gross bounds of the battery voltage in V."""
        return self.battery_min_v, self.battery_max_v

    @model_validator(mode="after")
    def _ordered_bounds(self) -> Self:
        for name, lower, upper in (
            ("temp", self.temp_min_c, self.temp_max_c),
            ("rh", self.rh_min_pct, self.rh_max_pct),
            ("precip", self.precip_min_mm, self.precip_max_mm),
            ("precip_total", self.precip_total_min_mm, self.precip_total_max_mm),
            ("battery", self.battery_min_v, self.battery_max_v),
        ):
            if lower >= upper:
                raise ValueError(f"the lower {name} bound must be lower than the upper one")
        return self


@dataclass(frozen=True, eq=False)
class ValueColumn:
    """A measured variable as read from one table, one entry per data row.

    Attributes
    ----------
    header : str
        The source column header, e.g. ``"Teplota (°C)"``.
    parsed : numpy.ndarray of float64
        Parsed values in the canonical unit (°C or %); ``NaN`` where the cell was empty or
        unparseable.
    unparseable : numpy.ndarray of bool
        ``True`` where the cell was not empty but could not be read as a number.
    """

    header: str
    parsed: FloatArray
    unparseable: BoolArray

    @property
    def present(self) -> FloatArray:
        """The values that are not ``NaN``."""
        return self.parsed[~np.isnan(self.parsed)]


@dataclass(frozen=True, eq=False)
class TimeColumn:
    """Timestamps of one table, one entry per data row.

    Attributes
    ----------
    header : str
        The source column header, e.g. ``"Datum a čas"``.
    local : pandas.Series
        Naive local wall-clock timestamps (``datetime64[ns]``); ``NaT`` where unparseable.
    utc : pandas.Series
        Timestamps converted to UTC (``datetime64[ns, UTC]``); ``NaT`` where unparseable,
        implausible, out of sequence or where the daylight-saving conversion collided with
        another row.
    suspect : numpy.ndarray of bool
        Ambiguous or nonexistent local time (daylight-saving transition).
    unresolved : numpy.ndarray of bool
        Subset of ``suspect`` whose UTC instant is a guess or ``NaT``, including ambiguous rows
        of a repaired table whose transition is not fully covered; these rows are dropped.
    implausible : numpy.ndarray of bool
        Readable local time outside the plausible range; not converted, dropped.
    out_of_sequence : numpy.ndarray of bool
        Far earlier than the rows before it, or an isolated row far ahead of its neighbours;
        not converted, dropped.
    """

    header: str
    local: pd.Series
    utc: pd.Series
    suspect: BoolArray
    unresolved: BoolArray
    implausible: BoolArray
    out_of_sequence: BoolArray

    @property
    def unparseable(self) -> BoolArray:
        """``True`` where no local timestamp could be read."""
        return np.asarray(self.local.isna().to_numpy(), dtype=np.bool_)


def _no_rows() -> RowArray:
    return np.empty(0, dtype=np.int64)


@dataclass(frozen=True, eq=False)
class TableInspection:
    """What a parser found in one table (a CSV file or one worksheet).

    Attributes
    ----------
    name : str
        Table name: the worksheet name, or the file name for single-table formats.
    sensor_id : SensorId or None
        The sensor the table belongs to; ``None`` if it could not be resolved.
    sensor_problem : str or None
        Why the sensor could not be resolved.
    header_search_rows : int
        How many leading rows were searched for the header (for messages).
    header_row : int or None
        1-based row number of the header; ``None`` if no header was found.
    missing_columns : tuple of str
        Required canonical columns (``timestamp``, ``temp_c``, ``rh_pct``) without a matching
        header.
    column_problems : tuple of str
        Descriptions of headers of required columns that were rejected (e.g. an unexpected
        unit) or ambiguous.
    optional_column_problems : tuple of str
        The same for the optional columns (precipitation, counter, battery); such a column is
        not read.
    source_rows : numpy.ndarray of int64
        1-based source row number of every data row (non-blank rows below the header), in
        the order of the columns below.
    short_rows : numpy.ndarray of int64
        Source row numbers of data rows that end before a mapped column (cut-off lines).
    reversed_order : bool
        ``True`` if the rows were recorded newest first and were reversed by the parser.
    backward_rows : numpy.ndarray of int64
        Source row numbers of the rows that are earlier than the row before them (steps
        inside the repeated hour of a fall-back excluded), after a possible reversal.
    order_undecided : bool
        ``True`` if the table steps back in time but is too short to decide whether it is
        newest first; it was read oldest first.
    date_order_problem : str or None
        Why the day/month order of the timestamps looks swapped, if it does.
    times, temp, rh : TimeColumn, ValueColumn or None
        Parsed columns; ``None`` when the header or a required column is missing.
    precip, precip_total, battery : ValueColumn or None
        Parsed optional columns (precipitation since the previous sample in mm, cumulative
        precipitation counter in mm, battery voltage in V); ``None`` when the table does not
        have the column or a required column is missing.
    """

    name: str
    sensor_id: SensorId | None
    sensor_problem: str | None = None
    header_search_rows: int = 0
    header_row: int | None = None
    missing_columns: tuple[str, ...] = ()
    column_problems: tuple[str, ...] = ()
    optional_column_problems: tuple[str, ...] = ()
    source_rows: RowArray = field(default_factory=_no_rows)
    short_rows: RowArray = field(default_factory=_no_rows)
    reversed_order: bool = False
    backward_rows: RowArray = field(default_factory=_no_rows)
    order_undecided: bool = False
    date_order_problem: str | None = None
    times: TimeColumn | None = None
    temp: ValueColumn | None = None
    rh: ValueColumn | None = None
    precip: ValueColumn | None = None
    precip_total: ValueColumn | None = None
    battery: ValueColumn | None = None

    @property
    def n_data_rows(self) -> int:
        """Number of data rows below the header."""
        return len(self.source_rows)

    @property
    def auxiliary_columns(self) -> tuple[ValueColumn, ...]:
        """The optional columns that were read (precipitation, counter, battery), in order."""
        columns = (self.precip, self.precip_total, self.battery)
        return tuple(column for column in columns if column is not None)

    def first_row(self, mask: npt.ArrayLike) -> int | None:
        """Return the source row number of the first data row selected by ``mask``.

        Parameters
        ----------
        mask : array_like of bool
            One entry per data row.

        Returns
        -------
        int or None
            1-based source row number, or ``None`` if ``mask`` selects nothing.
        """
        positions = np.flatnonzero(np.asarray(mask, dtype=np.bool_))
        return int(self.source_rows[positions[0]]) if len(positions) else None


@dataclass(frozen=True, eq=False)
class ExportInspection:
    """What a parser found in one export file; the input of :class:`InputValidator`.

    Attributes
    ----------
    source : pathlib.Path
        The export file.
    size_bytes : int or None
        File size in bytes; ``None`` if the path is not an existing file.
    read_problem : str or None
        Why the file could not be read (corrupt or truncated workbook, undecodable text).
    tables : tuple of TableInspection
        The tables that were read (one per sensor).
    missing_tables : tuple of str
        Tables the parser expected but did not find (e.g. mapped worksheets).
    ignored_tables : tuple of str
        Tables that were present but not read (e.g. worksheets without a sensor mapping).
    """

    source: Path
    size_bytes: int | None
    read_problem: str | None = None
    tables: tuple[TableInspection, ...] = ()
    missing_tables: tuple[str, ...] = ()
    ignored_tables: tuple[str, ...] = ()

    @property
    def is_readable(self) -> bool:
        """``True`` if the file exists, is not empty and could be read."""
        return bool(self.size_bytes) and self.read_problem is None


class ValidationRule(ABC):
    """One input check; subclasses register with :data:`validation_rules`.

    Parameters
    ----------
    settings : ValidationSettings
        Thresholds shared by all rules.
    """

    rule_id: ClassVar[str]

    def __init__(self, settings: ValidationSettings) -> None:
        self._settings = settings

    @property
    def settings(self) -> ValidationSettings:
        """The thresholds of this rule."""
        return self._settings

    @abstractmethod
    def check(self, inspection: ExportInspection) -> Iterator[ValidationIssue]:
        """Yield the findings of this rule for one export file.

        Parameters
        ----------
        inspection : ExportInspection
            What the parser found.

        Yields
        ------
        ValidationIssue
            Findings; none if the file passes.
        """

    def _issue(
        self,
        severity: Severity,
        message: str,
        row: int | None = None,
        table: str | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(self.rule_id, severity, message, row, table)


class TableRule(ValidationRule):
    """A rule checked on every readable table of a file separately."""

    def check(self, inspection: ExportInspection) -> Iterator[ValidationIssue]:
        """Yield the findings of :meth:`check_table` for every table of a readable file.

        Parameters
        ----------
        inspection : ExportInspection
            What the parser found.

        Yields
        ------
        ValidationIssue
            Findings of all tables, in table order.
        """
        if not inspection.is_readable:
            return
        for table in inspection.tables:
            yield from self.check_table(table)

    @abstractmethod
    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield the findings of this rule for one table.

        Parameters
        ----------
        table : TableInspection
            What the parser found in the table.

        Yields
        ------
        ValidationIssue
            Findings; none if the table passes.
        """


type RuleClass = type[ValidationRule]
"""A concrete :class:`ValidationRule` subclass."""


class ValidationRuleRegistry:
    """Registry of validation rule classes, in registration order.

    Registries are the one kind of module-level mutable state the project allows
    (MIGRATION_PLAN §1.2): they are filled by class decorators at import and never changed
    afterwards.
    """

    __slots__ = ("_classes",)

    def __init__(self) -> None:
        self._classes: dict[str, RuleClass] = {}

    def register[C: RuleClass](self, cls: C) -> C:
        """Register a rule class; use as a class decorator.

        Parameters
        ----------
        cls : type[ValidationRule]
            A concrete rule with a unique ``rule_id``.

        Returns
        -------
        type[ValidationRule]
            The class unchanged.

        Raises
        ------
        TypeError
            If ``cls`` is not a concrete rule with a non-empty ``rule_id``.
        ValueError
            If the ``rule_id`` is already registered.
        """
        if not (isinstance(cls, type) and issubclass(cls, ValidationRule)):
            raise TypeError(f"Only ValidationRule subclasses can be registered, got {cls!r}.")
        if getattr(cls, "__abstractmethods__", None):
            raise TypeError(f"{cls.__name__} is abstract and cannot be registered.")
        rule_id = getattr(cls, "rule_id", None)
        if not isinstance(rule_id, str) or not rule_id:
            raise TypeError(f"{cls.__name__} must define a non-empty class variable 'rule_id'.")
        if rule_id in self._classes:
            raise ValueError(f"Validation rule {rule_id!r} is already registered.")
        self._classes[rule_id] = cls
        return cls

    def classes(self) -> tuple[RuleClass, ...]:
        """Return the registered rule classes in registration order.

        Returns
        -------
        tuple of type[ValidationRule]
            The rule classes.
        """
        return tuple(self._classes.values())

    def ids(self) -> tuple[str, ...]:
        """Return the registered rule ids in registration order.

        Returns
        -------
        tuple of str
            The rule identifiers.
        """
        return tuple(self._classes)

    def __len__(self) -> int:
        return len(self._classes)


validation_rules: Final = ValidationRuleRegistry()
"""The project-wide registry of input validation rules."""


class InputValidator:
    """Run validation rules over an :class:`ExportInspection`.

    Parameters
    ----------
    settings : ValidationSettings, optional
        Thresholds; defaults when omitted.
    rules : sequence of ValidationRule, optional
        The rules to run; one instance of every class registered in
        :data:`validation_rules` (built with ``settings``) when omitted.
    """

    __slots__ = ("_rules", "_settings")

    def __init__(
        self,
        settings: ValidationSettings | None = None,
        rules: Sequence[ValidationRule] | None = None,
    ) -> None:
        self._settings = settings or ValidationSettings()
        if rules is None:
            rules = [cls(self._settings) for cls in validation_rules.classes()]
        self._rules = tuple(rules)

    @property
    def settings(self) -> ValidationSettings:
        """The thresholds used to build the default rules."""
        return self._settings

    @property
    def rule_ids(self) -> tuple[str, ...]:
        """Identifiers of the rules this validator runs, in order."""
        return tuple(rule.rule_id for rule in self._rules)

    def validate(self, inspection: ExportInspection) -> ValidationReport:
        """Check one export file.

        Parameters
        ----------
        inspection : ExportInspection
            What the parser found in the file.

        Returns
        -------
        ValidationReport
            All findings; :attr:`ValidationReport.is_acceptable` tells whether the file may be
            imported.
        """
        issues = [issue for rule in self._rules for issue in rule.check(inspection)]
        report = ValidationReport(tuple(issues))
        for issue in report.issues:
            log = logger.warning if issue.severity is Severity.ERROR else logger.info
            log("%s: %s", inspection.source.name, issue)
        return report


def outside_bounds(values: FloatArray, bounds: tuple[float, float]) -> BoolArray:
    """Tell which values lie outside inclusive bounds.

    Parameters
    ----------
    values : numpy.ndarray of float
        Values in the unit of the bounds; ``NaN`` is never outside.
    bounds : tuple of float
        ``(lower, upper)``, inclusive.

    Returns
    -------
    numpy.ndarray of bool
        ``True`` where a value is below ``lower`` or above ``upper``.
    """
    lower, upper = bounds
    with np.errstate(invalid="ignore"):
        return np.asarray((values < lower) | (values > upper), dtype=np.bool_)


def _share(count: int, total: int) -> float:
    return count / total if total else 0.0


def _share_severity(count: int, total: int, limit: float, settings: ValidationSettings) -> Severity:
    """ERROR if more than ``limit`` of ``total`` and more than ``min_error_rows`` (or all)."""
    if total and count == total:
        return Severity.ERROR
    if _share(count, total) > limit and count > settings.min_error_rows:
        return Severity.ERROR
    return Severity.WARNING


@validation_rules.register
class FileExistsRule(ValidationRule):
    """The export path must be an existing file (ERROR)."""

    rule_id = "file-exists"

    def check(self, inspection: ExportInspection) -> Iterator[ValidationIssue]:
        """Yield an ERROR if the file does not exist (see :meth:`ValidationRule.check`)."""
        if inspection.size_bytes is None:
            yield self._issue(Severity.ERROR, f"{inspection.source} is not an existing file.")


@validation_rules.register
class FileNotEmptyRule(ValidationRule):
    """The export file must not be empty (ERROR)."""

    rule_id = "file-not-empty"

    def check(self, inspection: ExportInspection) -> Iterator[ValidationIssue]:
        """Yield an ERROR for a zero-byte file (see :meth:`ValidationRule.check`)."""
        if inspection.size_bytes == 0:
            yield self._issue(Severity.ERROR, "The file is empty (0 bytes).")


@validation_rules.register
class FileReadableRule(ValidationRule):
    """The file must open: a truncated or corrupt workbook or undecodable text is an ERROR."""

    rule_id = "file-readable"

    def check(self, inspection: ExportInspection) -> Iterator[ValidationIssue]:
        """Yield an ERROR if the file could not be read (see :meth:`ValidationRule.check`)."""
        if inspection.size_bytes and inspection.read_problem is not None:
            yield self._issue(
                Severity.ERROR,
                f"The file cannot be read (truncated or corrupt?): {inspection.read_problem}",
            )


@validation_rules.register
class ExpectedTablesRule(ValidationRule):
    """Every expected table must be present (ERROR); unread tables are reported (WARNING)."""

    rule_id = "expected-tables"

    def check(self, inspection: ExportInspection) -> Iterator[ValidationIssue]:
        """Yield findings about missing and ignored tables (see :meth:`ValidationRule.check`)."""
        if not inspection.is_readable:
            return
        if inspection.missing_tables:
            yield self._issue(
                Severity.ERROR,
                f"Expected table(s) not found: {', '.join(inspection.missing_tables)}.",
            )
        elif not inspection.tables:
            yield self._issue(Severity.ERROR, "The file contains no table to read.")
        if inspection.ignored_tables:
            yield self._issue(
                Severity.WARNING,
                "Table(s) not read (only the first worksheet of a portal export and the mapped "
                "worksheets of a legacy workbook are read): "
                f"{', '.join(inspection.ignored_tables)}.",
            )


@validation_rules.register
class SensorIdRule(TableRule):
    """The sensor of every table must be resolvable (from the file name or a mapping)."""

    rule_id = "sensor-id"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield an ERROR if the sensor is unknown (see :meth:`TableRule.check_table`)."""
        if table.sensor_id is None:
            reason = table.sensor_problem or "no sensor id"
            yield self._issue(
                Severity.ERROR, f"The sensor cannot be resolved: {reason}", table=table.name
            )


@validation_rules.register
class RequiredColumnsRule(TableRule):
    """A header with timestamp, temperature and humidity columns must exist (ERROR)."""

    rule_id = "required-columns"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield an ERROR for a missing header or column (see :meth:`TableRule.check_table`)."""
        if table.header_row is None:
            yield self._issue(
                Severity.ERROR,
                "No header row with a timestamp column in the first "
                f"{table.header_search_rows} rows.",
                table=table.name,
            )
            return
        for problem in table.column_problems:
            yield self._issue(Severity.ERROR, problem, table.header_row, table.name)
        if table.missing_columns:
            yield self._issue(
                Severity.ERROR,
                f"Required column(s) not found: {', '.join(table.missing_columns)}.",
                table.header_row,
                table.name,
            )


@validation_rules.register
class DataRowsRule(TableRule):
    """A table needs at least ``min_data_rows`` data rows below its header (ERROR)."""

    rule_id = "data-rows"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield an ERROR for a header-only table (see :meth:`TableRule.check_table`)."""
        if table.header_row is not None and table.n_data_rows < self.settings.min_data_rows:
            yield self._issue(
                Severity.ERROR,
                f"{table.n_data_rows} data row(s) below the header, at least "
                f"{self.settings.min_data_rows} expected (empty or truncated export).",
                table.header_row,
                table.name,
            )


@validation_rules.register
class ShortRowsRule(TableRule):
    """Rows that end before a mapped column look cut off (WARNING; cells become missing)."""

    rule_id = "short-rows"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield a WARNING for cut-off rows (see :meth:`TableRule.check_table`)."""
        if len(table.short_rows):
            yield self._issue(
                Severity.WARNING,
                f"{len(table.short_rows)} row(s) end before a mapped column (truncated "
                "line?); the missing cells are treated as missing values.",
                int(table.short_rows[0]),
                table.name,
            )


@validation_rules.register
class OptionalColumnsRule(TableRule):
    """A rejected or ambiguous optional column is not read (WARNING).

    Optional columns are precipitation, the cumulative precipitation counter and the battery
    voltage. Unlike a problem with a required column, a problem with one of them does not
    reject the file (owner decision Q9: validity concerns temperature and humidity only).
    """

    rule_id = "optional-columns"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield a WARNING per optional column problem (see :meth:`TableRule.check_table`)."""
        for problem in table.optional_column_problems:
            yield self._issue(
                Severity.WARNING,
                f"{problem} The optional column is not read.",
                table.header_row,
                table.name,
            )


@validation_rules.register
class NumbersParseableRule(TableRule):
    """Value cells must be numbers (decimal comma or point).

    For temperature and humidity, a share of unparseable cells above
    ``max_unparseable_value_share`` is an ERROR; a smaller share is a WARNING and the values
    become missing. For the optional auxiliary columns the same share is reported, but always
    as a WARNING: their values become missing and the file is kept.
    """

    rule_id = "numbers-parseable"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield findings about non-numeric cells (see :meth:`TableRule.check_table`)."""
        required = tuple(column for column in (table.temp, table.rh) if column is not None)
        for column in (*required, *table.auxiliary_columns):
            count = int(column.unparseable.sum())
            if not count:
                continue
            share = _share(count, table.n_data_rows)
            limit = self.settings.max_unparseable_value_share
            severity = _share_severity(count, table.n_data_rows, limit, self.settings)
            if column not in required:
                severity = Severity.WARNING
            consequence = "file rejected" if severity is Severity.ERROR else "read as missing"
            yield self._issue(
                severity,
                f"Column '{column.header}': {count} of {table.n_data_rows} value(s) are not "
                f"numbers ({share:.1%}, limit {limit:.1%}); {consequence}.",
                table.first_row(column.unparseable),
                table.name,
            )


@validation_rules.register
class TimestampsParseableRule(TableRule):
    """Every data row needs a readable timestamp.

    A share of unreadable timestamps above ``max_unparseable_timestamp_share`` is an ERROR, also
    when only a few rows are affected (``min_error_rows`` does not apply: a truncated export,
    whose last line is cut inside the timestamp, must be rejected; WP-1.7 review). A smaller
    share is a WARNING and the rows are dropped.
    """

    rule_id = "timestamps-parseable"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield findings about unreadable timestamps (see :meth:`TableRule.check_table`)."""
        if table.times is None:
            return
        unparseable = table.times.unparseable
        count = int(unparseable.sum())
        if not count:
            return
        share = _share(count, table.n_data_rows)
        limit = self.settings.max_unparseable_timestamp_share
        severity = Severity.ERROR if share > limit else Severity.WARNING
        consequence = "file rejected" if severity is Severity.ERROR else "rows dropped"
        yield self._issue(
            severity,
            f"Column '{table.times.header}': {count} of {table.n_data_rows} timestamp(s) cannot "
            f"be read ({share:.1%}, limit {limit:.1%}); {consequence}.",
            table.first_row(unparseable),
            table.name,
        )


@validation_rules.register
class ValuesPresentRule(TableRule):
    """A table must contain measured values of both variables.

    A temperature or humidity column without any value (empty cells, or formula cells without
    cached results, which openpyxl reads as empty) is an ERROR. Under the whole-row validity
    rule (owner decision 2026-10-05, MIGRATION_PLAN §0.5) every row of such a table would be
    ``MISSING``, so the export holds no valid measurement (e.g. a failed humidity channel).
    """

    rule_id = "values-present"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield findings about empty value columns (see :meth:`TableRule.check_table`)."""
        if table.temp is None or table.rh is None or not table.n_data_rows:
            return
        empty = [column.header for column in (table.temp, table.rh) if not len(column.present)]
        if not empty:
            return
        yield self._issue(
            Severity.ERROR,
            f"Column(s) {', '.join(repr(name) for name in empty)} contain no value in "
            f"{table.n_data_rows} data row(s) (empty cells, or formulas without cached "
            "results); a measurement needs both variables, so the export holds no valid "
            "measurement.",
            table.header_row,
            table.name,
        )


@validation_rules.register
class DateOrderRule(TableRule):
    """Day and month that look swapped (numeric text dates) are an ERROR."""

    rule_id = "date-order"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield an ERROR for an ambiguous date order (see :meth:`TableRule.check_table`)."""
        if table.date_order_problem is not None:
            yield self._issue(Severity.ERROR, table.date_order_problem, table=table.name)


@validation_rules.register
class TimestampsPlausibleRule(TableRule):
    """Timestamps must lie between the earliest plausible time and the run time (plus margin).

    A share of implausible timestamps above ``max_implausible_timestamp_share`` is an ERROR; a
    smaller share is a WARNING and the rows are dropped.
    """

    rule_id = "timestamps-plausible"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield findings about implausible timestamps (see :meth:`TableRule.check_table`)."""
        if table.times is None:
            return
        implausible = table.times.implausible
        count = int(implausible.sum())
        if not count:
            return
        limit = self.settings.max_implausible_timestamp_share
        severity = _share_severity(count, table.n_data_rows, limit, self.settings)
        consequence = "file rejected" if severity is Severity.ERROR else "rows dropped"
        yield self._issue(
            severity,
            f"{count} of {table.n_data_rows} timestamp(s) are outside the plausible range "
            f"(device clock reset or wrong date?) ({_share(count, table.n_data_rows):.1%}, "
            f"limit {limit:.1%}); {consequence}.",
            table.first_row(implausible),
            table.name,
        )


@validation_rules.register
class RowOrderRule(TableRule):
    """A table that steps back but is too short to tell whether it is newest first (WARNING)."""

    rule_id = "row-order"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield a WARNING for an undecidable row order (see :meth:`TableRule.check_table`)."""
        if table.order_undecided:
            yield self._issue(
                Severity.WARNING,
                "Too few rows to decide whether the table is newest first; read oldest first.",
                table=table.name,
            )


@validation_rules.register
class OutOfSequenceRule(TableRule):
    """Rows out of sequence are dropped; too many of them reject the file.

    A row more than ``ParserSettings.max_backward_step_s`` earlier than the latest accepted row
    before it (device clock reset; exact copies from overlapping exports are kept), or an
    isolated row as far ahead of its neighbours (glitched timestamp), is dropped. A share above
    ``max_implausible_timestamp_share`` (and more than ``min_error_rows`` rows) is an ERROR,
    so a mass drop is never silent.
    """

    rule_id = "out-of-sequence"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield findings about dropped rows (see :meth:`TableRule.check_table`)."""
        if table.times is None:
            return
        dropped = table.times.out_of_sequence
        count = int(dropped.sum())
        if not count:
            return
        limit = self.settings.max_implausible_timestamp_share
        severity = _share_severity(count, table.n_data_rows, limit, self.settings)
        consequence = "file rejected" if severity is Severity.ERROR else "dropped"
        yield self._issue(
            severity,
            f"{count} of {table.n_data_rows} row(s) are out of sequence: far earlier than the "
            "rows before them (clock reset?) or isolated far ahead of "
            f"their neighbours ({_share(count, table.n_data_rows):.1%}, limit {limit:.1%}); "
            f"{consequence}.",
            table.first_row(dropped),
            table.name,
        )


@validation_rules.register
class DuplicateTimestampsRule(TableRule):
    """Repeated timestamps are reported (WARNING); the last occurrence is kept.

    Keeping the last row is the behaviour of ``MeasurementSeries.from_records``; conflicts
    between different files are resolved by the measurement store (WP-1.4).
    """

    rule_id = "duplicate-timestamps"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield a WARNING with the number of duplicates (see :meth:`TableRule.check_table`)."""
        if table.times is None or table.temp is None or table.rh is None:
            return
        values = {
            f"value_{position}": column.parsed
            for position, column in enumerate((table.temp, table.rh, *table.auxiliary_columns))
        }
        frame = pd.DataFrame({"t": table.times.utc.to_numpy(), **values})
        frame = frame[frame["t"].notna() & ~table.times.unresolved]
        repeated = frame["t"].duplicated(keep="last")
        count = int(repeated.sum())
        if not count:
            return
        identical = frame.duplicated(keep="last")
        conflicting = count - int(identical.sum())
        positions = frame.index[repeated.to_numpy()]
        mask = np.zeros(table.n_data_rows, dtype=np.bool_)
        mask[positions] = True
        yield self._issue(
            Severity.WARNING,
            f"{count} row(s) repeat an earlier timestamp ({conflicting} with different values); "
            "the last occurrence is kept.",
            table.first_row(mask),
            table.name,
        )


@validation_rules.register
class BackwardStepsRule(TableRule):
    """Rows that step back in local time are reported (WARNING with count and rows).

    Outside daylight-saving hours, a timestamp earlier than the one before it comes from a
    device clock correction or from overlapping exports concatenated into one file. The file
    is not rejected: the parser converts the rows in separate monotonic segments (see
    :mod:`sivin.ingest.parsers.order`), sorts them by time afterwards and keeps the last of
    repeated instants. A table recorded newest first is reversed before this check.
    """

    rule_id = "backward-steps"

    max_listed_rows: ClassVar[int] = 10
    """At most this many row numbers are written into the message."""

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield a WARNING for backward steps (see :meth:`TableRule.check_table`)."""
        count = len(table.backward_rows)
        if not count:
            return
        listed = ", ".join(str(row) for row in table.backward_rows[: self.max_listed_rows])
        more = ", ..." if count > self.max_listed_rows else ""
        yield self._issue(
            Severity.WARNING,
            f"{count} backward step(s) in time (clock correction or overlapping exports?) at "
            f"row(s) {listed}{more}; converted in {count + 1} monotonic segments and sorted "
            "by time.",
            int(table.backward_rows[0]),
            table.name,
        )


@validation_rules.register
class DaylightSavingRule(TableRule):
    """Ambiguous or nonexistent local times are reported (WARNING) and flagged.

    The rows get :attr:`~sivin.core.flags.QcFlag.TIMESTAMP_SUSPECT`; unresolved rows (UTC
    instant guessed or undetermined) are dropped, and their number is part of the finding.
    """

    rule_id = "daylight-saving"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield a WARNING for daylight-saving rows (see :meth:`TableRule.check_table`)."""
        if table.times is None:
            return
        suspect = table.times.suspect
        count = int(suspect.sum())
        if not count:
            return
        dropped = int(
            (table.times.unresolved | (suspect & table.times.utc.isna().to_numpy())).sum()
        )
        yield self._issue(
            Severity.WARNING,
            f"{count} local time(s) fall into a daylight-saving transition and are flagged "
            f"TIMESTAMP_SUSPECT; {dropped} unresolved row(s) dropped.",
            table.first_row(suspect),
            table.name,
        )


class GrossBoundsRule(TableRule):
    """Base of the gross physical bounds checks of one variable.

    A share of present values outside ``[lower, upper]`` above ``max_out_of_bounds_share`` is
    an ERROR (wrong unit or swapped columns); a smaller share is a WARNING and the values are
    left to quality control (WP-1.5). A rule with :attr:`can_reject` false (the optional
    auxiliary columns) reports every finding as a WARNING, and the parser reads those values
    as missing (:func:`outside_bounds`): a value outside gross bounds of an auxiliary column is
    a unit or column mix-up (e.g. a battery charge in % under a unitless ``Battery`` header),
    and no quality check would catch it later.
    """

    variable: ClassVar[str]
    unit: ClassVar[str]
    can_reject: ClassVar[bool] = True
    """Whether a share above the limit rejects the file (only for required variables)."""

    @abstractmethod
    def _column(self, table: TableInspection) -> ValueColumn | None:
        """Return the checked column of ``table``."""

    @abstractmethod
    def _bounds(self) -> tuple[float, float]:
        """Return the inclusive bounds in :attr:`unit`."""

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield findings about impossible values (see :meth:`TableRule.check_table`)."""
        column = self._column(table)
        if column is None:
            return
        lower, upper = self._bounds()
        outside = outside_bounds(column.parsed, (lower, upper))
        count = int(outside.sum())
        if not count:
            return
        share = _share(count, len(column.present))
        limit = self.settings.max_out_of_bounds_share
        severity = _share_severity(count, len(column.present), limit, self.settings)
        if not self.can_reject:
            severity = Severity.WARNING
        hint = " (wrong unit or swapped columns?)" if severity is Severity.ERROR else ""
        if not self.can_reject:
            hint = "; read as missing"
        yield self._issue(
            severity,
            f"{count} {self.variable} value(s) outside [{lower:g}, {upper:g}] {self.unit} "
            f"({share:.1%} of present values, limit {limit:.1%}){hint}.",
            table.first_row(outside),
            table.name,
        )


@validation_rules.register
class TemperatureBoundsRule(GrossBoundsRule):
    """Gross bounds of air temperature (``temp_min_c`` to ``temp_max_c``)."""

    rule_id = "temperature-bounds"
    variable = "temperature"
    unit = "°C"

    def _column(self, table: TableInspection) -> ValueColumn | None:
        return table.temp

    def _bounds(self) -> tuple[float, float]:
        return self.settings.temp_min_c, self.settings.temp_max_c


@validation_rules.register
class HumidityBoundsRule(GrossBoundsRule):
    """Physical bounds of relative humidity (``rh_min_pct`` to ``rh_max_pct``)."""

    rule_id = "humidity-bounds"
    variable = "relative humidity"
    unit = "%"

    def _column(self, table: TableInspection) -> ValueColumn | None:
        return table.rh

    def _bounds(self) -> tuple[float, float]:
        return self.settings.rh_min_pct, self.settings.rh_max_pct


@validation_rules.register
class PrecipitationBoundsRule(GrossBoundsRule):
    """Gross bounds of the precipitation per interval (``precip_min_mm`` to ``precip_max_mm``).

    Never rejects the file; values outside are read as missing.
    """

    rule_id = "precipitation-bounds"
    variable = "precipitation"
    unit = "mm"
    can_reject = False

    def _column(self, table: TableInspection) -> ValueColumn | None:
        return table.precip

    def _bounds(self) -> tuple[float, float]:
        return self.settings.precip_bounds_mm


@validation_rules.register
class PrecipitationTotalBoundsRule(GrossBoundsRule):
    """Gross bounds of the cumulative precipitation counter (never rejects; outside = missing)."""

    rule_id = "precipitation-total-bounds"
    variable = "cumulative precipitation"
    unit = "mm"
    can_reject = False

    def _column(self, table: TableInspection) -> ValueColumn | None:
        return table.precip_total

    def _bounds(self) -> tuple[float, float]:
        return self.settings.precip_total_bounds_mm


@validation_rules.register
class BatteryBoundsRule(GrossBoundsRule):
    """Gross bounds of the battery voltage (``battery_min_v`` to ``battery_max_v``).

    Never rejects the file; values outside (e.g. a charge in %) are read as missing.
    """

    rule_id = "battery-bounds"
    variable = "battery voltage"
    unit = "V"
    can_reject = False

    def _column(self, table: TableInspection) -> ValueColumn | None:
        return table.battery

    def _bounds(self) -> tuple[float, float]:
        return self.settings.battery_bounds_v


@validation_rules.register
class HumidityFractionRule(TableRule):
    """Relative humidity given as a 0-1 fraction instead of % is an ERROR.

    Such values lie inside the physical bounds, so :class:`HumidityBoundsRule` cannot see them.
    The file is rejected when the share of values at or below ``rh_fraction_max_pct`` exceeds
    ``max_out_of_bounds_share`` (and their number ``min_error_rows``), or all values are.
    """

    rule_id = "humidity-fraction"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield an ERROR for fraction-like humidity (see :meth:`TableRule.check_table`)."""
        if table.rh is None:
            return
        present = table.rh.present
        threshold = self.settings.rh_fraction_max_pct
        count = int((present <= threshold).sum())
        share = _share(count, len(present))
        limit = self.settings.max_out_of_bounds_share
        if count and _share_severity(count, len(present), limit, self.settings) is Severity.ERROR:
            yield self._issue(
                Severity.ERROR,
                f"{share:.1%} of the relative humidity values are at or below {threshold:g} %; "
                "the column looks like a 0-1 fraction instead of a percentage.",
                table=table.name,
            )
