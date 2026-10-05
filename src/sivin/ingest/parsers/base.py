"""Extension point for export formats: :class:`ExportParser` and its registry.

A new export format is a new subclass of :class:`ExportParser` that registers itself::

    @parser_registry.register
    class MyFormatParser(ExportParser):
        format_id = "my-format"

        def can_parse(self, path: Path) -> bool: ...

        def parse(self, path: Path) -> ParsedExport: ...

:meth:`ParserRegistry.for_file` picks the one parser whose :meth:`ExportParser.can_parse`
accepts a file. The concrete parsers live in :mod:`sivin.ingest.parsers.portal` and
:mod:`sivin.ingest.parsers.legacy`; importing :mod:`sivin.ingest.parsers` registers them.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

from sivin.core.schema import MeasurementSeries
from sivin.ingest.parsers.columns import ParserSettings
from sivin.ingest.validation import InputValidator, ValidationReport

logger = logging.getLogger(__name__)


class UnsupportedExportError(ValueError):
    """Raised when no registered parser accepts a file."""


class AmbiguousExportError(ValueError):
    """Raised when more than one registered parser accepts a file."""


@dataclass(frozen=True)
class ParsedExport:
    """The result of parsing one export file.

    Attributes
    ----------
    series : tuple of MeasurementSeries
        One series per sensor in the file (a workbook can hold several). Empty if the report
        has an error: a rejected file yields no data.
    source : pathlib.Path
        The export file.
    report : ValidationReport
        All validation findings of the file.

    Raises
    ------
    ValueError
        If series are given together with a report that has errors.
    """

    series: tuple[MeasurementSeries, ...]
    source: Path
    report: ValidationReport

    def __post_init__(self) -> None:
        if self.series and not self.report.is_acceptable:
            raise ValueError("A rejected export must not carry series.")

    @property
    def is_accepted(self) -> bool:
        """``True`` if the file passed validation (its series may be imported)."""
        return self.report.is_acceptable


class ExportParser(ABC):
    """Read one kind of export file into validated :class:`MeasurementSeries`.

    Parsers never raise for bad file content: they return a :class:`ParsedExport` with an
    empty ``series`` and a report that explains the problem.

    Attributes
    ----------
    format_id : str
        Unique identifier of the format, also the key in the registry.

    Parameters
    ----------
    settings : ParserSettings, optional
        Parser settings; defaults when omitted.
    validator : InputValidator, optional
        The validator to run on every file; one with default settings when omitted.
    """

    format_id: ClassVar[str]

    def __init__(
        self, settings: ParserSettings | None = None, validator: InputValidator | None = None
    ) -> None:
        self._settings = settings or ParserSettings()
        self._validator = validator or InputValidator()

    @property
    def settings(self) -> ParserSettings:
        """The parser settings."""
        return self._settings

    @property
    def validator(self) -> InputValidator:
        """The input validator."""
        return self._validator

    @abstractmethod
    def can_parse(self, path: Path) -> bool:
        """Tell whether this parser is responsible for a file.

        The decision must be cheap (normally the file name only) and must not overlap with
        any other registered parser.

        Parameters
        ----------
        path : pathlib.Path
            The export file (it need not exist).

        Returns
        -------
        bool
            ``True`` if :meth:`parse` should be used for the file.
        """

    @abstractmethod
    def parse(self, path: Path) -> ParsedExport:
        """Read, validate and convert one export file.

        Parameters
        ----------
        path : pathlib.Path
            The export file.

        Returns
        -------
        ParsedExport
            The series and the validation report.
        """


type ParserClass = type[ExportParser]
"""A concrete :class:`ExportParser` subclass."""


class ParserRegistry:
    """Registry of export parser classes, keyed by :attr:`ExportParser.format_id`.

    Registries are the one kind of module-level mutable state the project allows
    (MIGRATION_PLAN §1.2): they are filled by class decorators at import and never changed
    afterwards.
    """

    __slots__ = ("_classes",)

    def __init__(self) -> None:
        self._classes: dict[str, ParserClass] = {}

    def register[C: ParserClass](self, cls: C) -> C:
        """Register a parser class; use as a class decorator.

        Parameters
        ----------
        cls : type[ExportParser]
            A concrete parser with a unique ``format_id``.

        Returns
        -------
        type[ExportParser]
            The class unchanged.

        Raises
        ------
        TypeError
            If ``cls`` is not a concrete parser with a non-empty ``format_id``.
        ValueError
            If the ``format_id`` is already registered.
        """
        if not (isinstance(cls, type) and issubclass(cls, ExportParser)):
            raise TypeError(f"Only ExportParser subclasses can be registered, got {cls!r}.")
        if getattr(cls, "__abstractmethods__", None):
            raise TypeError(f"{cls.__name__} is abstract and cannot be registered.")
        format_id = getattr(cls, "format_id", None)
        if not isinstance(format_id, str) or not format_id:
            raise TypeError(f"{cls.__name__} must define a non-empty class variable 'format_id'.")
        if format_id in self._classes:
            raise ValueError(f"Export format {format_id!r} is already registered.")
        self._classes[format_id] = cls
        return cls

    def ids(self) -> tuple[str, ...]:
        """Return the registered format ids, sorted.

        Returns
        -------
        tuple of str
            Format identifiers.
        """
        return tuple(sorted(self._classes))

    def get(self, format_id: str) -> ParserClass:
        """Return the class registered under ``format_id``.

        Parameters
        ----------
        format_id : str
            Identifier of a registered format.

        Returns
        -------
        type[ExportParser]
            The parser class.

        Raises
        ------
        KeyError
            If the format is not registered.
        """
        try:
            return self._classes[format_id]
        except KeyError:
            raise KeyError(
                f"Unknown export format {format_id!r}; registered: {', '.join(self.ids())}."
            ) from None

    def for_file(
        self,
        path: Path,
        settings: ParserSettings | None = None,
        validator: InputValidator | None = None,
    ) -> ExportParser:
        """Return the one parser responsible for a file.

        Parameters
        ----------
        path : pathlib.Path
            The export file.
        settings : ParserSettings, optional
            Settings for the parser; defaults when omitted.
        validator : InputValidator, optional
            Validator for the parser; one with default settings when omitted.

        Returns
        -------
        ExportParser
            A new instance of the parser whose :meth:`~ExportParser.can_parse` accepts the file.

        Raises
        ------
        UnsupportedExportError
            If no registered parser accepts the file.
        AmbiguousExportError
            If several parsers accept it (overlapping ``can_parse`` rules are a bug).
        """
        parsers = [cls(settings, validator) for cls in self._classes.values()]
        accepting = [parser for parser in parsers if parser.can_parse(path)]
        if not accepting:
            raise UnsupportedExportError(
                f"No export parser accepts {path.name!r}; formats: {', '.join(self.ids())}."
            )
        if len(accepting) > 1:
            names = ", ".join(parser.format_id for parser in accepting)
            raise AmbiguousExportError(f"Several export parsers accept {path.name!r}: {names}.")
        logger.debug("Export %s is read by %s.", path.name, accepting[0].format_id)
        return accepting[0]

    def __contains__(self, format_id: object) -> bool:
        return format_id in self._classes

    def __len__(self) -> int:
        return len(self._classes)


parser_registry: Final = ParserRegistry()
"""The project-wide registry of export parsers."""
