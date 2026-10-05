"""The committed SYNTHETIC fixtures are exactly what make_fixtures.py generates.

The real export below ``real/`` is not generated and is tested in ``test_real_export.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import openpyxl

from .conftest import EXPORTS, REAL_EXPORTS


def committed_files() -> list[Path]:
    """The committed synthetic fixtures (the real export is excluded)."""
    return sorted(
        path.relative_to(EXPORTS)
        for path in EXPORTS.rglob("*")
        if path.is_file()
        and path.suffix in {".csv", ".xlsx"}
        and not path.is_relative_to(REAL_EXPORTS)
    )


def cells(path: Path) -> list[tuple[str, list[tuple[object, ...]]]]:
    workbook = openpyxl.load_workbook(path)
    return [(sheet.title, list(sheet.iter_rows(values_only=True))) for sheet in workbook]


def test_generator_reproduces_the_committed_fixtures(
    make_fixtures: ModuleType, tmp_path: Path
) -> None:
    make_fixtures.generate(tmp_path)
    generated = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file())
    assert generated == committed_files()
    for relative in generated:
        fresh, committed = tmp_path / relative, EXPORTS / relative
        if relative.suffix == ".csv":
            assert fresh.read_bytes() == committed.read_bytes(), relative
        elif "truncated" in relative.parts[1]:
            assert fresh.stat().st_size > 0
        else:
            assert cells(fresh) == cells(committed), relative


def test_readme_lists_every_fixture_directory() -> None:
    readme = (EXPORTS / "README.md").read_text(encoding="utf-8")
    assert "SYNTHETIC" in readme
    for relative in committed_files():
        assert f"`{relative.parent.as_posix()}/`" in readme, relative
