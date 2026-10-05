"""Tests of the command-line interface."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sivin import __version__, cli
from sivin.config import SivinConfig
from sivin.logging_setup import setup_logging

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_global_logging_setup(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record setup_logging calls instead of reconfiguring the root logger of pytest."""
    calls: list[str] = []
    monkeypatch.setattr(cli, "setup_logging", calls.append)
    return calls


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output == f"sivin {__version__}\n"


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(cli.app, [])
    assert "config" in result.output


def test_config_show_with_explicit_file(tmp_path: Path, no_global_logging_setup: list[str]) -> None:
    path = tmp_path / "custom.yaml"
    path.write_text("analytics:\n  min_daily_coverage: 0.8\n", encoding="utf-8")
    result = runner.invoke(
        cli.app, ["--log-level", "debug", "config", "show", "--config", str(path)]
    )
    assert result.exit_code == 0, result.output
    shown = yaml.safe_load(result.output)
    assert shown["analytics"]["min_daily_coverage"] == 0.8
    assert shown["time"]["expected_interval_s"] == 1830.0
    assert no_global_logging_setup == ["debug"]


def test_config_show_uses_project_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sivin.yaml").write_text(
        "time:\n  display_timezone: UTC\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path / "config")
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert yaml.safe_load(result.output)["time"]["display_timezone"] == "UTC"


def test_config_show_defaults_without_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").touch()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert yaml.safe_load(result.output) == SivinConfig.default().model_dump(mode="json")


def test_config_show_defaults_outside_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert yaml.safe_load(result.output) == SivinConfig.default().model_dump(mode="json")


def test_config_show_reports_invalid_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("analytics:\n  min_daily_coverag: 0.8\n", encoding="utf-8")
    result = runner.invoke(cli.app, ["config", "show", "--config", str(path)])
    assert result.exit_code == 1
    assert "analytics.min_daily_coverag" in result.output


def test_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", setup_logging)
    result = runner.invoke(cli.app, ["--log-level", "loud", "config", "show"])
    assert result.exit_code == 2
    assert "Unknown log level" in result.output


def test_setup_logging_configures_root_logger() -> None:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        setup_logging("warning")
        assert root.level == logging.WARNING
        assert len(root.handlers) == 1
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
    with pytest.raises(ValueError, match="Unknown log level"):
        setup_logging("verbose")
