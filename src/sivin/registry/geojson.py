"""Reading and writing the registry file ``sensors/sensors.geojson`` (MIGRATION_PLAN §2.4).

The file is a GeoJSON FeatureCollection with one Point feature per sensor. The geometry is the
position of the sensor's last placement as ``[lon, lat]``; the properties are the
:class:`~sivin.registry.model.Sensor` fields. The writer produces a canonical text (fixed key
order, 2-space indentation, trailing newline), so saving a loaded canonical file reproduces it
byte for byte and diffs stay small.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sivin.registry.errors import RegistryFormatError
from sivin.registry.model import Sensor
from sivin.registry.registry import SensorRegistry
from sivin.registry.settings import RegistrySettings

logger = logging.getLogger(__name__)

JSON_INDENT: Final = 2
"""Indentation of the written JSON in spaces."""

FILE_ENCODING: Final = "utf-8"
"""Encoding of the registry file and of the JSON Schema file."""

_DOC_CONFIG: Final = ConfigDict(frozen=True, extra="forbid")


def render_json(document: Any) -> str:
    """Render a JSON document in the canonical text form of the registry files.

    Parameters
    ----------
    document : Any
        JSON-compatible value; mapping key order is kept.

    Returns
    -------
    str
        UTF-8 friendly JSON (non-ASCII kept), 2-space indentation, trailing newline.
    """
    return json.dumps(document, indent=JSON_INDENT, ensure_ascii=False, allow_nan=False) + "\n"


class PointGeometry(BaseModel):
    """GeoJSON Point of the sensor's last placement."""

    model_config = _DOC_CONFIG

    type: Literal["Point"] = Field(description="GeoJSON geometry type.")
    coordinates: tuple[float, float] = Field(
        description="[longitude, latitude] in degrees (WGS 84) of the last placement."
    )


class SensorFeature(BaseModel):
    """GeoJSON Feature of one sensor."""

    model_config = _DOC_CONFIG

    type: Literal["Feature"] = Field(description="GeoJSON object type.")
    geometry: PointGeometry = Field(description="Position of the last placement.")
    properties: Sensor = Field(description="The sensor and its placement history.")

    @classmethod
    def of(cls, sensor: Sensor) -> SensorFeature:
        """Build the feature of a sensor.

        Parameters
        ----------
        sensor : Sensor
            The sensor.

        Returns
        -------
        SensorFeature
            Feature whose point is the sensor's last placement.
        """
        last = sensor.last_placement
        return cls(
            type="Feature",
            geometry=PointGeometry(type="Point", coordinates=(last.lon_deg, last.lat_deg)),
            properties=sensor,
        )

    def check_geometry(self) -> None:
        """Check that the point equals the last placement.

        Raises
        ------
        RegistryFormatError
            If the geometry and the last placement disagree (e.g. the point was moved in a GIS
            tool without adding a placement).
        """
        last = self.properties.last_placement
        if self.geometry.coordinates != (last.lon_deg, last.lat_deg):
            raise RegistryFormatError(
                f"Sensor {self.properties.id}: geometry {list(self.geometry.coordinates)} differs "
                f"from its last placement [{last.lon_deg}, {last.lat_deg}]. Move a sensor by "
                "adding a placement (docs/sensors.md)."
            )


class SensorCollection(BaseModel):
    """The whole registry file: a GeoJSON FeatureCollection of sensors."""

    model_config = _DOC_CONFIG

    type: Literal["FeatureCollection"] = Field(description="GeoJSON object type.")
    features: tuple[SensorFeature, ...] = Field(description="One feature per sensor.")


class GeoJsonRegistryStore:
    """Load and save a :class:`SensorRegistry` as a GeoJSON FeatureCollection.

    Parameters
    ----------
    settings : RegistrySettings, optional
        Registry settings; ``allowed_area`` is applied to every loaded registry. Defaults to
        :class:`RegistrySettings` defaults (the Czech Republic).
    """

    def __init__(self, settings: RegistrySettings | None = None) -> None:
        self._settings = settings if settings is not None else RegistrySettings()

    def load(self, path: Path) -> SensorRegistry:
        """Read a registry file.

        Parameters
        ----------
        path : pathlib.Path
            The GeoJSON file.

        Returns
        -------
        SensorRegistry
            The registry, with the settings' allowed area.

        Raises
        ------
        RegistryFormatError
            If the file cannot be read, is not valid JSON or violates the format; the message
            names the location of every problem, e.g. ``features.0.properties.placements``.
        RegistryError
            If the sensors violate a registry rule (duplicates, area).
        """
        try:
            text = path.read_text(encoding=FILE_ENCODING)
        except OSError as error:
            raise RegistryFormatError(f"Cannot read sensor registry {path}: {error}") from error
        try:
            collection = SensorCollection.model_validate_json(text)
        except ValidationError as error:
            problems = "\n".join(
                f"  {'.'.join(str(part) for part in issue['loc']) or '<root>'}: {issue['msg']}"
                for issue in error.errors()
            )
            raise RegistryFormatError(f"Invalid sensor registry {path}:\n{problems}") from error
        for feature in collection.features:
            feature.check_geometry()
        registry = SensorRegistry(
            (feature.properties for feature in collection.features),
            area=self._settings.allowed_area,
        )
        logger.info("Loaded %d sensors from %s", len(registry), path)
        return registry

    def dumps(self, registry: SensorRegistry) -> str:
        """Render a registry as the canonical text of the registry file.

        Parameters
        ----------
        registry : SensorRegistry
            The registry.

        Returns
        -------
        str
            The file content.
        """
        collection = SensorCollection(
            type="FeatureCollection",
            features=tuple(SensorFeature.of(sensor) for sensor in registry),
        )
        return render_json(collection.model_dump(mode="json", by_alias=True))

    def save(self, registry: SensorRegistry, path: Path) -> None:
        """Write a registry file atomically (temporary file, then rename).

        Parameters
        ----------
        registry : SensorRegistry
            The registry.
        path : pathlib.Path
            Target file; its directory must exist.
        """
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            temporary.write_text(self.dumps(registry), encoding=FILE_ENCODING, newline="\n")
            temporary.replace(path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        logger.info("Saved %d sensors to %s", len(registry), path)
