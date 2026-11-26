"""Fetch the data of all (or selected) sensors from the data provider's portal (export or table).

This module imports Selenium (through :mod:`sivin.ingest.portal.session`); it needs the
``ingest`` extra and is imported only when a command fetches.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from selenium.common.exceptions import WebDriverException
from urllib3.exceptions import HTTPError as TransportError

from sivin.app.outcome import Outcome, SourceUnavailableError
from sivin.core.ids import SensorId
from sivin.ingest.portal.client import PortalClient
from sivin.ingest.portal.credentials import PASSWORD_ENV_VAR, USER_ENV_VAR, PortalCredentials
from sivin.ingest.portal.driver import WebDriverFactory
from sivin.ingest.portal.errors import MissingCredentialsError, PortalError
from sivin.ingest.portal.models import SessionResult
from sivin.ingest.portal.session import PortalSession
from sivin.ingest.portal.settings import PortalSettings
from sivin.ingest.portal.sources import (
    LastTimestamps,
    NoStoredData,
    SourceContext,
    device_source_registry,
)
from sivin.redaction import SecretRedactor
from sivin.storage.errors import StoreError
from sivin.storage.store import MeasurementStore

logger = logging.getLogger(__name__)

CredentialsSource = Callable[[], PortalCredentials]
"""Returns the portal credentials (from the environment); raises
:class:`~sivin.ingest.portal.errors.MissingCredentialsError` when they are not set."""

DriverFactoryBuilder = Callable[[PortalSettings], WebDriverFactory]
"""Builds the browser factory for the settings (the registry of ``ingest.portal.browser`` by
default; tests inject a fake browser)."""


class StoreLastTimestamps:
    """The last stored measurement of a sensor, read from the measurement store.

    The table source reads only the rows newer than this (WP-1.10). A store that cannot be
    read gives ``None`` with a WARNING: the whole history is then read, and the store's
    deduplication skips what it already holds.

    Parameters
    ----------
    store : MeasurementStore
        The store the run appends to.
    """

    __slots__ = ("_store",)

    def __init__(self, store: MeasurementStore) -> None:
        self._store = store

    def last_timestamp(self, sensor_id: SensorId) -> datetime | None:
        """Return the newest stored ``timestamp_utc`` of a sensor.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.

        Returns
        -------
        datetime.datetime or None
            Timezone-aware UTC time, or ``None`` when nothing is stored (or the store cannot
            be read).
        """
        try:
            bounds = self._store.time_range(sensor_id)
        except (StoreError, OSError) as error:
            logger.warning(
                "The last stored time of %s is unknown (%s); reading its whole table history.",
                sensor_id,
                error,
            )
            return None
        return None if bounds is None else bounds[1].to_pydatetime()


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
        """The downloaded export files and the files written from the device tables."""
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
    """Log in to the portal and fetch the data of every device.

    Each device is fetched with the sources of ``settings.sources`` in order (by default the
    device table, then the Excel export as the fallback, WP-1.10).

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
    last_timestamps : LastTimestamps, optional
        Last stored measurement per sensor (e.g. :class:`StoreLastTimestamps`); the table
        source reads only newer rows. Without it the table source reads the whole history.
    """

    __slots__ = ("_credentials", "_drivers", "_last_timestamps", "_redactor", "_settings")

    def __init__(
        self,
        settings: PortalSettings,
        credentials: CredentialsSource,
        drivers: DriverFactoryBuilder,
        redactor: SecretRedactor | None = None,
        last_timestamps: LastTimestamps | None = None,
    ) -> None:
        self._redactor = redactor if redactor is not None else SecretRedactor()
        self._settings = settings
        self._credentials = credentials
        self._drivers = drivers
        self._last_timestamps = last_timestamps if last_timestamps is not None else NoStoredData()

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
        sources = device_source_registry.create(
            self._settings.sources, SourceContext(self._last_timestamps)
        )
        try:
            result = PortalSession(client, sources).run(sensors)
        except (PortalError, WebDriverException, OSError, TransportError) as error:
            text = redactor.redact(f"Portal session failed: {type(error).__name__}: {error}")
            raise SourceUnavailableError(text) from None
        return self._report(result, redactor)

    def _report(self, result: SessionResult, redactor: SecretRedactor) -> FetchReport:
        by_source: dict[str, int] = {}
        for download in result.downloads:
            by_source[download.source] = by_source.get(download.source, 0) + 1
        delivered = ", ".join(f"{count} by {name}" for name, count in sorted(by_source.items()))
        logger.info(
            "Fetched %d file(s) into %s (%s); %d device(s) up to date, %d failed.",
            len(result.downloads),
            self._settings.download_dir,
            delivered or "none",
            len(result.up_to_date),
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
        """Fetch each device's data, table first (see :class:`~sivin.app.run.ExportSource`).

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
