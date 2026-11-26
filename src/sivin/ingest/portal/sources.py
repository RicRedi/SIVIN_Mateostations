"""Ways of getting one device's data from the portal: the Excel export and the device table.

:class:`PortalSession` tries the sources named in ``ingest.portal.sources`` in order and stops
at the first that delivers. Each source is a :class:`DeviceSource` subclass registered under
its :class:`~sivin.ingest.portal.settings.PortalSource` value in :data:`device_source_registry`;
a new way of fetching is a new registered class.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Protocol

from sivin.core.ids import SensorId
from sivin.ingest.portal.client import PortalClient
from sivin.ingest.portal.errors import TableReadError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.settings import PortalSource
from sivin.ingest.portal.table_file import TableCsvWriter

logger = logging.getLogger(__name__)


class LastTimestamps(Protocol):
    """Tells the last stored measurement of a sensor (read-only)."""

    def last_timestamp(self, sensor_id: SensorId) -> datetime | None:
        """Return the newest stored ``timestamp_utc`` of a sensor.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.

        Returns
        -------
        datetime.datetime or None
            Timezone-aware UTC time, or ``None`` when nothing is stored.
        """
        ...


class NoStoredData:
    """A :class:`LastTimestamps` without a store: the whole table history is always read."""

    __slots__ = ()

    def last_timestamp(self, sensor_id: SensorId) -> datetime | None:
        """Return ``None`` (nothing known to be stored).

        Parameters
        ----------
        sensor_id : SensorId
            The sensor (unused).

        Returns
        -------
        None
            Always.
        """
        return None


def utc_now() -> datetime:
    """Return the current UTC time (timezone-aware).

    Returns
    -------
    datetime.datetime
        Now, in UTC.
    """
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SourceContext:
    """What the sources need besides the open client.

    Parameters
    ----------
    last_timestamps : LastTimestamps, optional
        Last stored measurement per sensor; :class:`NoStoredData` (full history) by default.
    clock : callable, optional
        Returns the current time (timezone-aware), for the names of written table files.
    """

    last_timestamps: LastTimestamps = field(default_factory=NoStoredData)
    clock: Callable[[], datetime] = utc_now


class DeviceSource(ABC):
    """One way of getting a device's data into the download directory.

    Subclasses define :attr:`name` and register with :data:`device_source_registry`.

    Parameters
    ----------
    context : SourceContext
        Store lookup and clock.
    """

    name: ClassVar[str]
    """Key of the source in ``ingest.portal.sources``."""

    def __init__(self, context: SourceContext) -> None:
        self._context = context

    @abstractmethod
    def deliver(self, client: PortalClient, device: PortalDevice) -> Path | None:
        """Fetch the device's data; the browser may stay on the device page.

        Parameters
        ----------
        client : PortalClient
            The open, logged-in client showing the device list.
        device : PortalDevice
            The device.

        Returns
        -------
        pathlib.Path or None
            The file to ingest, or ``None`` when the source worked but had nothing new.

        Raises
        ------
        PortalError, selenium.common.exceptions.WebDriverException, OSError
            When the source fails for this device.
        """


class DeviceSourceRegistry:
    """Registry of :class:`DeviceSource` classes keyed by :attr:`DeviceSource.name`.

    Filled by class decorators at import time and never changed afterwards (the one kind of
    module-level mutable state MIGRATION_PLAN §1.2 allows).
    """

    __slots__ = ("_classes",)

    def __init__(self) -> None:
        self._classes: dict[str, type[DeviceSource]] = {}

    def register[C: type[DeviceSource]](self, cls: C) -> C:
        """Register a source class; use as a class decorator.

        Parameters
        ----------
        cls : type[DeviceSource]
            The class; its ``name`` is the key.

        Returns
        -------
        type[DeviceSource]
            The class unchanged.

        Raises
        ------
        ValueError
            If the name is missing or already registered.
        """
        name = getattr(cls, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError(f"{cls.__name__} has no 'name'.")
        if name in self._classes:
            raise ValueError(f"A device source named {name!r} is already registered.")
        self._classes[name] = cls
        return cls

    def create(self, names: Sequence[str], context: SourceContext) -> tuple[DeviceSource, ...]:
        """Instantiate the named sources in the given order.

        Parameters
        ----------
        names : sequence of str
            Source names, e.g. ``settings.sources``.
        context : SourceContext
            Passed to every source.

        Returns
        -------
        tuple[DeviceSource, ...]
            The sources.

        Raises
        ------
        KeyError
            If a name is not registered.
        """
        sources = []
        for name in names:
            try:
                cls = self._classes[str(name)]
            except KeyError:
                raise KeyError(
                    f"Unknown device source {name!r}; registered: {self.names()}."
                ) from None
            sources.append(cls(context))
        return tuple(sources)

    def names(self) -> list[str]:
        """Return the registered names.

        Returns
        -------
        list[str]
            Sorted names.
        """
        return sorted(self._classes)


device_source_registry = DeviceSourceRegistry()
"""The registry of the built-in sources (``export``, ``table``)."""


@device_source_registry.register
class ExportSource(DeviceSource):
    """Click the Excel export button and wait for the downloaded file (WP-1.3)."""

    name = PortalSource.EXPORT.value

    def deliver(self, client: PortalClient, device: PortalDevice) -> Path:
        """Download the export.

        Parameters
        ----------
        client : PortalClient
            The open client showing the device list.
        device : PortalDevice
            The device.

        Returns
        -------
        pathlib.Path
            The downloaded file.
        """
        return client.download_export(device)


@device_source_registry.register
class TableSource(DeviceSource):
    """Read the device page's data table and write the new rows as a CSV export (WP-1.10).

    Only rows newer than the sensor's last stored measurement are read and written; without
    stored data the whole history is read.
    """

    name = PortalSource.TABLE.value

    def deliver(self, client: PortalClient, device: PortalDevice) -> Path | None:
        """Read the table and write the new rows.

        Parameters
        ----------
        client : PortalClient
            The open client showing the device list.
        device : PortalDevice
            The device; its name must name a sensor.

        Returns
        -------
        pathlib.Path or None
            The written file, or ``None`` when the table has no row newer than the store.

        Raises
        ------
        TableReadError
            If the device names no sensor or the table cannot be read.
        """
        sensor_id = device.sensor_id
        if sensor_id is None:
            raise TableReadError(
                f"The device name {device.name!r} does not name a sensor; its table rows "
                "could not be attributed."
            )
        since_utc = self._context.last_timestamps.last_timestamp(sensor_id)
        logger.info(
            "Reading the table of %s %s.",
            device,
            "(whole history)" if since_utc is None else f"after {since_utc.isoformat()}",
        )
        reading = client.read_table(device, since_utc)
        if not reading.rows:
            logger.info("The table of %s has no row newer than the store.", device)
            return None
        writer = TableCsvWriter(client.settings.table, client.settings.download_dir)
        return writer.write(device, reading, self._context.clock())
