"""One complete download run: login, device list and an export per device."""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import Final

from selenium.common.exceptions import WebDriverException

from sivin.core.ids import SensorId
from sivin.ingest.portal.client import PortalClient
from sivin.ingest.portal.errors import PortalError
from sivin.ingest.portal.models import DeviceFailure, DownloadedExport, PortalDevice, SessionResult

logger = logging.getLogger(__name__)

NOT_LISTED_REASON: Final = "not listed in the portal"
"""Failure reason of a requested sensor that the portal does not list."""

DEVICE_ERRORS: Final = (WebDriverException, PortalError, OSError)
"""Errors that fail one device but not the run."""


class PortalSession:
    """Downloads the exports of all (or selected) devices; one failure never stops the run.

    Parameters
    ----------
    client : PortalClient
        A client that is not yet open; :meth:`run` opens and closes it.
    """

    def __init__(self, client: PortalClient) -> None:
        self._client = client

    def run(self, devices: Collection[SensorId] | None = None) -> SessionResult:
        """Log in and download one export per device.

        Parameters
        ----------
        devices : Collection[SensorId], optional
            Sensors to download; every device the portal lists when omitted. A requested
            sensor the portal does not list is recorded as a failure.

        Returns
        -------
        SessionResult
            Downloaded files and failed devices; the caller decides the exit code.

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
        failures: list[DeviceFailure] = []
        with self._client as client:
            client.login()
            listed = client.list_devices()
            selected, missing = self._select(listed, devices)
            failures.extend(DeviceFailure(device, NOT_LISTED_REASON) for device in missing)
            for device in selected:
                try:
                    downloads.append(DownloadedExport(device, client.download_export(device)))
                except DEVICE_ERRORS as error:
                    failures.append(DeviceFailure(device, _describe(error)))
                    logger.warning("Export of %s failed: %s", device, failures[-1].reason)
                    self._recover(client)
        logger.info("Portal session: %d downloaded, %d failed.", len(downloads), len(failures))
        return SessionResult(tuple(downloads), tuple(failures))

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
