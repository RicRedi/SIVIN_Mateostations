"""Project configuration: ``config/sivin.yaml`` as frozen pydantic models (MIGRATION_PLAN §1.3).

Every section is frozen and rejects unknown keys, so a typo fails at start-up with the path of
the offending key. Paths are relative to the project root (see :class:`~sivin.paths.ProjectPaths`).
Secrets never appear here; they come from the environment. The sections of the subsystems are
the settings models of their packages; :class:`SivinConfig` composes them and resolves the
values shared through the ``time`` section (see ``docs/configuration.md``).
"""

from sivin.config.loader import DEFAULT_CONFIG_FILE, ConfigError, describe, load_config
from sivin.config.model import SivinConfig
from sivin.config.sections import (
    AnalyticsConfig,
    IngestConfig,
    PathsConfig,
    QuarantineMode,
    TimeConfig,
)

__all__ = [
    "DEFAULT_CONFIG_FILE",
    "AnalyticsConfig",
    "ConfigError",
    "IngestConfig",
    "PathsConfig",
    "QuarantineMode",
    "SivinConfig",
    "TimeConfig",
    "describe",
    "load_config",
]
