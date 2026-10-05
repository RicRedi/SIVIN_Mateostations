"""No credential leaves the process: console, run record and derived files (WP-1.7 round 3).

The fake portal's login fields raise a Selenium exception that quotes the typed text, as a
driver error message might. Everything here is SYNTHETIC; no portal is contacted.
"""

from __future__ import annotations

import json
import logging
import runpy
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, quote_plus

import pytest
from selenium.common.exceptions import WebDriverException
from tests.app.fake_portal import credentials, drivers
from tests.app.project import EMPTY_OFFSITE_LOG, Project, make_project, write_synthetic_export
from tests.ingest.portal import conftest as fake
from typer.testing import CliRunner, Result

from sivin.app.factory import ServiceFactory
from sivin.app.outcome import Outcome
from sivin.cli import main as cli
from sivin.cli.main import entry_point
from sivin.cli.state import CliOverrides
from sivin.ingest.portal.credentials import PortalCredentials, Secret
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


def test_unexpected_error_prints_a_redacted_traceback_and_exits_5(
    project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SIVIN_USER", fake.USERNAME)
    monkeypatch.setenv("SIVIN_PASSWORD", fake.PASSWORD)

    def broken(self: ServiceFactory) -> None:
        raise RuntimeError(f"bug while logging in as {fake.USERNAME} with {fake.PASSWORD}")

    monkeypatch.setattr(ServiceFactory, "sensors_check", broken)
    with pytest.raises(SystemExit) as raised:
        entry_point(["sensors", "check"])
    assert raised.value.code == int(Outcome.INTERNAL_ERROR) == 5
    captured = capsys.readouterr()
    assert "Traceback (most recent call last)" in captured.err
    assert f"RuntimeError: bug while logging in as {REDACTED} with {REDACTED}" in captured.err
    for secret in (fake.USERNAME, fake.PASSWORD):
        assert secret not in captured.err
        assert secret not in captured.out


def test_entry_point_passes_normal_exit_codes(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        entry_point(["sensors", "check"])
    assert raised.value.code == 0
    assert "Sensor registry:" in capsys.readouterr().out


def test_python_dash_m_runs_the_entry_point() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "sivin", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("sivin ")


TRICKY_PASSWORD = "pw\\\"q'é€ x-42"
"""SYNTHETIC password with a backslash, both quote kinds, non-ASCII characters and a space."""

TRICKY_USER = 'op"\\é-user'
"""SYNTHETIC user name with a double quote, a backslash and a non-ASCII character."""

LEAK_FORMS: dict[str, Callable[[str], str]] = {
    "plain": lambda text: text,
    "repr": repr,
    "json": json.dumps,
    "json-unicode": lambda text: json.dumps(text, ensure_ascii=False),
    "char-list": lambda text: str({"value": list(text)}),
    "json-char-list": lambda text: json.dumps({"value": list(text)}),
    "url": lambda text: quote(text, safe=""),
    "url-plus": lambda text: quote_plus(text, safe=""),
    "escaped-quotes": lambda text: text.replace("\\", "\\\\").replace('"', '\\"'),
}


def probe_forms(secret: str) -> set[str]:
    """Every form of ``secret`` that must not appear anywhere (quotes stripped)."""
    forms = {LEAK_FORMS[name](secret) for name in LEAK_FORMS}
    forms |= {repr(secret)[1:-1], json.dumps(secret)[1:-1], str(list(secret))[1:-1]}
    return forms


@pytest.mark.parametrize("form", sorted(LEAK_FORMS))
@pytest.mark.parametrize("field", ["username", "password"])
def test_escaped_forms_of_the_credentials_are_redacted(
    project: Project, monkeypatch: pytest.MonkeyPatch, form: str, field: str
) -> None:
    monkeypatch.setenv("SIVIN_USER", TRICKY_USER)
    monkeypatch.setenv("SIVIN_PASSWORD", TRICKY_PASSWORD)
    original = fake.FakeElement.send_keys

    def send_keys(self: fake.FakeElement, text: str) -> None:
        if self.key == field:
            raise WebDriverException(f"cannot type {LEAK_FORMS[form](text)} into <{field}>")
        original(self, text)

    monkeypatch.setattr(fake.FakeElement, "send_keys", send_keys)
    obj = CliOverrides(
        drivers=drivers(),
        credentials=lambda: PortalCredentials(TRICKY_USER, Secret(TRICKY_PASSWORD)),
        clock=lambda: RUN_TIME,
    )
    result = runner.invoke(cli.app, ["run", "--season", "2026"], obj=obj)
    assert result.exit_code == 4, result.output
    assert "Portal session failed: WebDriverException: Message: cannot type" in result.stderr
    files = written_texts(project.root)
    assert any(name.startswith("data/runs/") for name in files)
    assert any(name.startswith("data/derived/") for name in files)
    for secret in (TRICKY_USER, TRICKY_PASSWORD):
        for leaked in probe_forms(secret):
            assert leaked not in result.stdout
            assert leaked not in result.stderr
            for name, text in files.items():
                assert leaked not in text, name


def test_ctrl_c_exits_with_130_without_a_traceback(
    project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SIVIN_PASSWORD", fake.PASSWORD)

    def interrupted(self: ServiceFactory) -> None:
        raise KeyboardInterrupt(fake.PASSWORD)

    monkeypatch.setattr(ServiceFactory, "sensors_check", interrupted)
    with pytest.raises(SystemExit) as raised:
        entry_point(["sensors", "check"])
    assert raised.value.code == 130
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert fake.PASSWORD not in captured.err + captured.out


def test_dunder_main_calls_the_entry_point(
    project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["sivin", "sensors", "check"])
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("sivin", run_name="__main__", alter_sys=True)
    assert raised.value.code == 0
    assert "Sensor registry:" in capsys.readouterr().out
