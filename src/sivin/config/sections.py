"""Sections of ``config/sivin.yaml`` that belong to no single subsystem (MIGRATION_PLAN §1.3).

The subsystem sections (``registry``, ``offsite_log``, ``ingest.*``, ``storage``, ``quality``,
``alignment``) are the settings models of their packages; :class:`IngestConfig` groups the three
ingest models. Every model is frozen and rejects unknown keys.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from sivin.core.daily import DEFAULT_AUXILIARY_EXCLUDE
from sivin.core.defaults import (
    DEFAULT_MIN_DAILY_COVERAGE,
    DEFAULT_MIN_SEASON_COVERAGE,
    DEFAULT_SAMPLING_INTERVAL_S,
    DEFAULT_TIMEZONE,
)
from sivin.core.flags import QcFlag
from sivin.ingest.parsers.columns import ParserSettings
from sivin.ingest.portal.settings import PortalSettings
from sivin.ingest.validation import ValidationSettings


class Section(BaseModel):
    """Base of the project's own configuration sections: frozen, unknown keys rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PathsConfig(Section):
    """Locations of data and outputs, relative to the project root."""

    data_dir: Path = Field(
        Path("data"), description="Measurement store directory (path, relative to the root)."
    )
    derived_dir: Path = Field(
        Path("data/derived"),
        description=(
            "Derived data written by sivin qc and sivin indices: events/<sensor_id>.json and "
            "indices/<season>.json (path, relative to the root; MIGRATION_PLAN §2.5)."
        ),
    )
    quarantine_dir: Path = Field(
        Path("data/quarantine"),
        description=(
            "Rejected export files with their validation report as JSON (path, relative to "
            "the root; MIGRATION_PLAN §2.7)."
        ),
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


class TimeConfig(Section):
    """Time zones and sampling, shared by every subsystem.

    The configuration copies these values into the subsystem settings that have their own
    field for them (see :class:`~sivin.config.shared.SharedValues`), so each is set once here.
    """

    source_timezone: str = Field(
        DEFAULT_TIMEZONE,
        description=(
            "IANA zone of the wall-clock timestamps in the provider's exports; the portal "
            "exports local time (owner decision Q2, 2026-10-05). Also sets "
            "ingest.parsers.source_timezone."
        ),
    )
    display_timezone: str = Field(
        DEFAULT_TIMEZONE,
        description=(
            "IANA zone for display and for local calendar days of daily aggregates. Also sets "
            "quality.deployment.display_timezone."
        ),
    )
    expected_interval_s: float = Field(
        DEFAULT_SAMPLING_INTERVAL_S,
        gt=0,
        description=(
            "Nominal sampling interval in seconds; 1830 s is the median step of the first real "
            "export (sensor 77799986, 2025-07-30 to 2026-03-01, MIGRATION_PLAN §0.6.1), the "
            "legacy configs estimated 1825 s. Used for daily coverage and set into every "
            "subsystem with its own interval field (ingest.parsers, the sampling check, the "
            "aligner, the sample durations of the indices)."
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


class QuarantineMode(StrEnum):
    """What ``sivin ingest`` does with a rejected export file."""

    COPY = "copy"
    """Copy it into the quarantine directory; the original stays where it is."""
    MOVE = "move"
    """Move it into the quarantine directory."""


class IngestConfig(Section):
    """Downloading, parsing and validating exports (WP-1.2, WP-1.3)."""

    portal: PortalSettings = Field(
        default_factory=PortalSettings,
        description="Portal client (URL, names, selectors, timeouts, download directory).",
    )
    parsers: ParserSettings = Field(
        default_factory=ParserSettings,
        description="Export parsers (column aliases, time zone, order detection).",
    )
    validation: ValidationSettings = Field(
        default_factory=ValidationSettings,
        description="Thresholds of the input validation (gross bounds, shares, row counts).",
    )
    quarantine_mode: QuarantineMode = Field(
        QuarantineMode.COPY,
        description=(
            "'copy' (default: the original file stays untouched) or 'move' a rejected export "
            "into paths.quarantine_dir (no unit)."
        ),
    )
    file_patterns: tuple[str, ...] = Field(
        ("*.csv", "*.xlsx"),
        min_length=1,
        description=(
            "Glob patterns (no unit) of the export files sivin ingest --from-dir picks up; "
            "browser leftovers (*.crdownload) never match."
        ),
    )


class AnalyticsConfig(Section):
    """Data-completeness rules, sample exclusion and parameters of the climate indices."""

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
    auxiliary_exclude_mask: StrictInt = Field(
        DEFAULT_AUXILIARY_EXCLUDE,
        ge=0,
        description=(
            "QcFlag bits (integer bit mask, dimensionless) that exclude a sample from the "
            "daily precipitation sum and minimum battery voltage (WP-1.9). Default "
            "PRE_DEPLOYMENT|MANUAL_EXCLUDE = 288: only 'not a vineyard measurement'."
        ),
    )
    indices: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Parameters per index id (keys and units as in each index's parameter model, see "
            "docs/indices/<id>.md); omitted keys take their defaults. 'gsr' also accepts "
            "'preset: <cultivar>' (GSR_CULTIVAR_PRESETS) instead of 'targets'. Resolved: every "
            "registered index with all its parameters."
        ),
    )

    @field_validator("exclude_mask", "auxiliary_exclude_mask")
    @classmethod
    def _known_flags(cls, value: int) -> int:
        unknown = value & ~QcFlag.all_bits()
        if unknown:
            raise ValueError(f"bits {unknown} are not QcFlag values")
        return value
