"""``sivin report`` (WP-4.1) on a temporary project: formats, selection, exit codes, secrets.

The exports, run records and events are SYNTHETIC; no portal is contacted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.app.fake_portal import credentials, drivers
from tests.app.project import (
    EMPTY_OFFSITE_LOG,
    OUTDOOR_SENSOR,
    Project,
    make_project,
    write_synthetic_export,
)
from typer.testing import CliRunner, Result

from sivin.app.summary_formats import NO_RECORD, markdown_text
from sivin.cli import main as cli
from sivin.cli.state import CliOverrides
from sivin.redaction import REDACTED
from sivin.storage.runlog import RunLog, RunRecord

RUN_TIME = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)

SYNTHETIC_PASSWORD = "synthetic_Pa55*word|x"
"""Contains Markdown characters: the Markdown escape must not hide it from the redactor."""

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_global_logging_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pytest's logging configuration (the CLI would reconfigure the root logger)."""
    monkeypatch.setattr(cli, "setup_logging", lambda level: None)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A project after one ``sivin ingest`` of a 2-day SYNTHETIC export (94 rows)."""
    made = make_project(tmp_path / "project", offsite_log=EMPTY_OFFSITE_LOG)
    monkeypatch.chdir(made.root)
    write_synthetic_export(made.downloads, days=2)
    assert invoke("ingest").exit_code == 0
    return made


def invoke(*args: str) -> Result:
    obj = CliOverrides(drivers=drivers(), credentials=credentials, clock=lambda: RUN_TIME)
    return runner.invoke(cli.app, list(args), obj=obj)


class TestReport:
    def test_markdown_of_the_latest_run(self, project: Project) -> None:
        result = invoke("report", "--format", "markdown", "--run", "latest", "--outcome", "0")
        assert result.exit_code == 0, result.output
        # 2 days at 1830 s: floor(172 800 / 1830) = 94 rows, all new.
        assert f"| {OUTDOOR_SENSOR} | 94 | 0 | 0 | 0 |" in result.stdout
        assert "| export files processed | 1 |" in result.stdout
        assert "Outcome: OK (exit code 0). Everything succeeded." in result.stdout
        assert "### Export files\n\n- MeteoData\\_8615620 77678271 (VUT)" in result.stdout

    def test_json_counts_for_the_commit_message(self, project: Project) -> None:
        result = invoke("report", "--format", "json", "--since", RUN_TIME.isoformat())
        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert (document["record"], document["files"], document["new_rows"]) == (True, 1, 94)

    def test_text_is_the_default(self, project: Project) -> None:
        result = invoke("report")
        assert result.exit_code == 0, result.output
        assert result.stdout.startswith("SIVIN PIPELINE RUN\n")

    def test_since_after_the_last_run_reports_no_record(self, project: Project) -> None:
        since = (RUN_TIME + timedelta(minutes=1)).isoformat()
        result = invoke("report", "--format", "markdown", "--since", since, "--outcome", "3")
        assert result.exit_code == 0, result.output
        assert NO_RECORD.split(":")[0] in result.stdout
        assert "Outcome: SETUP\\_ERROR (exit code 3)." in result.stdout

    def test_a_given_day_and_warnings(self, project: Project) -> None:
        events = project.root / "data" / "derived" / "events"
        events.mkdir(parents=True, exist_ok=True)
        (events / f"{OUTDOOR_SENSOR}.json").write_text(
            json.dumps(
                {
                    "sensor_id": OUTDOOR_SENSOR,
                    "status": "ok",
                    "events": [
                        {
                            "type": "low_battery",
                            "t": "2026-06-02T00:00:00Z",
                            "t_end": "2026-06-02T06:00:00Z",
                            "severity": "warning",
                            "detail": "battery below 3.4 V",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = invoke("report", "--format", "markdown", "--run", "2026-10-05")
        assert result.exit_code == 0, result.output
        assert (
            f"| {OUTDOOR_SENSOR} | low\\_battery | 1 | 2026-06-02T00:00:00Z .. "
            "2026-06-02T06:00:00Z | battery below 3.4 V |"
        ) in result.stdout

    @pytest.mark.parametrize(
        "args",
        [
            ("--format", "html"),
            ("--run", "yesterday"),
            ("--since", "not a time"),
        ],
    )
    def test_invalid_options_exit_with_2(self, project: Project, args: tuple[str, ...]) -> None:
        assert invoke("report", *args).exit_code == 2

    def test_outside_a_project_exits_with_3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert invoke("report").exit_code == 3

    def test_credentials_are_redacted(
        self, project: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIVIN_PASSWORD", SYNTHETIC_PASSWORD)
        failure = f"fetch: login rejected input {SYNTHETIC_PASSWORD!r}"
        RunLog(project.root / "data").append(
            RunRecord(RUN_TIME, RUN_TIME + timedelta(seconds=5), failures=(failure,))
        )
        for output_format, shown in (("markdown", markdown_text(REDACTED)), ("text", REDACTED)):
            result = invoke("report", "--format", output_format)
            assert result.exit_code == 0, result.output
            assert SYNTHETIC_PASSWORD not in result.output
            assert markdown_text(SYNTHETIC_PASSWORD) not in result.output
            assert f"fetch: login rejected input '{shown}'" in result.stdout
