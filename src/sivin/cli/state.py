"""State of one ``sivin`` invocation: the global options and the lazily built services.

The heavy packages (pandas, the subsystems) are imported here, inside the methods, and only
when a command needs them, so ``sivin --version`` and ``sivin --help`` start instantly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sivin.app.factory import ServiceFactory
    from sivin.config import SivinConfig
    from sivin.ingest.portal.credentials import PortalCredentials
    from sivin.ingest.portal.driver import WebDriverFactory
    from sivin.ingest.portal.settings import PortalSettings
    from sivin.redaction import SecretRedactor

logger = logging.getLogger(__name__)


def protect_secrets() -> SecretRedactor:
    """Build the redactor of the credentials in the environment and install it everywhere.

    The same redactor serves the log handlers and the console (and, through the
    :class:`~sivin.app.factory.ServiceFactory`, the run record and the derived files). A
    credential shorter than :data:`~sivin.redaction.MIN_SECRET_LENGTH` cannot be redacted
    safely; one warning names its variable, never its value.

    Returns
    -------
    SecretRedactor
        The installed redactor.
    """
    from sivin.cli.console import console
    from sivin.logging_setup import install_redactor
    from sivin.redaction import MIN_SECRET_LENGTH, SecretRedactor

    redactor = SecretRedactor.from_environment()
    install_redactor(redactor)
    console.use(redactor)
    for name in redactor.unredactable:
        logger.warning(
            "%s is shorter than %d characters and cannot be redacted safely from the output.",
            name,
            MIN_SECRET_LENGTH,
        )
    return redactor


@dataclass(frozen=True)
class CliOverrides:
    """Collaborators the tests inject through ``CliRunner.invoke(..., obj=CliOverrides(...))``.

    Attributes
    ----------
    drivers : callable or None
        Builds the browser factory (a fake portal in tests); the browser registry if ``None``.
    credentials : callable or None
        Returns the portal credentials; from the environment if ``None``.
    clock : callable or None
        Current time (aware); the system clock if ``None``.
    """

    drivers: Callable[[PortalSettings], WebDriverFactory] | None = None
    credentials: Callable[[], PortalCredentials] | None = None
    clock: Callable[[], datetime] | None = None


@dataclass
class CliState:
    """Global options of one invocation and the services built from them.

    Attributes
    ----------
    config_file : pathlib.Path or None
        ``--config``; ``config/sivin.yaml`` of the project when ``None``.
    overrides : CliOverrides
        Injected collaborators (tests only).
    """

    config_file: Path | None = None
    overrides: CliOverrides = field(default_factory=CliOverrides)
    _services: ServiceFactory | None = field(default=None, init=False, repr=False)

    def services(self) -> ServiceFactory:
        """Return the services of the project (built once).

        Finds the project, loads the configuration and ``.env`` (never overriding variables
        that are already set).

        Returns
        -------
        ServiceFactory
            The services.

        Raises
        ------
        sivin.app.outcome.SetupError
            Outside a project, or with an invalid configuration.
        """
        if self._services is None:
            from sivin.app.environment import DotEnvLoader
            from sivin.app.factory import ServiceFactory
            from sivin.app.workspace import Workspace

            workspace = Workspace.open(self.config_file)
            DotEnvLoader(workspace.paths.root).load()
            redactor = protect_secrets()
            self._services = ServiceFactory(
                workspace,
                drivers=self.overrides.drivers,
                credentials=self.overrides.credentials,
                clock=self.overrides.clock,
                redactor=redactor,
            )
        return self._services

    def config(self) -> SivinConfig:
        """Return the configuration for ``config show``; the defaults outside a project.

        Returns
        -------
        SivinConfig
            The resolved configuration of ``--config``, of the project, or the defaults.

        Raises
        ------
        sivin.app.outcome.SetupError
            If the configuration file is invalid.
        """
        from sivin.app.outcome import SetupError
        from sivin.app.workspace import ProjectNotFoundError, Workspace
        from sivin.config import ConfigError, SivinConfig, load_config

        if self.config_file is not None:
            try:
                return load_config(self.config_file)
            except ConfigError as error:
                raise SetupError(str(error)) from error
        try:
            return Workspace.open().config
        except ProjectNotFoundError:
            logger.info("Not inside the project; using the default configuration.")
            return SivinConfig()

    @staticmethod
    def schema_text(markdown: bool) -> str:
        """Return the JSON schema or the Markdown key reference of the configuration.

        Parameters
        ----------
        markdown : bool
            The Markdown reference instead of the JSON schema.

        Returns
        -------
        str
            The text, ending with a line break.
        """
        from sivin.config.schema import ConfigReference, ConfigSchema

        return ConfigReference().markdown() if markdown else ConfigSchema().text()
