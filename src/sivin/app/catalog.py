"""The sensors of the project: the registry and the off-site log, loaded and validated together."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sivin.app.outcome import Outcome, SetupError
from sivin.registry.errors import RegistryError, RegistryFormatError
from sivin.registry.geojson import GeoJsonRegistryStore
from sivin.registry.offsite import OffSiteLog, OffSiteLogError, OffSiteLogStore
from sivin.registry.registry import SensorRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SensorCatalog:
    """The validated sensor registry and off-site log.

    Attributes
    ----------
    registry : SensorRegistry
        All sensors with their placement history.
    offsite_log : OffSiteLog
        Periods when a sensor was not in the vineyard (checked against the registry).
    """

    registry: SensorRegistry
    offsite_log: OffSiteLog


class SensorCatalogLoader:
    """Read the registry and then the off-site log (which refers to registry sensors).

    Parameters
    ----------
    registry_store : GeoJsonRegistryStore
        Reads ``sensors/sensors.geojson`` with the ``registry`` settings.
    registry_file : pathlib.Path
        The registry file (absolute).
    offsite_store : OffSiteLogStore
        Reads ``sensors/offsite_log.yaml``.
    offsite_file : pathlib.Path
        The off-site log (absolute).
    offsite_timezone : str
        IANA zone of the local times in the log.
    """

    __slots__ = (
        "_offsite_file",
        "_offsite_store",
        "_offsite_timezone",
        "_registry_file",
        "_registry_store",
    )

    def __init__(
        self,
        registry_store: GeoJsonRegistryStore,
        registry_file: Path,
        offsite_store: OffSiteLogStore,
        offsite_file: Path,
        offsite_timezone: str,
    ) -> None:
        self._registry_store = registry_store
        self._registry_file = registry_file
        self._offsite_store = offsite_store
        self._offsite_file = offsite_file
        self._offsite_timezone = offsite_timezone

    def load(self) -> SensorCatalog:
        """Load and validate both files.

        Returns
        -------
        SensorCatalog
            The registry and the log.

        Raises
        ------
        SetupError
            If either file cannot be read or is invalid (plan §2.8: an invalid log stops the
            run). The message names the file and every problem.
        """
        try:
            registry = self._registry_store.load(self._registry_file)
        except (RegistryError, RegistryFormatError) as error:
            raise SetupError(f"Sensor registry {self._registry_file}:\n{error}") from error
        try:
            log = self._offsite_store.load(self._offsite_file, registry, self._offsite_timezone)
        except OffSiteLogError as error:
            raise SetupError(f"Off-site log {self._offsite_file}:\n{error}") from error
        logger.info("Loaded %d sensor(s) and %d off-site period(s).", len(registry), len(log))
        return SensorCatalog(registry, log)


@dataclass(frozen=True, slots=True)
class SensorsCheckReport:
    """Result of ``sivin sensors check``.

    Attributes
    ----------
    catalog : SensorCatalog or None
        The loaded registry and log; ``None`` if they are invalid.
    problem : str or None
        What is wrong, with file names and entries; ``None`` if both files are valid.
    """

    catalog: SensorCatalog | None
    problem: str | None = None

    @property
    def outcome(self) -> Outcome:
        """:attr:`Outcome.OK` for valid files, :attr:`Outcome.PARTIAL_FAILURE` otherwise."""
        return Outcome.OK if self.problem is None else Outcome.PARTIAL_FAILURE


class SensorsCheck:
    """Validate the sensor registry and the off-site log without running anything else.

    Parameters
    ----------
    loader : SensorCatalogLoader
        Loads both files.
    """

    __slots__ = ("_loader",)

    def __init__(self, loader: SensorCatalogLoader) -> None:
        self._loader = loader

    def run(self) -> SensorsCheckReport:
        """Load both files and report the first file that is invalid.

        Returns
        -------
        SensorsCheckReport
            The catalog, or the readable problem.
        """
        try:
            return SensorsCheckReport(self._loader.load())
        except SetupError as error:
            return SensorsCheckReport(None, str(error))
