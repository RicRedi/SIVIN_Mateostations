"""Project configuration: ``config/sivin.yaml`` as frozen pydantic models (MIGRATION_PLAN §1.3).

Every section is frozen and rejects unknown keys, so a typo fails at start-up with the path of
the offending key. Paths are relative to the project root (see :class:`~sivin.paths.ProjectPaths`).
Secrets never appear here; they come from the environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator

from sivin.core.defaults import (
    DEFAULT_MIN_DAILY_COVERAGE,
    DEFAULT_MIN_SEASON_COVERAGE,
    DEFAULT_SAMPLING_INTERVAL_S,
    DEFAULT_TIMEZONE,
)
from sivin.core.flags import QcFlag

DEFAULT_CONFIG_FILE: Final = Path("config/sivin.yaml")
"""Location of the configuration file, relative to the project root."""


class ConfigError(ValueError):
    """Raised when the configuration file cannot be read or is invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PathsConfig(_Section):
    """Locations of data and outputs, relative to the project root."""

    data_dir: Path = Field(
        Path("data"), description="Measurement store directory (path, relative to the root)."
    )
    site_dir: Path = Field(
        Path("site"), description="Generated static site data directory (path, relative)."
    )
    sensors_file: Path = Field(
        Path("sensors/sensors.geojson"),
        description="Sensor registry, GeoJSON FeatureCollection (path, relative to the root).",
    )
    output_dir: Path = Field(
        Path("vystupy"), description="Plots and other outputs for people (path, relative)."
    )


class TimeConfig(_Section):
    """Time zones and sampling."""

    source_timezone: str = Field(
        DEFAULT_TIMEZONE,
        description=(
            "IANA zone of the timestamps in the provider's exports (wall-clock time). "
            "Not yet confirmed by a real export (owner question Q2)."
        ),
    )
    display_timezone: str = Field(
        DEFAULT_TIMEZONE,
        description="IANA zone for display and for local calendar days of daily aggregates.",
    )
    expected_interval_s: float = Field(
        DEFAULT_SAMPLING_INTERVAL_S,
        gt=0,
        description=(
            "Nominal sampling interval in seconds; 1830 s is the median step of the first real "
            "export (sensor 77799986, 2025-07-30 to 2026-03-01, MIGRATION_PLAN §0.6.1), the "
            "legacy configs estimated 1825 s. Used for daily coverage."
        ),
    )

    @field_validator("source_timezone", "display_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA time zone {value!r}") from error
        return value


class AnalyticsConfig(_Section):
    """Data-completeness rules and sample exclusion for climate indices."""

    min_daily_coverage: float = Field(
        DEFAULT_MIN_DAILY_COVERAGE,
        ge=0.0,
        le=1.0,
        description=(
            "Share of a day (0-1, dimensionless) covered by valid samples for the day to count "
            "as complete. Project default, to be tuned on real data."
        ),
    )
    min_season_coverage: float = Field(
        DEFAULT_MIN_SEASON_COVERAGE,
        ge=0.0,
        le=1.0,
        description=(
            "Share of complete days in an index period (0-1, dimensionless) for a complete "
            "index result. Project default, to be tuned on real data."
        ),
    )
    exclude_mask: StrictInt = Field(
        int(QcFlag.DEFAULT_EXCLUDE),
        ge=0,
        description=(
            "QcFlag bits (integer bit mask, dimensionless) that exclude a sample from indices. "
            "Default: MISSING|OUT_OF_RANGE|SPIKE|STUCK|PRE_DEPLOYMENT|MANUAL_EXCLUDE = 311."
        ),
    )

    @field_validator("exclude_mask")
    @classmethod
    def _known_flags(cls, value: int) -> int:
        unknown = value & ~QcFlag.all_bits()
        if unknown:
            raise ValueError(f"bits {unknown} are not QcFlag values")
        return value


class SivinConfig(_Section):
    """The whole project configuration (``config/sivin.yaml``)."""

    paths: PathsConfig = Field(default_factory=PathsConfig, description="File locations.")
    time: TimeConfig = Field(default_factory=TimeConfig, description="Time zones and sampling.")
    analytics: AnalyticsConfig = Field(
        default_factory=AnalyticsConfig, description="Completeness rules for climate indices."
    )

    @classmethod
    def default(cls) -> Self:
        """Return the configuration with all defaults.

        Returns
        -------
        SivinConfig
            Default configuration.
        """
        return cls()


def load_config(path: Path) -> SivinConfig:
    """Load and validate a YAML configuration file.

    Missing sections and keys take their defaults; an empty file gives the defaults.

    Parameters
    ----------
    path : pathlib.Path
        The YAML file.

    Returns
    -------
    SivinConfig
        The validated configuration.

    Raises
    ------
    ConfigError
        If the file cannot be read, is not valid YAML, is not a mapping, or violates the
        schema. The message names the path of every offending key, e.g. ``analytics.min_cov``.
    """
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigError(f"Cannot read configuration {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"Configuration {path} is not valid YAML: {error}") from error
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration {path} must be a mapping, got {type(raw).__name__}.")
    try:
        return SivinConfig.model_validate(raw)
    except ValidationError as error:
        problems = "\n".join(
            f"  {'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors()
        )
        raise ConfigError(f"Invalid configuration {path}:\n{problems}") from error
