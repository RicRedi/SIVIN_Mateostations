"""Tests of AtomicFileWriter."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from sivin.storage.atomic import NEW_FILE_MODE, AtomicFileWriter


def test_creates_parents_and_file_with_default_mode(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "file.csv"
    with AtomicFileWriter().open(target) as stream:
        stream.write(b"content\n")
    assert target.read_bytes() == b"content\n"
    assert stat.S_IMODE(target.stat().st_mode) == NEW_FILE_MODE
    assert sorted(path.name for path in target.parent.iterdir()) == ["file.csv"]


def test_replacement_keeps_existing_mode(tmp_path: Path) -> None:
    target = tmp_path / "file.csv"
    target.write_bytes(b"old")
    target.chmod(0o640)
    with AtomicFileWriter().open(target) as stream:
        stream.write(b"new")
    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_exception_mid_write_keeps_old_content_and_removes_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "file.csv"
    target.write_bytes(b"old content")

    def write_half_then_crash() -> None:
        with AtomicFileWriter().open(target) as stream:
            stream.write(b"half of the new")
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        write_half_then_crash()
    assert target.read_bytes() == b"old content"
    assert [path.name for path in tmp_path.iterdir()] == ["file.csv"]


def test_failing_rename_keeps_old_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "file.csv"
    target.write_bytes(b"old content")

    def failing_replace(source: object, destination: object) -> None:
        raise OSError("rename failed (injected)")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="injected"), AtomicFileWriter().open(target) as stream:
        stream.write(b"new content")
    assert target.read_bytes() == b"old content"
    assert [path.name for path in tmp_path.iterdir()] == ["file.csv"]
