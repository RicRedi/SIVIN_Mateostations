"""Tests of the targeted .gitignore rules (data ignored, sources and fixtures versioned)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout"
)


def is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT, check=False
    )
    return result.returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        "tests/fixtures/exports/a.xlsx",
        "tests/fixtures/exports/a.csv",
        "tests/fixtures/a.log",
        "web/public/data/manifest.json",
        "web/src/data/DataClient.ts",
        "web/src/lib/x.ts",
        "docs/wp_log/img/WP-3.1-desktop.png",
        "src/sivin/x/data/a.csv",
        "sensors/sensors.geojson",
        "config/sivin.yaml",
    ],
)
def test_versioned_paths_are_not_ignored(path: str) -> None:
    assert not is_ignored(path)


@pytest.mark.parametrize(
    "path",
    [
        "data/raw/77678271/2026.csv",
        "site/data/manifest.json",
        "vystupy/graf.png",
        "data.xlsx",
        "MeteoData_8615620 77678271 (VUT)_20260301_223857.csv",
        ".env",
        ".venv/bin/python",
        "web/node_modules/a/index.js",
        "web/dist/index.html",
    ],
)
def test_data_and_local_files_are_ignored(path: str) -> None:
    assert is_ignored(path)
