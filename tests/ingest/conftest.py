"""Shared helpers of the ingest tests. All data are SYNTHETIC (see tests/fixtures/exports)."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType

import pytest

from sivin.ingest.parsers.columns import ParserSettings

EXPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "exports"
"""Directory of the committed synthetic export fixtures."""

PORTAL_CSV_NAME = "MeteoData_8615620 77678271 (VUT)_20260301_223857.csv"
LEGACY_SHEETS = {"8271": "77678271", "0921": "77680921"}


def load_fixture_module() -> ModuleType:
    """Import ``tests/fixtures/exports/make_fixtures.py`` (it is not a package)."""
    spec = importlib.util.spec_from_file_location("make_fixtures", EXPORTS / "make_fixtures.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def make_fixtures() -> ModuleType:
    return load_fixture_module()


@pytest.fixture
def settings() -> ParserSettings:
    """Parser settings with the legacy worksheet mapping of the fixture workbook."""
    return ParserSettings(legacy_sheet_sensors=LEGACY_SHEETS)


CsvWriter = Callable[..., Path]


@pytest.fixture
def write_csv(tmp_path: Path) -> CsvWriter:
    """Write a synthetic portal CSV from text rows; returns its path."""

    def writer(
        rows: Sequence[Sequence[str]],
        header: Sequence[str] = ("Datum a čas", "Teplota (°C)", "Vlhkost (%)"),
        name: str = PORTAL_CSV_NAME,
        title: str | None = "Meteo Data;",
        encoding: str = "utf-8",
    ) -> Path:
        lines = [] if title is None else [title]
        lines += [";".join(header), *(";".join(row) for row in rows)]
        path = tmp_path / name
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode(encoding))
        return path

    return writer
