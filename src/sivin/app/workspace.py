"""The project a command works on: its root directory and its resolved configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

from sivin.app.outcome import SetupError
from sivin.config import DEFAULT_CONFIG_FILE, ConfigError, SivinConfig, load_config
from sivin.paths import ProjectPaths, ProjectRootNotFoundError

logger = logging.getLogger(__name__)

EVENTS_DIR: Final = "events"
"""Directory below ``paths.derived_dir`` with one QC events file per sensor."""

INDICES_DIR: Final = "indices"
"""Directory below ``paths.derived_dir`` with one indices file per season."""

SITE_DATA_DIR: Final = "data"
"""Directory below ``paths.site_dir`` with the static site data (MIGRATION_PLAN §2.6)."""


class ProjectNotFoundError(SetupError):
    """Raised when the command does not run inside a project (no ``pyproject.toml`` found)."""


@dataclass(frozen=True, slots=True)
class Workspace:
    """The project root and its configuration, with every configured path made absolute.

    Attributes
    ----------
    paths : ProjectPaths
        The project root.
    config : SivinConfig
        The resolved configuration.
    """

    paths: ProjectPaths
    config: SivinConfig

    @classmethod
    def open(cls, config_file: Path | None = None, start: Path | None = None) -> Self:
        """Find the project and load its configuration.

        Parameters
        ----------
        config_file : pathlib.Path, optional
            Configuration file; ``config/sivin.yaml`` of the project when omitted (the
            defaults when that file does not exist).
        start : pathlib.Path, optional
            Where the search for the project root starts; the working directory when omitted.
            When it is outside the project, the directory of ``config_file`` is tried.

        Returns
        -------
        Workspace
            The project.

        Raises
        ------
        ProjectNotFoundError
            If no project root is found.
        SetupError
            If the configuration is invalid.
        """
        paths = _discover(start, config_file)
        target = config_file if config_file is not None else paths.resolve(DEFAULT_CONFIG_FILE)
        if config_file is None and not target.is_file():
            logger.info("%s not found; using the default configuration.", target)
            return cls(paths, SivinConfig())
        try:
            return cls(paths, load_config(target))
        except ConfigError as error:
            raise SetupError(str(error)) from error

    @property
    def data_dir(self) -> Path:
        """Measurement store directory (``paths.data_dir``)."""
        return self.paths.resolve(self.config.paths.data_dir)

    @property
    def events_dir(self) -> Path:
        """QC events per sensor (``<paths.derived_dir>/events``)."""
        return self.paths.resolve(self.config.paths.derived_dir) / EVENTS_DIR

    @property
    def indices_dir(self) -> Path:
        """Index results per season (``<paths.derived_dir>/indices``)."""
        return self.paths.resolve(self.config.paths.derived_dir) / INDICES_DIR

    @property
    def site_data_dir(self) -> Path:
        """Static site data of the web portal (``<paths.site_dir>/data``)."""
        return self.paths.resolve(self.config.paths.site_dir) / SITE_DATA_DIR

    @property
    def quarantine_dir(self) -> Path:
        """Rejected exports (``paths.quarantine_dir``)."""
        return self.paths.resolve(self.config.paths.quarantine_dir)

    @property
    def sensors_file(self) -> Path:
        """The sensor registry (``paths.sensors_file``)."""
        return self.paths.resolve(self.config.paths.sensors_file)

    @property
    def offsite_log_file(self) -> Path:
        """The off-site log (``offsite_log.file``)."""
        return self.paths.resolve(self.config.offsite_log.file)

    @property
    def download_dir(self) -> Path:
        """Where ``sivin fetch`` saves exports (``ingest.portal.download_dir``)."""
        return self.paths.resolve(self.config.ingest.portal.download_dir)


def _discover(start: Path | None, config_file: Path | None) -> ProjectPaths:
    try:
        return ProjectPaths.discover(start)
    except ProjectRootNotFoundError as error:
        if config_file is not None:
            try:
                return ProjectPaths.discover(config_file.resolve().parent)
            except ProjectRootNotFoundError:
                pass
        raise ProjectNotFoundError(str(error)) from error
