"""End to end: ``sivin build-site`` and ``sivin run`` produce the site data the web reads.

The run fixture is the trimmed REAL export of 77799986 and a SYNTHETIC export of 77678271
(``tests/site/python_site.py``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.app.project import Project, make_project, write_synthetic_export
from tests.site.python_site import (
    FIXTURE_DIR,
    FIXTURE_README,
    README_TEXT,
    RUN_TIME,
    build_site,
    contract_files,
)
from typer.testing import CliRunner, Result

from sivin.cli import main as cli
from sivin.cli.state import CliOverrides

runner = CliRunner()
REGENERATE = ".venv/bin/python -m tests.site.python_site"


@pytest.fixture(autouse=True)
def no_global_logging_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda level: None)


def sivin(*args: str, clock: datetime = RUN_TIME) -> Result:
    result = runner.invoke(cli.app, list(args), obj=CliOverrides(clock=lambda: clock))
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    return result


def test_run_skip_fetch_matches_the_web_fixture(tmp_path: Path) -> None:
    generated = contract_files(build_site(tmp_path))
    committed = contract_files(FIXTURE_DIR)
    assert sorted(generated) == sorted(committed), f"fixture is stale; run {REGENERATE}"
    for path, content in generated.items():
        assert committed[path] == content, f"{path} is stale; run {REGENERATE}"
    readme = (FIXTURE_DIR / FIXTURE_README).read_text(encoding="utf-8")
    assert readme == README_TEXT


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    made = make_project(tmp_path / "vineyard")
    made.real_export()
    write_synthetic_export(made.downloads, days=2)
    monkeypatch.chdir(made.root)
    assert sivin("ingest").exit_code == 0
    return made


def test_build_site_command(project: Project) -> None:
    first = sivin("build-site")
    assert first.exit_code == 0, first.output
    assert "Site data (full)" in first.output
    assert "2 sensor(s) built, 0 reused" in first.output
    assert "seasons: 2025, 2026" in first.output

    again = sivin("build-site", clock=datetime(2026, 10, 6, 4, 0, tzinfo=UTC))
    assert again.exit_code == 0, again.output
    assert "Site data (incremental)" in again.output
    # A new generated_at changes manifest, latest and both indices files; nothing else.
    assert "0 sensor(s) built, 2 reused, 4 file(s) written" in again.output


def test_build_site_options(project: Project) -> None:
    out = project.root / "elsewhere"
    result = sivin("build-site", "--out", str(out), "--season", "2026", "--full")
    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seasons"] == [2026]
    assert sorted(path.name for path in (out / "indices").iterdir()) == ["2026.json"]
    assert not (project.root / "site").exists()


def test_run_skip_site(project: Project) -> None:
    result = sivin("run", "--skip-fetch", "--skip-site")
    assert result.exit_code == 0, result.output
    assert "Site data not built" in result.output
    assert not (project.root / "site").exists()


def test_build_site_outside_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert sivin("build-site").exit_code == 3
