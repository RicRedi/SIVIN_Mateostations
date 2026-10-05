"""Value objects of a portal session: devices, downloads, failures and the run result."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sivin.core.ids import SensorId


@dataclass(frozen=True, slots=True)
class PortalDevice:
    """A device as the portal lists it.

    Parameters
    ----------
    name : str
        ``DeviceName`` from the viewmodel, e.g. ``"8615620 77678271"``; also the text of the
        device link.
    """

    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("A portal device name must not be empty.")

    @property
    def sensor_id(self) -> SensorId | None:
        """Return the canonical sensor id parsed from the name.

        Returns
        -------
        SensorId or None
            The id, or ``None`` when the name is not a known sensor spelling.
        """
        try:
            return SensorId.parse(self.name)
        except ValueError:
            return None

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class DownloadedExport:
    """An export file downloaded for one device.

    Parameters
    ----------
    device : PortalDevice
        The device.
    path : pathlib.Path
        Absolute path of the downloaded file.
    """

    device: PortalDevice
    path: Path


@dataclass(frozen=True, slots=True)
class DeviceFailure:
    """A device whose export could not be downloaded.

    Parameters
    ----------
    device : PortalDevice
        The device.
    reason : str
        Short, single-line description (exception type and message).
    """

    device: PortalDevice
    reason: str


@dataclass(frozen=True, slots=True)
class SessionResult:
    """Outcome of one portal session; the caller decides the exit code.

    Parameters
    ----------
    downloads : tuple[DownloadedExport, ...]
        Successful downloads, in portal order.
    failures : tuple[DeviceFailure, ...]
        Devices that failed, in portal order.
    """

    downloads: tuple[DownloadedExport, ...]
    failures: tuple[DeviceFailure, ...]

    @property
    def files(self) -> tuple[Path, ...]:
        """Return the downloaded files.

        Returns
        -------
        tuple[pathlib.Path, ...]
            Paths of all downloaded exports.
        """
        return tuple(download.path for download in self.downloads)

    @property
    def ok(self) -> bool:
        """Return whether no device failed.

        Returns
        -------
        bool
            ``True`` when :attr:`failures` is empty.
        """
        return not self.failures
