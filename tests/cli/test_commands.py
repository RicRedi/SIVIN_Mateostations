"""The ``sivin`` commands on a temporary project (CliRunner; fake portal, SYNTHETIC exports)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.app.fake_portal import credentials, drivers
from tests.app.project import (
    EMPTY_OFFSITE_LOG,
    OUTDOOR_SENSOR,
    REAL_SENSOR,
    Project,
    make_project,
    write_synthetic_export,
)
from tests.ingest.portal.conftest import PASSWORD
from typer.testing import CliRunner, Result

from sivin.cli import main as cli
from sivin.cli.state import CliOverrides
from sivin.ingest.portal.errors import MissingCredentialsError

RUN_TIME = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_global_logging_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pytest's logging configuration (the CLI would reconfigure the root logger)."""
    monkeypatch.setattr(cli, "setup_logging", lambda level: None)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A project; the commands run in its root directory."""
    made = make_project(tmp_path / "project")
    monkeypatch.chdir(made.root)
    return made


def invoke(*args: str, overrides: CliOverrides | None = None) -> Result:
    obj = overrides or CliOverrides(
        drivers=drivers(), credentials=credentials, clock=lambda: RUN_TIME
    )
    return runner.invoke(cli.app, list(args), obj=obj)


def no_credentials() -> None:
    raise MissingCredentialsError("Portal credentials missing: set SIVIN_USER and SIVIN_PASSWORD.")


class TestSensors:
    def test_valid_files(self, project: Project) -> None:
        result = invoke("sensors", "check")
        assert result.exit_code == 0, result.output
        assert "Sensor registry: 4 sensor(s), 4 active." in result.output
        assert "Off-site log: 1 period(s)." in result.output

    def test_invalid_log_exits_with_1(self, project: Project) -> None:
        project.write_offsite_log("entries:\n  - sensor: '77678271'\n")
        result = invoke("sensors", "check")
        assert result.exit_code == 1
        assert "Off-site log" in result.output
        assert "entry #1" in result.output

    def test_outside_a_project_exits_with_3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = invoke("sensors", "check")
        assert result.exit_code == 3
        assert "Error: No pyproject.toml" in result.output


class TestFetch:
    def test_downloads_and_never_prints_the_password(self, project: Project) -> None:
        result = invoke("fetch", "--sensor", "8615620 77678271", "--headed")
        assert result.exit_code == 0, result.output
        assert "DOWNLOADED" in result.output
        assert "77678271 (VUT)_20260605_060001.csv" in result.output
        assert PASSWORD not in result.output

    def test_failed_device_exits_with_1(self, project: Project, tmp_path: Path) -> None:
        overrides = CliOverrides(
            drivers=drivers({"8615621 77678272": "no_button"}), credentials=credentials
        )
        result = invoke("fetch", "--download-dir", str(tmp_path / "dl"), overrides=overrides)
        assert result.exit_code == 1
        assert "FAILED fetch 8615621 77678272" in result.output
        assert len(list((tmp_path / "dl").glob("*.csv"))) == 2

    def test_missing_credentials_exit_with_4(self, project: Project) -> None:
        overrides = CliOverrides(drivers=drivers(), credentials=no_credentials)  # type: ignore[arg-type]
        result = invoke("fetch", overrides=overrides)
        assert result.exit_code == 4
        assert "SIVIN_USER" in result.output

    def test_invalid_sensor_name_is_a_usage_error(self, project: Project) -> None:
        result = invoke("fetch", "--sensor", "8271")
        assert result.exit_code == 2


class TestIngest:
    def test_files_and_run_record(self, project: Project) -> None:
        path = project.real_export()
        result = invoke("ingest", str(path))
        assert result.exit_code == 0, result.output
        assert f"IMPORTED {path.name}: 77799986 300 rows (77799986 +300 new" in result.output
        runs = project.root / "data" / "runs" / "2026-10-05.jsonl"
        record = json.loads(runs.read_text(encoding="utf-8"))
        assert record["files"] == [path.name]
        assert record["appends"][REAL_SENSOR]["new_rows"] == 300

    def test_default_directory_and_rejected_file(self, project: Project) -> None:
        write_synthetic_export(project.downloads, days=1)
        (project.downloads / "broken.csv").write_text("Meteo Data;\n", encoding="utf-8")
        result = invoke("ingest")
        assert result.exit_code == 1
        assert "REJECTED broken.csv ->" in result.output
        assert "IMPORTED MeteoData_8615620 77678271 (VUT)_20260605_060000.csv" in result.output

    @pytest.mark.parametrize(
        ("option", "kept"), [([], False), (["--quarantine-mode", "copy"], True)]
    )
    def test_quarantine_mode_of_a_named_file(
        self, project: Project, tmp_path: Path, option: list[str], kept: bool
    ) -> None:
        own = tmp_path / "mine" / "broken.csv"
        own.parent.mkdir()
        own.write_text("Meteo Data;\n", encoding="utf-8")
        result = invoke("ingest", str(own), *option)
        assert result.exit_code == 1
        assert own.exists() is kept
        assert list((project.root / "data" / "quarantine").rglob("broken*.csv"))

    def test_from_dir_dry_run(self, project: Project, tmp_path: Path) -> None:
        directory = tmp_path / "exports"
        write_synthetic_export(directory, days=1)
        result = invoke("ingest", "--from-dir", str(directory), "--dry-run")
        assert result.exit_code == 0, result.output
        assert "VALID MeteoData_8615620 77678271 (VUT)_20260605_060000.csv: 77678271 47 rows" in (
            result.output
        )
        assert "Dry run: nothing was written." in result.output
        assert not (project.root / "data" / "raw").exists()
        assert not (project.root / "data" / "runs").exists()

    def test_nothing_to_ingest(self, project: Project) -> None:
        result = invoke("ingest")
        assert result.exit_code == 0, result.output
        assert "No export files to ingest." in result.output
        assert not (project.root / "data" / "runs").exists()

    def test_warnings_are_listed(self, project: Project) -> None:
        path = write_synthetic_export(project.downloads, days=1)
        text = path.read_text(encoding="utf-8").replace("3,60", "85,0", 1)
        path.write_text(text, encoding="utf-8")
        result = invoke("ingest", str(path))
        assert result.exit_code == 0, result.output
        assert "  WARNING battery-bounds" in result.output


class TestQcIndicesRun:
    def test_qc_with_bounds(self, project: Project) -> None:
        assert invoke("ingest", str(project.real_export())).exit_code == 0
        result = invoke("qc", "--sensor", REAL_SENSOR, "--from", "2026-02-01", "--to", "2026-03-01")
        assert result.exit_code == 0, result.output
        assert result.output.startswith(f"{REAL_SENSOR}: ")
        assert "PRE_DEPLOYMENT" in result.output
        assert "events/77799986.json" in result.output

    def test_qc_reports_sensors_without_data_and_bad_bounds(self, project: Project) -> None:
        result = invoke("qc", "--sensor", OUTDOOR_SENSOR)
        assert result.exit_code == 0, result.output
        assert f"{OUTDOOR_SENSOR}: no stored data" in result.output
        assert invoke("qc", "--from", "2026-06-02", "--to", "2026-06-01").exit_code == 2

    def test_qc_failure_exits_with_1(self, project: Project) -> None:
        bad = project.root / "data" / "raw" / REAL_SENSOR / "2026.csv"
        bad.parent.mkdir(parents=True)
        bad.write_text("broken\n", encoding="utf-8")
        result = invoke("qc")
        assert result.exit_code == 1
        assert f"FAILED qc {REAL_SENSOR}" in result.output

    def test_invalid_off_site_log_stops_qc(self, project: Project) -> None:
        project.write_offsite_log("entries:\n  - sensor: '77678271'\n    from: x\n")
        result = invoke("qc")
        assert result.exit_code == 3
        assert "Off-site log" in result.output

    def test_indices(self, project: Project) -> None:
        assert invoke("ingest", str(write_synthetic_export(project.downloads))).exit_code == 0
        result = invoke("indices", "--season", "2026", "--index", "gst", "-i", "frost")
        assert result.exit_code == 0, result.output
        assert "Season 2026 (data 2025-01-01..2026-12-31)" in result.output
        assert f"{OUTDOOR_SENSOR} gst: " in result.output
        assert f"{OUTDOOR_SENSOR} frost: " in result.output
        assert "indices/2026.json" in result.output

    def test_unknown_index_is_a_usage_error(self, project: Project) -> None:
        result = invoke("indices", "--season", "2026", "--index", "hugin")
        assert result.exit_code == 2
        assert "unknown index hugin" in result.output

    def test_run_with_the_fake_portal(self, project: Project) -> None:
        result = invoke("run", "--sensor", OUTDOOR_SENSOR)
        assert result.exit_code == 0, result.output
        assert "Season 2026" in result.output  # current year of the fixed clock
        assert "Run finished: OK." in result.output
        assert (project.root / "data" / "runs" / "2026-10-05.jsonl").exists()

    def test_run_continues_without_the_portal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = make_project(tmp_path / "p", offsite_log=EMPTY_OFFSITE_LOG)
        monkeypatch.chdir(project.root)
        write_synthetic_export(project.downloads, days=1)
        assert invoke("ingest").exit_code == 0
        overrides = CliOverrides(credentials=no_credentials, clock=lambda: RUN_TIME)  # type: ignore[arg-type]
        result = invoke("run", "--season", "2026", overrides=overrides)
        assert result.exit_code == 4
        assert "FAILED fetch: Portal credentials missing" in result.output
        assert "Run finished: DATA_SOURCE_UNAVAILABLE." in result.output

    def test_run_skip_fetch_dry_run(self, project: Project) -> None:
        write_synthetic_export(project.downloads, days=1)
        result = invoke("run", "--skip-fetch", "--dry-run", "--season", "2026")
        assert result.exit_code == 0, result.output
        assert "VALID " in result.output
        assert not (project.root / "data" / "runs").exists()


def tree_digest(root: Path) -> dict[str, str]:
    """SHA-256 of every file below ``root`` (relative path → digest)."""
    import hashlib

    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestRobustness:
    def test_run_dry_run_never_touches_the_portal_or_the_tree(self, project: Project) -> None:
        write_synthetic_export(project.downloads, days=1)
        assert invoke("ingest").exit_code == 0
        write_synthetic_export(project.downloads, days=2, stamp="20260606_060000")
        calls: list[object] = []

        def forbidden(settings: object) -> object:
            calls.append(settings)
            raise AssertionError("the browser must not start in a dry run")

        overrides = CliOverrides(drivers=forbidden, credentials=credentials, clock=lambda: RUN_TIME)  # type: ignore[arg-type]
        before = tree_digest(project.root)
        result = invoke("run", "--dry-run", overrides=overrides)
        assert result.exit_code == 0, result.output
        assert "Note: fetch skipped in dry-run." in result.output
        assert calls == []
        assert tree_digest(project.root) == before

    def test_empty_store(self, project: Project) -> None:
        result = invoke("qc")
        assert result.exit_code == 0, result.output
        assert "No stored data." in result.output
        result = invoke("indices", "--season", "2026")
        assert result.exit_code == 0, result.output
        assert "No stored data for this season; nothing written." in result.output
        assert not (project.root / "data").exists()

    def test_failed_login_exits_with_4(self, project: Project) -> None:
        from sivin.ingest.portal.credentials import PortalCredentials, Secret

        overrides = CliOverrides(
            drivers=drivers(), credentials=lambda: PortalCredentials("synthetic-user", Secret("x"))
        )
        result = invoke("fetch", overrides=overrides)
        assert result.exit_code == 4
        assert "Portal session failed" in result.output
