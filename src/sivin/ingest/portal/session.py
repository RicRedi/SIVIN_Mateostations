"""One complete download run: login, device list and the data of every device."""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Final

from selenium.common.exceptions import WebDriverException

from sivin.core.ids import SensorId
from sivin.ingest.portal.client import PortalClient
from sivin.ingest.portal.errors import PortalError
from sivin.ingest.portal.models import (
    DeviceFailure,
    DownloadedExport,
    PortalDevice,
    SessionResult,
    UpToDateDevice,
)
from sivin.ingest.portal.sources import DeviceSource, SourceContext, device_source_registry

logger = logging.getLogger(__name__)

NOT_LISTED_REASON: Final = "not listed in the portal"
"""Failure reason of a requested sensor that the portal does not list."""

DEVICE_ERRORS: Final = (WebDriverException, PortalError, OSError)
"""Errors that fail one device but not the run."""

SOURCE_SEPARATOR: Final = "; "
"""Separates the failure reasons of several sources in :attr:`DeviceFailure.reason`."""


class _SourceFailedError(Exception):
    """All attempts of one source failed for one device; ``reason`` summarises them."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PortalSession:
    """Fetches the data of all (or selected) devices; one failure never stops the run.

    Parameters
    ----------
    client : PortalClient
        A client that is not yet open; :meth:`run` opens and closes it. Its
        ``settings.attempts_per_device`` sets how often a failing source is retried.
    sources : sequence of DeviceSource, optional
        Tried in order per device until one delivers; built from ``settings.sources`` with a
        default :class:`~sivin.ingest.portal.sources.SourceContext` (no store: the table is
        read in full) when omitted.
    """

    def __init__(self, client: PortalClient, sources: Sequence[DeviceSource] | None = None) -> None:
        self._client = client
        self._sources = (
            tuple(sources)
            if sources is not None
            else device_source_registry.create(client.settings.sources, SourceContext())
        )
        if not self._sources:
            raise ValueError("A portal session needs at least one source.")

    def run(self, devices: Collection[SensorId] | None = None) -> SessionResult:
        """Log in and fetch the data of every device (export, table, …).

        Parameters
        ----------
        devices : Collection[SensorId], optional
            Sensors to download; every device the portal lists when omitted. A requested
            sensor the portal does not list is recorded as a failure.

        Returns
        -------
        SessionResult
            Delivered files, devices without new rows and failed devices; the caller decides
            the exit code.

        Raises
        ------
        PortalLoginError
            If the login fails.
        ViewModelError
            If the device list cannot be read.
        selenium.common.exceptions.WebDriverException
            If the browser fails before the device loop (start, login page, folder).
        """
        downloads: list[DownloadedExport] = []
        up_to_date: list[UpToDateDevice] = []
        failures: list[DeviceFailure] = []
        with self._client as client:
            client.login()
            listed = client.list_devices()
            selected, missing = self._select(listed, devices)
            failures.extend(DeviceFailure(device, NOT_LISTED_REASON) for device in missing)
            for device in selected:
                outcome = self._fetch(client, device)
                if isinstance(outcome, DeviceFailure):
                    failures.append(outcome)
                elif isinstance(outcome, UpToDateDevice):
                    up_to_date.append(outcome)
                else:
                    downloads.append(outcome)
        logger.info(
            "Portal session: %d delivered, %d up to date, %d failed.",
            len(downloads),
            len(up_to_date),
            len(failures),
        )
        return SessionResult(tuple(downloads), tuple(failures), tuple(up_to_date))

    def _fetch(
        self, client: PortalClient, device: PortalDevice
    ) -> DownloadedExport | UpToDateDevice | DeviceFailure:
        """Try the sources in order; the device fails only when every source failed."""
        reasons: list[str] = []
        for source in self._sources:
            try:
                path = self._attempt(client, source, device)
            except _SourceFailedError as failed:
                reasons.append(failed.reason)
                logger.warning("The %s source failed for %s: %s", source.name, device, failed)
                continue
            self._leave_device(client)
            fallback = f" after {len(reasons)} failed source(s)" if reasons else ""
            if path is None:
                logger.info("%s: up to date (%s source%s).", device, source.name, fallback)
                return UpToDateDevice(device, source.name)
            logger.info("%s: delivered by the %s source%s.", device, source.name, fallback)
            return DownloadedExport(device, path, source.name)
        return DeviceFailure(device, self._reason(reasons))

    def _attempt(
        self, client: PortalClient, source: DeviceSource, device: PortalDevice
    ) -> Path | None:
        """Try one source up to ``attempts_per_device`` times, recovering between attempts.

        Raises
        ------
        _SourceFailedError
            When every attempt failed.
        """
        attempts = client.settings.attempts_per_device
        reasons: list[str] = []
        for attempt in range(1, attempts + 1):
            try:
                return source.deliver(client, device)
            except DEVICE_ERRORS as error:
                reasons.append(_describe(error))
                logger.warning(
                    "%s of %s failed (attempt %d of %d): %s",
                    source.name.capitalize(),
                    device,
                    attempt,
                    attempts,
                    reasons[-1],
                )
                self._recover(client)
        raise _SourceFailedError(_summarise(reasons))

    def _reason(self, reasons: list[str]) -> str:
        """Return the failure reason; prefixed with the source names when several were used."""
        if len(self._sources) == 1:
            return reasons[0]
        return SOURCE_SEPARATOR.join(
            f"{source.name}: {reason}"
            for source, reason in zip(self._sources, reasons, strict=True)
        )

    @staticmethod
    def _leave_device(client: PortalClient) -> None:
        """Return to the device list; a failure here never loses the delivered data."""
        try:
            client.back_to_device_list()
        except DEVICE_ERRORS as error:
            logger.warning(
                "Data delivered, but returning to the device list failed: %s",
                _describe(error),
            )

    @staticmethod
    def _select(
        listed: list[PortalDevice], wanted: Collection[SensorId] | None
    ) -> tuple[list[PortalDevice], list[PortalDevice]]:
        if wanted is None:
            return listed, []
        selected = [device for device in listed if device.sensor_id in wanted]
        found = {device.sensor_id for device in selected}
        missing = [PortalDevice(str(sensor)) for sensor in sorted(wanted) if sensor not in found]
        return selected, missing

    @staticmethod
    def _recover(client: PortalClient) -> None:
        try:
            client.return_to_folder()
        except DEVICE_ERRORS as error:
            logger.warning("Returning to the device list failed: %s", _describe(error))


def _describe(error: BaseException) -> str:
    """Return ``"<ExceptionType>: <first line of the message>"``."""
    message = (error.msg if isinstance(error, WebDriverException) else str(error)) or ""
    lines = message.strip().splitlines()
    return f"{type(error).__name__}: {lines[0]}" if lines else type(error).__name__


def _summarise(reasons: list[str]) -> str:
    """Return the first failure reason, plus the last one when a retry failed differently."""
    if len(reasons) == 1:
        return reasons[0]
    if reasons[-1] == reasons[0]:
        return f"{reasons[0]} ({len(reasons)} attempts)"
    return f"{reasons[0]} ({len(reasons)} attempts; last: {reasons[-1]})"
