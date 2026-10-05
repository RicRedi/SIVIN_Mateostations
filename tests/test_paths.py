"""Tests of ProjectPaths."""

from __future__ import annotations

from pathlib import Path

import pytest

from sivin.paths import ProjectPaths, ProjectRootNotFoundError


def test_discover_walks_up_to_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert ProjectPaths.discover(nested).root == tmp_path.resolve()
    assert ProjectPaths.discover(tmp_path).root == tmp_path.resolve()


def test_discover_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").touch()
    monkeypatch.chdir(tmp_path)
    assert ProjectPaths.discover().root == tmp_path.resolve()


def test_discover_finds_this_repository() -> None:
    root = ProjectPaths.discover(Path(__file__).parent).root
    assert (root / "src" / "sivin" / "paths.py").is_file()


def test_discover_fails_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    with pytest.raises(ProjectRootNotFoundError, match=r"No pyproject\.toml found"):
        ProjectPaths.discover(tmp_path)


def test_resolve(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    assert paths.resolve("data/raw") == tmp_path / "data" / "raw"
    assert paths.resolve(Path("config/sivin.yaml")) == tmp_path / "config" / "sivin.yaml"
    absolute = tmp_path / "elsewhere"
    assert paths.resolve(absolute) == absolute


def test_root_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="absolute"):
        ProjectPaths(Path("relative/root"))
