"""No credential leaves the process: console, run record and derived files (WP-1.7 round 3).

The fake portal's login fields raise a Selenium exception that quotes the typed text, as a
driver error message might. Everything here is SYNTHETIC; no portal is contacted.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from selenium.common.exceptions import WebDriverException
from tests.app.fake_portal import credentials, drivers
from tests.app.project import EMPTY_OFFSITE_LOG, Project, make_project, write_synthetic_export
from tests.ingest.portal import conftest as fake
from typer.testing import CliRunner, Result

from sivin.cli import main as cli
from sivin.cli.state import CliOverrides
from sivin.redaction import MIN_SECRET_LENGTH, REDACTED

RUN_TIME = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_global_logging_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pytest's logging configuration (the CLI would reconfigure the root logger)."""
    monkeypatch.setattr(cli, "setup_logging", lambda level: None)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A project with stored data, so that ``sivin run`` also writes derived files."""
    made = make_project(tmp_path / "p", offsite_log=EMPTY_OFFSITE_LOG)
    monkeypatch.chdir(made.root)
    write_synthetic_export(made.downloads, days=2)
    assert invoke("ingest").exit_code == 0
    return made


def invoke(*args: str) -> Result:
    obj = CliOverrides(drivers=drivers(), credentials=credentials, clock=lambda: RUN_TIME)
    return runner.invoke(cli.app, list(args), obj=obj)


def leaking_field(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    """Make the login field ``field`` raise an error that contains the typed text."""
    original = fake.FakeElement.send_keys

    def send_keys(self: fake.FakeElement, text: str) -> None:
        if self.key == field:
            raise WebDriverException(f"element <{field}> rejected input {text!r}")
        original(self, text)

    monkeypatch.setattr(fake.FakeElement, "send_keys", send_keys)


def written_texts(root: Path) -> dict[str, str]:
    """Every file the run wrote below ``data/`` (store, run record, derived files)."""
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted((root / "data").rglob("*"))
        if path.is_file() and path.suffix in {".json", ".jsonl", ".csv", ".geojson"}
    }


@pytest.mark.parametrize("field", ["username", "password"])
@pytest.mark.parametrize("in_environment", [True, False])
@pytest.mark.parametrize("command", ["fetch", "run"])
def test_credentials_in_a_selenium_error_never_leave_the_process(
    project: Project,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    field: str,
    in_environment: bool,
    command: str,
) -> None:
    if in_environment:
        monkeypatch.setenv("SIVIN_USER", fake.USERNAME)
        monkeypatch.setenv("SIVIN_PASSWORD", fake.PASSWORD)
    else:
        monkeypatch.delenv("SIVIN_USER", raising=False)
        monkeypatch.delenv("SIVIN_PASSWORD", raising=False)
    leaking_field(monkeypatch, field)
    args = [command] if command == "fetch" else [command, "--season", "2026"]
    result = invoke(*args)
    assert result.exit_code == 4, result.output
    assert "Portal session failed: WebDriverException" in result.stderr
    assert f"rejected input '{REDACTED}'" in result.stderr
    files = written_texts(project.root)
    if command == "run":
        assert any(name.startswith("data/runs/") for name in files)
        assert any(name.startswith("data/derived/") for name in files)
    for secret in (fake.USERNAME, fake.PASSWORD):
        assert secret not in result.stdout
        assert secret not in result.stderr
        for name, text in files.items():
            assert secret not in text, name


def test_short_credential_is_reported_once_without_its_value(
    project: Project, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    short = "q7Z"
    assert len(short) < MIN_SECRET_LENGTH
    monkeypatch.setenv("SIVIN_PASSWORD", short)
    monkeypatch.setenv("SIVIN_USER", "long-enough-user")
    with caplog.at_level(logging.WARNING, logger="sivin"):
        result = invoke("sensors", "check")
    assert result.exit_code == 0, result.output
    warnings = [r.getMessage() for r in caplog.records if "cannot be redacted" in r.getMessage()]
    assert warnings == [
        f"SIVIN_PASSWORD is shorter than {MIN_SECRET_LENGTH} characters and cannot be "
        "redacted safely from the output."
    ]
    assert short not in caplog.text


def test_console_redacts_every_command(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIVIN_USER", "MeteoData")  # a value that occurs in the output
    result = invoke("ingest", "--dry-run", "--from-dir", str(project.downloads))
    assert result.exit_code == 0, result.output
    assert "MeteoData" not in result.output
    assert REDACTED in result.output
