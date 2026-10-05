"""Tests of the parser extension point: ParsedExport and ParserRegistry."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries
from sivin.ingest.parsers import legacy, portal
from sivin.ingest.parsers.base import (
    AmbiguousExportError,
    ExportParser,
    ParsedExport,
    ParserRegistry,
    UnsupportedExportError,
    parser_registry,
)
from sivin.ingest.parsers.columns import ParserSettings
from sivin.ingest.validation import (
    InputValidator,
    Severity,
    ValidationIssue,
    ValidationReport,
)

from ..conftest import EXPORTS, PORTAL_CSV_NAME


class _Csv(ExportParser):
    format_id = "test-csv"

    def can_parse(self, path: Path) -> bool:
        return path.suffix == ".csv"

    def parse(self, path: Path) -> ParsedExport:
        return ParsedExport((), path, ValidationReport())


class _AnyFile(_Csv):
    format_id = "test-any"

    def can_parse(self, path: Path) -> bool:
        return True


def test_all_parsers_are_registered() -> None:
    assert parser_registry.ids() == ("legacy-workbook", "portal-csv", "portal-xlsx")
    assert parser_registry.get("portal-csv") is portal.PortalCsvParser
    assert "legacy-workbook" in parser_registry
    assert len(parser_registry) == 3
    assert legacy.LegacyWorkbookParser.format_id == "legacy-workbook"


@pytest.mark.parametrize(
    ("relative", "format_id"),
    [
        (f"valid/{PORTAL_CSV_NAME}", "portal-csv"),
        ("valid/MeteoData_8615620 77678271.xlsx", "portal-xlsx"),
        ("legacy/data.xlsx", "legacy-workbook"),
        ("broken/unknown_name/export.csv", "portal-csv"),
    ],
)
def test_for_file_picks_one_parser(relative: str, format_id: str, settings: ParserSettings) -> None:
    parser = parser_registry.for_file(EXPORTS / relative, settings)
    assert parser.format_id == format_id
    assert parser.settings is settings


def test_for_file_passes_the_validator() -> None:
    validator = InputValidator()
    parser = parser_registry.for_file(Path("a.csv"), validator=validator)
    assert parser.validator is validator


def test_for_file_without_parser() -> None:
    with pytest.raises(UnsupportedExportError, match=r"No export parser accepts 'data\.xlsx'"):
        parser_registry.for_file(Path("data.xlsx"))
    with pytest.raises(UnsupportedExportError):
        parser_registry.for_file(Path("notes.txt"))


def test_ambiguous_parsers_are_an_error() -> None:
    registry = ParserRegistry()
    registry.register(_Csv)
    registry.register(_AnyFile)
    assert isinstance(registry.for_file(Path("a.txt")), _AnyFile)
    with pytest.raises(AmbiguousExportError, match="test-csv, test-any"):
        registry.for_file(Path("a.csv"))


def test_registration_errors() -> None:
    registry = ParserRegistry()
    registry.register(_Csv)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_Csv)
    with pytest.raises(TypeError, match="Only ExportParser"):
        registry.register(int)  # type: ignore[type-var]
    with pytest.raises(TypeError, match="abstract"):
        registry.register(ExportParser)  # type: ignore[type-abstract]

    class Nameless(_Csv):
        format_id = ""

    with pytest.raises(TypeError, match="format_id"):
        registry.register(Nameless)
    with pytest.raises(KeyError, match="Unknown export format 'x'"):
        registry.get("x")


def test_rejected_export_cannot_carry_series() -> None:
    series = MeasurementSeries.from_records(
        SensorId("77678271"), [pd.Timestamp("2026-01-01", tz="UTC")], [1.0], [50.0]
    )
    error = ValidationIssue("file-exists", Severity.ERROR, "missing")
    with pytest.raises(ValueError, match="rejected export"):
        ParsedExport((series,), Path("a.csv"), ValidationReport((error,)))
    accepted = ParsedExport((series,), Path("a.csv"), ValidationReport())
    assert accepted.is_accepted
