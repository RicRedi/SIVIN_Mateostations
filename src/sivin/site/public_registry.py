"""The public projection of the sensor registry, published as ``sensors.geojson``.

Owner decision 2026-10-05 (MIGRATION_PLAN §0.5): internal notes are not published. The web
gets the registry with every sensor's ``notes`` and every placement's ``note`` set to
``null``; all other keys (``portal_name`` included, the web contract relies on it) are kept.
The registry file in the repository is not changed.
"""

from __future__ import annotations

import logging
from typing import Any

from sivin.registry.geojson import GeoJsonRegistryStore
from sivin.registry.model import Placement, Sensor
from sivin.registry.registry import SensorRegistry
from sivin.registry.settings import RegistrySettings

logger = logging.getLogger(__name__)


class PublicRegistryProjection:
    """Turn the registry file into its public form (internal notes removed).

    Parameters
    ----------
    store : GeoJsonRegistryStore, optional
        Reads and renders the registry. Defaults to a store without the allowed-area check:
        the registry was validated with the configured area when it was loaded, and the
        projection must not reject what the configuration accepts.
    """

    __slots__ = ("_store",)

    def __init__(self, store: GeoJsonRegistryStore | None = None) -> None:
        if store is None:
            store = GeoJsonRegistryStore(RegistrySettings(allowed_area=None))
        self._store = store

    def document(self, registry_file: bytes) -> dict[str, Any]:
        """Return the public registry as a JSON document.

        Parameters
        ----------
        registry_file : bytes
            Content of the registry file (``sensors/sensors.geojson``).

        Returns
        -------
        dict
            The FeatureCollection in the registry file's key order, without internal notes.

        Raises
        ------
        RegistryFormatError
            If the content is not a valid registry file.
        """
        registry = self._store.loads(registry_file, "registry file of the site build")
        public = SensorRegistry(self.sensor(sensor) for sensor in registry)
        logger.debug("Public registry: %d sensors, internal notes removed", len(public))
        return self._store.document(public)

    @staticmethod
    def sensor(sensor: Sensor) -> Sensor:
        """Return a sensor without its internal notes.

        Parameters
        ----------
        sensor : Sensor
            A registry sensor.

        Returns
        -------
        Sensor
            The same sensor with ``notes`` and every placement's ``note`` set to ``None``.
        """
        placements = tuple(PublicRegistryProjection.placement(p) for p in sensor.placements)
        return sensor.replaced(notes=None, placements=placements)

    @staticmethod
    def placement(placement: Placement) -> Placement:
        """Return a placement without its internal note.

        Parameters
        ----------
        placement : Placement
            A placement.

        Returns
        -------
        Placement
            The same placement with ``note`` set to ``None``.
        """
        return placement.model_copy(update={"note": None})
