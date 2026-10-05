"""Shared helpers of the ingest tests. All data are SYNTHETIC (see tests/fixtures/exports)."""

from __future__ import annotations

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
    """Import ``tests/fixtures/exports/make_fixtures.py`` (it is not a package).

    The source is executed directly, so no ``__pycache__`` is written into the fixture
    directory (``.gitignore`` re-includes everything below ``tests/fixtures/``).
    """
    path = EXPORTS / "make_fixtures.py"
    module = ModuleType("make_fixtures")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module  # dataclasses look their module up there
    exec(compile(path.read_text(encoding="utf-8"), path, "exec"), module.__dict__)
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
