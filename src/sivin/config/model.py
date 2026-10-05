"""The whole project configuration, ``config/sivin.yaml`` (MIGRATION_PLAN §1.3)."""

from __future__ import annotations

from typing import Any, Self

from pydantic import Field, model_validator

from sivin.alignment.config import AlignmentConfig
from sivin.config.resolver import ConfigResolver
from sivin.config.sections import AnalyticsConfig, IngestConfig, PathsConfig, Section, TimeConfig
from sivin.quality.pipeline import QualityPipelineSettings
from sivin.registry.offsite.settings import OffSiteLogSettings
from sivin.registry.settings import RegistrySettings
from sivin.site.settings import SiteSettings
from sivin.storage.config import StorageConfig


class SivinConfig(Section):
    """The whole project configuration (``config/sivin.yaml``), resolved.

    Every way of building it resolves it first (:class:`~sivin.config.resolver.ConfigResolver`):
    the ``time`` values are written into every subsystem field of the same name, and the
    registry-backed mappings (``quality.check_settings``, ``alignment.params``,
    ``analytics.indices``) are validated and completed with all defaults. So
    ``SivinConfig()`` is the complete default configuration, and a typo anywhere fails with
    its key path.
    """

    paths: PathsConfig = Field(default_factory=PathsConfig, description="File locations.")
    time: TimeConfig = Field(
        default_factory=TimeConfig,
        description="Time zones and the nominal sampling interval, shared by all subsystems.",
    )
    registry: RegistrySettings = Field(
        default_factory=RegistrySettings,
        description="Sensor registry checks (the file is paths.sensors_file).",
    )
    offsite_log: OffSiteLogSettings = Field(
        default_factory=OffSiteLogSettings,
        description="The off-site log (file and the time zone of its local times).",
    )
    ingest: IngestConfig = Field(
        default_factory=IngestConfig, description="Portal download, parsers, validation."
    )
    storage: StorageConfig = Field(
        default_factory=StorageConfig,
        description="Measurement store (the directory is paths.data_dir).",
    )
    quality: QualityPipelineSettings = Field(
        default_factory=QualityPipelineSettings,
        description="Quality-control checks, their settings and the deployment detector.",
    )
    alignment: AlignmentConfig = Field(
        default_factory=AlignmentConfig, description="Time alignment of several sensors."
    )
    analytics: AnalyticsConfig = Field(
        default_factory=AnalyticsConfig,
        description="Completeness rules, exclusion masks and index parameters.",
    )
    site: SiteSettings = Field(
        default_factory=SiteSettings,
        description=(
            "Static site data for the web portal (sivin build-site, written to "
            "<paths.site_dir>/data; docs/site.md)."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _resolve(cls, data: Any) -> Any:
        return ConfigResolver().resolve(cls, data)

    @classmethod
    def default(cls) -> Self:
        """Return the configuration with all defaults (resolved).

        Returns
        -------
        SivinConfig
            Default configuration.
        """
        return cls()
