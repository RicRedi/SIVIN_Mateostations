"""Workspace, exit codes, the .env loader and the sensor catalog."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.app.project import EMPTY_OFFSITE_LOG, Project, make_project

from sivin.app.catalog import SensorsCheck
from sivin.app.environment import DotEnvLoader
from sivin.app.factory import ServiceFactory
from sivin.app.outcome import Outcome, SetupError
from sivin.app.workspace import Workspace
from sivin.config import SivinConfig


class TestOutcome:
    def test_of_and_worst(self) -> None:
        assert Outcome.of([]) is Outcome.OK
        assert Outcome.of(["x"]) is Outcome.PARTIAL_FAILURE
        assert Outcome.worst([Outcome.OK, Outcome.SETUP_ERROR, Outcome.PARTIAL_FAILURE]) is (
            Outcome.SETUP_ERROR
        )
        assert Outcome.worst([]) is Outcome.OK
        assert [int(o) for o in Outcome] == [0, 1, 2, 3]


class TestWorkspace:
    def test_paths_are_resolved_against_the_root(self, project: Project) -> None:
        workspace = Workspace.open(start=project.root / "sensors")
        root = project.root
        assert workspace.paths.root == root
        assert workspace.data_dir == root / "data"
        assert workspace.events_dir == root / "data" / "derived" / "events"
        assert workspace.indices_dir == root / "data" / "derived" / "indices"
        assert workspace.quarantine_dir == root / "data" / "quarantine"
        assert workspace.sensors_file == root / "sensors" / "sensors.geojson"
        assert workspace.offsite_log_file == root / "sensors" / "offsite_log.yaml"
        assert workspace.download_dir == root / "data" / "downloads"

    def test_without_config_file_the_defaults_apply(self, project: Project) -> None:
        (project.root / "config" / "sivin.yaml").unlink()
        assert Workspace.open(start=project.root).config == SivinConfig()

    def test_explicit_config_file(self, project: Project, tmp_path: Path) -> None:
        other = tmp_path / "other.yaml"
        other.write_text("paths:\n  data_dir: elsewhere\n", encoding="utf-8")
        workspace = Workspace.open(other, start=project.root)
        assert workspace.data_dir == project.root / "elsewhere"

    def test_invalid_config_is_a_setup_error(self, project: Project) -> None:
        project.write_config("paths:\n  data_dri: x\n")
        with pytest.raises(SetupError, match=r"paths\.data_dri: Extra inputs"):
            Workspace.open(start=project.root)

    def test_outside_a_project(self, tmp_path: Path) -> None:
        outside = tmp_path / "nowhere"
        outside.mkdir()
        with pytest.raises(SetupError, match=r"No pyproject\.toml"):
            Workspace.open(start=outside)

    def test_config_file_inside_a_project_finds_the_root(
        self, project: Project, tmp_path: Path
    ) -> None:
        outside = tmp_path / "nowhere"
        outside.mkdir()
        config_file = project.root / "config" / "sivin.yaml"
        assert Workspace.open(config_file, start=outside).paths.root == project.root
        stray = tmp_path / "stray.yaml"
        stray.write_text("", encoding="utf-8")
        with pytest.raises(SetupError):
            Workspace.open(stray, start=outside)


class TestDotEnv:
    def test_loads_without_overriding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIVIN_TEST_KEPT", "from-environment")
        monkeypatch.delenv("SIVIN_TEST_NEW", raising=False)
        (tmp_path / ".env").write_text(
            "SIVIN_TEST_KEPT=from-file\nSIVIN_TEST_NEW=synthetic\n", encoding="utf-8"
        )
        loader = DotEnvLoader(tmp_path)
        assert loader.path == tmp_path / ".env"
        assert loader.load() is True
        assert os.environ["SIVIN_TEST_KEPT"] == "from-environment"
        assert os.environ["SIVIN_TEST_NEW"] == "synthetic"
        monkeypatch.delenv("SIVIN_TEST_NEW")

    def test_missing_file(self, tmp_path: Path) -> None:
        assert DotEnvLoader(tmp_path).load() is False


class TestCatalog:
    def test_loads_registry_and_log_once(self, factory: ServiceFactory) -> None:
        catalog = factory.catalog()
        assert len(catalog.registry) == 4
        assert len(catalog.offsite_log) == 1
        assert factory.catalog() is catalog

    def test_sensors_check_of_valid_files(self, factory: ServiceFactory) -> None:
        report = factory.sensors_check().run()
        assert report.outcome is Outcome.OK
        assert report.problem is None
        assert report.catalog is not None

    def test_invalid_off_site_log(self, tmp_path: Path) -> None:
        project = make_project(
            tmp_path / "p",
            offsite_log=(
                "entries:\n  - sensor: '11111111'\n    from: '2026-01-01 10:00'\n"
                "    to: open\n    reason: office\n"
            ),
        )
        report = SensorsCheck(
            ServiceFactory(Workspace.open(start=project.root)).catalog_loader()
        ).run()
        assert report.outcome is Outcome.PARTIAL_FAILURE
        assert report.catalog is None
        assert report.problem is not None
        assert report.problem.startswith(f"Off-site log {project.root / 'sensors'}")
        assert "11111111" in report.problem

    def test_invalid_registry(self, tmp_path: Path) -> None:
        project = make_project(tmp_path / "p", offsite_log=EMPTY_OFFSITE_LOG)
        (project.root / "sensors" / "sensors.geojson").write_text("{", encoding="utf-8")
        factory = ServiceFactory(Workspace.open(start=project.root))
        with pytest.raises(SetupError, match="Sensor registry"):
            factory.catalog()


def test_json_writer_is_stable_and_writes_null_for_nan(tmp_path: Path) -> None:
    from sivin.app.json_files import JsonFileWriter

    path = tmp_path / "out" / "x.json"
    JsonFileWriter().write(path, {"b": float("nan"), "a": (1, float("inf")), "c": "č", "d": 2})
    assert path.read_text(encoding="utf-8") == (
        '{\n  "b": null,\n  "a": [\n    1,\n    null\n  ],\n  "c": "č",\n  "d": 2\n}\n'
    )


def test_factory_exposes_its_workspace_and_clock(factory: ServiceFactory) -> None:
    from tests.app.conftest import RUN_TIME

    assert factory.clock() == RUN_TIME
    assert factory.workspace.paths.root.name == "project"
