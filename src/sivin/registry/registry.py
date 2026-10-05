"""The sensor registry: an immutable collection of sensors (MIGRATION_PLAN §2.4).

:class:`SensorRegistry` resolves every known spelling of a sensor name to its :class:`Sensor`
and returns new registries for changes. Reading and writing the registry file is the job of
:class:`~sivin.registry.geojson.GeoJsonRegistryStore`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator
from pathlib import PureWindowsPath
from typing import Final

from sivin.core.ids import LEGACY_SUFFIX_DIGITS, SensorId
from sivin.registry.errors import AmbiguousSensorNameError, RegistryError, SensorLookupError
from sivin.registry.model import Placement, Sensor
from sivin.registry.settings import GeoBounds

logger = logging.getLogger(__name__)

_LEGACY_SUFFIX_PATTERN: Final = re.compile(rf"[0-9]{{{LEGACY_SUFFIX_DIGITS}}}")


def _base_name(text: str) -> str:
    """Normalise a name the way :meth:`SensorId.parse` does: base name of a (Windows) path.

    ``sivin.core.ids`` keeps this step private; see the WP-1.1 hand-off note (out of scope).
    """
    return PureWindowsPath(text.strip()).name.strip()


class SensorRegistry:
    """Immutable collection of sensors with unique ids (and therefore unique portal names).

    Portal names are unique because every :class:`Sensor` checks that its portal name contains
    its own serial: two sensors with one portal name would share an id.

    Parameters
    ----------
    sensors : iterable of Sensor
        The sensors; their order is kept (it is the order in the registry file).
    area : GeoBounds, optional
        Bounding box every placement must lie in; no check when omitted.

    Raises
    ------
    RegistryError
        If two sensors share an id (or a portal name), or a placement lies outside ``area``.
    """

    def __init__(self, sensors: Iterable[Sensor] = (), *, area: GeoBounds | None = None) -> None:
        self._sensors: tuple[Sensor, ...] = tuple(sensors)
        self._area = area
        self._by_id: dict[SensorId, Sensor] = {}
        self._by_suffix: dict[str, list[Sensor]] = {}
        for sensor in self._sensors:
            if sensor.id in self._by_id:
                raise RegistryError(f"Duplicate sensor id {sensor.id} in the registry.")
            self._by_id[sensor.id] = sensor
            self._by_suffix.setdefault(sensor.id.legacy_suffix, []).append(sensor)
            self._check_area(sensor)

    def _check_area(self, sensor: Sensor) -> None:
        if self._area is None:
            return
        for index, placement in enumerate(sensor.placements):
            if not self._area.contains(placement.lat_deg, placement.lon_deg):
                raise RegistryError(
                    f"Placement {index} of sensor {sensor.id} (lat {placement.lat_deg}, "
                    f"lon {placement.lon_deg}) lies outside the allowed area {self._area}; "
                    "are latitude and longitude swapped?"
                )

    @property
    def area(self) -> GeoBounds | None:
        """The bounding box placements are checked against, if any."""
        return self._area

    def __iter__(self) -> Iterator[Sensor]:
        return iter(self._sensors)

    def __len__(self) -> int:
        return len(self._sensors)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, SensorId | str):
            return False
        try:
            self.get(key)
        except SensorLookupError:
            return False
        return True

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SensorRegistry):
            return NotImplemented
        return self._sensors == other._sensors and self._area == other._area

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        ids = ", ".join(str(sensor.id) for sensor in self._sensors)
        return f"SensorRegistry([{ids}])"

    def ids(self) -> tuple[SensorId, ...]:
        """Return the sensor ids in registry order.

        Returns
        -------
        tuple of SensorId
            One id per sensor.
        """
        return tuple(sensor.id for sensor in self._sensors)

    def active(self) -> tuple[Sensor, ...]:
        """Return the sensors whose status is ``active``, in registry order.

        Returns
        -------
        tuple of Sensor
            The active sensors.
        """
        return tuple(sensor for sensor in self._sensors if sensor.is_active)

    def get(self, key: SensorId | str) -> Sensor:
        """Find a sensor by its id or by any known spelling of its name.

        Parameters
        ----------
        key : SensorId or str
            A :class:`SensorId`, the canonical serial, the portal name (``8615620 77678271``),
            the GPX name (``77678271 (VUT)``), an export file name or path, or the legacy
            4-digit short name (``8271``, also as the last component of a path) if exactly one
            sensor of the registry ends with it.

        Returns
        -------
        Sensor
            The sensor.

        Raises
        ------
        AmbiguousSensorNameError
            If a legacy short name matches more than one sensor.
        SensorLookupError
            If the name is not recognised or names a sensor that is not in the registry.
        """
        if isinstance(key, SensorId):
            return self._by_known_id(key, key)
        name = _base_name(key)
        if _LEGACY_SUFFIX_PATTERN.fullmatch(name) is not None:
            return self._by_legacy_suffix(name)
        try:
            sensor_id = SensorId.parse(key)
        except ValueError as error:
            raise SensorLookupError(str(error)) from error
        return self._by_known_id(sensor_id, key)

    def _by_known_id(self, sensor_id: SensorId, key: SensorId | str) -> Sensor:
        sensor = self._by_id.get(sensor_id)
        if sensor is None:
            raise SensorLookupError(f"Sensor {sensor_id} (from {key!r}) is not in the registry.")
        return sensor

    def _by_legacy_suffix(self, suffix: str) -> Sensor:
        matches = self._by_suffix.get(suffix, [])
        if not matches:
            raise SensorLookupError(f"No sensor of the registry has a serial ending in {suffix}.")
        if len(matches) > 1:
            candidates = ", ".join(str(sensor.id) for sensor in matches)
            raise AmbiguousSensorNameError(
                f"Legacy short name {suffix!r} is ambiguous: it matches sensors {candidates}. "
                "Use the full 8-digit serial."
            )
        return matches[0]

    def with_sensor(self, sensor: Sensor) -> SensorRegistry:
        """Return a registry with a sensor added, or replaced if its id is already present.

        Parameters
        ----------
        sensor : Sensor
            The new or updated sensor. A replaced sensor keeps its position; a new one is
            appended.

        Returns
        -------
        SensorRegistry
            The new registry (same area).

        Raises
        ------
        RegistryError
            If the result violates a registry rule (e.g. a duplicate portal name).
        """
        if sensor.id in self._by_id:
            sensors = [sensor if s.id == sensor.id else s for s in self._sensors]
            logger.info("Replacing sensor %s in the registry", sensor.id)
        else:
            sensors = [*self._sensors, sensor]
            logger.info("Adding sensor %s to the registry", sensor.id)
        return SensorRegistry(sensors, area=self._area)

    def without(self, sensor_id: SensorId) -> SensorRegistry:
        """Return a registry without a sensor.

        Removing a sensor deletes its history; to take a sensor out of use, set its status to
        ``retired`` instead (see ``docs/sensors.md``).

        Parameters
        ----------
        sensor_id : SensorId
            The sensor to remove.

        Returns
        -------
        SensorRegistry
            The new registry.

        Raises
        ------
        SensorLookupError
            If the sensor is not in the registry.
        """
        self._by_known_id(sensor_id, sensor_id)
        logger.info("Removing sensor %s from the registry", sensor_id)
        return SensorRegistry(
            (sensor for sensor in self._sensors if sensor.id != sensor_id), area=self._area
        )

    def with_moved(self, sensor_id: SensorId, placement: Placement) -> SensorRegistry:
        """Return a registry in which a sensor has moved to a new placement.

        The sensor's open placement is closed at ``placement.from_utc``.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor that moves.
        placement : Placement
            The new placement.

        Returns
        -------
        SensorRegistry
            The new registry.

        Raises
        ------
        SensorLookupError
            If the sensor is not in the registry.
        pydantic.ValidationError
            If the new placement does not fit after the sensor's history.
        RegistryError
            If the new placement lies outside the allowed area.
        """
        return self.with_sensor(self._by_known_id(sensor_id, sensor_id).moved_to(placement))
