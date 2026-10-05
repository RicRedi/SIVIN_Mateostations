"""Download the exports of all (or selected) sensors from the data provider's portal.

This module imports Selenium (through :mod:`sivin.ingest.portal.session`); it needs the
``ingest`` extra and is imported only when a command fetches.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from selenium.common.exceptions import WebDriverException

from sivin.app.outcome import Outcome, SourceUnavailableError
from sivin.core.ids import SensorId
from sivin.ingest.portal.client import PortalClient
from sivin.ingest.portal.credentials import PASSWORD_ENV_VAR, USER_ENV_VAR, PortalCredentials
from sivin.ingest.portal.driver import WebDriverFactory
from sivin.ingest.portal.errors import MissingCredentialsError, PortalError
from sivin.ingest.portal.models import SessionResult
from sivin.ingest.portal.session import PortalSession
from sivin.ingest.portal.settings import PortalSettings
from sivin.redaction import SecretRedactor

logger = logging.getLogger(__name__)

CredentialsSource = Callable[[], PortalCredentials]
"""Returns the portal credentials (from the environment); raises
:class:`~sivin.ingest.portal.errors.MissingCredentialsError` when they are not set."""

DriverFactoryBuilder = Callable[[PortalSettings], WebDriverFactory]
"""Builds the browser factory for the settings (the registry of ``ingest.portal.browser`` by
default; tests inject a fake browser)."""


@dataclass(frozen=True)
class FetchReport:
    """Outcome of :meth:`FetchService.fetch`.

    Attributes
    ----------
    result : SessionResult
        Downloaded files and failed devices.
    redactor : SecretRedactor
        Redacts the credentials in the failure texts.
    """

    result: SessionResult
    redactor: SecretRedactor = field(default_factory=SecretRedactor)

    @property
    def files(self) -> tuple[Path, ...]:
        """The downloaded export files."""
        return self.result.files

    @property
    def failures(self) -> tuple[str, ...]:
        """One message per device that was not downloaded."""
        return tuple(
            self.redactor.redact(f"fetch {item.device}: {item.reason}")
            for item in self.result.failures
        )

    @property
    def outcome(self) -> Outcome:
        """:attr:`Outcome.PARTIAL_FAILURE` if any device failed."""
        return Outcome.of(self.failures)


class FetchService:
    """Log in to the portal and download one export per device.

    Parameters
    ----------
    settings : PortalSettings
        Portal settings with absolute paths (``resolved_against`` the project root).
    credentials : CredentialsSource
        Returns the credentials; called only when fetching.
    drivers : DriverFactoryBuilder
        Builds the browser factory for ``settings``.
    redactor : SecretRedactor, optional
        The process's redactor; the credentials actually used are added to it, so no error
        text of this service contains them (exception messages from Selenium included).
    """

    __slots__ = ("_credentials", "_drivers", "_redactor", "_settings")

    def __init__(
        self,
        settings: PortalSettings,
        credentials: CredentialsSource,
        drivers: DriverFactoryBuilder,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self._redactor = redactor if redactor is not None else SecretRedactor()
        self._settings = settings
        self._credentials = credentials
        self._drivers = drivers

    @property
    def settings(self) -> PortalSettings:
        """The portal settings used."""
        return self._settings

    def fetch(self, sensors: Collection[SensorId] | None = None) -> FetchReport:
        """Download the exports.

        Parameters
        ----------
        sensors : collection of SensorId, optional
            Sensors to download; every device the portal lists when omitted.

        Returns
        -------
        FetchReport
            Files and per-device failures (one failed device never stops the others).

        Raises
        ------
        SourceUnavailableError
            If the credentials are missing, the browser cannot start, the login fails or the
            device list cannot be read. The message never contains the credentials.
        """
        try:
            credentials = self._credentials()
        except MissingCredentialsError as error:
            raise SourceUnavailableError(self._redactor.redact(str(error))) from None
        redactor = self._redactor.including(
            {
                USER_ENV_VAR: credentials.username,
                PASSWORD_ENV_VAR: credentials.password.reveal(),
            }
        )
        self._settings.download_dir.mkdir(parents=True, exist_ok=True)
        client = PortalClient(self._settings, credentials, self._drivers(self._settings))
        try:
            result = PortalSession(client).run(sensors)
        except (PortalError, WebDriverException, OSError) as error:
            text = redactor.redact(f"Portal session failed: {type(error).__name__}: {error}")
            raise SourceUnavailableError(text) from None
        return self._report(result, redactor)

    def _report(self, result: SessionResult, redactor: SecretRedactor) -> FetchReport:
        logger.info(
            "Fetched %d export(s) into %s; %d device(s) failed.",
            len(result.downloads),
            self._settings.download_dir,
            len(result.failures),
        )
        return FetchReport(result, redactor)


class PortalExports:
    """Export source of ``sivin run``: download from the portal.

    Parameters
    ----------
    service : FetchService
        The portal download.
    """

    __slots__ = ("_service",)

    def __init__(self, service: FetchService) -> None:
        self._service = service

    def exports(
        self, sensors: Sequence[SensorId] | None
    ) -> tuple[tuple[Path, ...], tuple[str, ...]]:
        """Download the exports (see :class:`~sivin.app.run.ExportSource`).

        Parameters
        ----------
        sensors : sequence of SensorId, optional
            Sensors to download; all listed devices when omitted.

        Returns
        -------
        tuple
            ``(files, failures)``.
        """
        report = self._service.fetch(sensors)
        return report.files, report.failures
