"""Tests of the configuration models and loader."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from sivin.config import (
    AnalyticsConfig,
    ConfigError,
    SivinConfig,
    TimeConfig,
    load_config,
)
from sivin.core.flags import QcFlag
from sivin.paths import ProjectPaths


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "sivin.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults() -> None:
    config = SivinConfig.default()
    assert config.paths.data_dir == Path("data")
    assert config.paths.site_dir == Path("site")
    assert config.paths.sensors_file == Path("sensors/sensors.geojson")
    assert config.paths.output_dir == Path("vystupy")
    assert config.time.source_timezone == "Europe/Prague"
    assert config.time.display_timezone == "Europe/Prague"
    assert config.time.expected_interval_s == 1830.0
    assert config.analytics.min_daily_coverage == 0.9
    assert config.analytics.min_season_coverage == 0.9
    assert config.analytics.exclude_mask == int(QcFlag.DEFAULT_EXCLUDE) == 311


def test_committed_yaml_mirrors_the_defaults() -> None:
    root = ProjectPaths.discover(Path(__file__).parent)
    assert load_config(root.resolve("config/sivin.yaml")) == SivinConfig.default()


def test_every_field_has_a_description() -> None:
    for model in (SivinConfig, *(f.annotation for f in SivinConfig.model_fields.values())):
        assert isinstance(model, type)
        for name, field in model.model_fields.items():  # type: ignore[attr-defined]
            assert field.description, f"{model.__name__}.{name} has no description"


def test_partial_file_keeps_other_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, "analytics:\n  min_daily_coverage: 0.75\n"))
    assert config.analytics.min_daily_coverage == 0.75
    assert config.time == TimeConfig()


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, "")) == SivinConfig.default()


@pytest.mark.parametrize(
    ("text", "key_path"),
    [
        ("analytics:\n  min_daily_coverag: 0.8\n", "analytics.min_daily_coverag"),
        ("pahts:\n  data_dir: x\n", "pahts"),
        ("analytics:\n  min_daily_coverage: 1.5\n", "analytics.min_daily_coverage"),
        ("time:\n  display_timezone: Europe/Brno\n", "time.display_timezone"),
        ("time:\n  expected_interval_s: 0\n", "time.expected_interval_s"),
        ("analytics:\n  exclude_mask: 1024\n", "analytics.exclude_mask"),
        ("analytics:\n  exclude_mask: true\n", "analytics.exclude_mask"),
    ],
)
def test_invalid_values_name_the_key_path(tmp_path: Path, text: str, key_path: str) -> None:
    with pytest.raises(ConfigError, match=rf"(?m)^  {key_path}: "):
        load_config(write(tmp_path, text))


def test_unreadable_or_malformed_files(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Cannot read"):
        load_config(tmp_path / "missing.yaml")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(write(tmp_path, "paths: [unclosed\n"))
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(write(tmp_path, "- a\n- b\n"))


def test_models_are_frozen() -> None:
    config = SivinConfig.default()
    with pytest.raises(ValidationError):
        config.analytics.min_daily_coverage = 0.5  # type: ignore[misc]
    with pytest.raises(ValidationError):
        AnalyticsConfig(unknown=1)  # type: ignore[call-arg]


def test_config_and_cli_do_not_import_pandas() -> None:
    """The configuration layer must not pull in the analytics stack (pandas)."""
    code = "import sys, sivin.cli; print('pandas' in sys.modules)"
    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert output.strip() == "False"
