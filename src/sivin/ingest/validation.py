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

    The defaults are project defaults, not taken from literature, and are to be tuned once real
    exports are available (owner question Q1).
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

    @model_validator(mode="after")
    def _ordered_bounds(self) -> Self:
        if self.temp_min_c >= self.temp_max_c:
            raise ValueError("temp_min_c must be lower than temp_max_c")
        if self.rh_min_pct >= self.rh_max_pct:
            raise ValueError("rh_min_pct must be lower than rh_max_pct")
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
        Timestamps converted to UTC (``datetime64[ns, UTC]``); ``NaT`` where unparseable or
        where the daylight-saving conversion collided with another row.
    suspect : numpy.ndarray of bool
        Ambiguous or nonexistent local time (daylight-saving transition).
    unresolved : numpy.ndarray of bool
        Subset of ``suspect`` whose UTC instant is a guess or ``NaT``.
    """

    header: str
    local: pd.Series
    utc: pd.Series
    suspect: BoolArray
    unresolved: BoolArray

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
        Canonical columns (``timestamp``, ``temp_c``, ``rh_pct``) without a matching header.
    column_problems : tuple of str
        Descriptions of headers that were rejected (e.g. an unexpected unit) or ambiguous.
    source_rows : numpy.ndarray of int64
        1-based source row number of every data row (non-blank rows below the header), in
        the order of the columns below.
    short_rows : numpy.ndarray of int64
        Source row numbers of data rows that end before a mapped column (cut-off lines).
    reversed_order : bool
        ``True`` if the rows were recorded newest first and were reversed by the parser.
    backward_rows : numpy.ndarray of int64
        Source row numbers of the rows (outside daylight-saving hours) that are earlier than
        the row before them, after a possible reversal.
    times, temp, rh : TimeColumn, ValueColumn or None
        Parsed columns; ``None`` when the header or a required column is missing.
    """

    name: str
    sensor_id: SensorId | None
    sensor_problem: str | None = None
    header_search_rows: int = 0
    header_row: int | None = None
    missing_columns: tuple[str, ...] = ()
    column_problems: tuple[str, ...] = ()
    source_rows: RowArray = field(default_factory=_no_rows)
    short_rows: RowArray = field(default_factory=_no_rows)
    reversed_order: bool = False
    backward_rows: RowArray = field(default_factory=_no_rows)
    times: TimeColumn | None = None
    temp: ValueColumn | None = None
    rh: ValueColumn | None = None

    @property
    def n_data_rows(self) -> int:
        """Number of data rows below the header."""
        return len(self.source_rows)

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


def _share(count: int, total: int) -> float:
    return count / total if total else 0.0


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
                "Table(s) without a sensor mapping were not read: "
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
    """Rows that end before a required column look cut off (WARNING; cells become missing)."""

    rule_id = "short-rows"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield a WARNING for cut-off rows (see :meth:`TableRule.check_table`)."""
        if len(table.short_rows):
            yield self._issue(
                Severity.WARNING,
                f"{len(table.short_rows)} row(s) end before a required column (truncated "
                "line?); the missing cells are treated as missing values.",
                int(table.short_rows[0]),
                table.name,
            )


@validation_rules.register
class NumbersParseableRule(TableRule):
    """Temperature and humidity cells must be numbers (decimal comma or point).

    A share of unparseable cells above ``max_unparseable_value_share`` is an ERROR; a smaller
    share is a WARNING and the values become missing.
    """

    rule_id = "numbers-parseable"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield findings about non-numeric cells (see :meth:`TableRule.check_table`)."""
        for column in (table.temp, table.rh):
            if column is None:
                continue
            count = int(column.unparseable.sum())
            if not count:
                continue
            share = _share(count, table.n_data_rows)
            limit = self.settings.max_unparseable_value_share
            severity = Severity.ERROR if share > limit else Severity.WARNING
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

    A share of unreadable timestamps above ``max_unparseable_timestamp_share`` is an ERROR; a
    smaller share is a WARNING and the rows are dropped.
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
        frame = pd.DataFrame(
            {"t": table.times.utc.to_numpy(), "temp": table.temp.parsed, "rh": table.rh.parsed}
        )
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
    left to quality control (WP-1.5).
    """

    variable: ClassVar[str]
    unit: ClassVar[str]

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
        with np.errstate(invalid="ignore"):
            outside = (column.parsed < lower) | (column.parsed > upper)
        count = int(outside.sum())
        if not count:
            return
        share = _share(count, len(column.present))
        limit = self.settings.max_out_of_bounds_share
        severity = Severity.ERROR if share > limit else Severity.WARNING
        hint = " (wrong unit or swapped columns?)" if severity is Severity.ERROR else ""
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
class HumidityFractionRule(TableRule):
    """Relative humidity given as a 0-1 fraction instead of % is an ERROR.

    Such values lie inside the physical bounds, so :class:`HumidityBoundsRule` cannot see them.
    The file is rejected when the share of values at or below ``rh_fraction_max_pct`` exceeds
    ``max_out_of_bounds_share``.
    """

    rule_id = "humidity-fraction"

    def check_table(self, table: TableInspection) -> Iterator[ValidationIssue]:
        """Yield an ERROR for fraction-like humidity (see :meth:`TableRule.check_table`)."""
        if table.rh is None:
            return
        present = table.rh.present
        threshold = self.settings.rh_fraction_max_pct
        share = _share(int((present <= threshold).sum()), len(present))
        if share > self.settings.max_out_of_bounds_share:
            yield self._issue(
                Severity.ERROR,
                f"{share:.1%} of the relative humidity values are at or below {threshold:g} %; "
                "the column looks like a 0-1 fraction instead of a percentage.",
                table=table.name,
            )
