"""Import of sensors from a GPX file (waypoints), using only the standard library.

The legacy file ``sensor_location.gpx`` (exported from mapy.com) holds one waypoint per sensor:
``<wpt lat=".." lon=".."><ele>..</ele><name>77678271 (VUT)</name></wpt>``.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from sivin.core.ids import SensorId
from sivin.registry.errors import GpxFormatError
from sivin.registry.model import Placement, Sensor

logger = logging.getLogger(__name__)

GPX_ROOT_TAG: Final = "gpx"
"""Local name of the GPX root element."""

_NAMESPACE_PATTERN: Final = re.compile(r"^\{(?P<uri>[^}]*)\}")

_PORTAL_PREFIX_PATTERN: Final = re.compile(r"[0-9]+")


@dataclass(frozen=True, slots=True)
class GpxWaypoint:
    """One waypoint of a GPX file.

    Attributes
    ----------
    name : str
        Waypoint name, e.g. ``"77678271 (VUT)"``.
    lat_deg : float
        Latitude in degrees north.
    lon_deg : float
        Longitude in degrees east.
    elevation_m : float or None
        Elevation in metres, if the waypoint has ``<ele>``.
    """

    name: str
    lat_deg: float
    lon_deg: float
    elevation_m: float | None


class GpxImporter:
    """Build registry sensors from the waypoints of a GPX 1.1 file.

    Every waypoint becomes an ``active`` sensor with one open placement. The sensor id is
    parsed from the waypoint name, which also becomes the label.

    Parameters
    ----------
    portal_prefix : str
        Device-number prefix of the provider's portal (digits); the portal name of every
        imported sensor is ``"<portal_prefix> <serial>"``. It is required because every sensor
        of the registry has a portal name (MIGRATION_PLAN §2.4). The prefix is passed by the
        caller and never assumed here.

    Raises
    ------
    ValueError
        If ``portal_prefix`` is not a string of digits.
    """

    def __init__(self, portal_prefix: str) -> None:
        if _PORTAL_PREFIX_PATTERN.fullmatch(portal_prefix) is None:
            raise ValueError(f"portal_prefix must be digits, got {portal_prefix!r}")
        self._portal_prefix = portal_prefix

    def read(
        self, path: Path, deployed_from: datetime, *, note_suffix: str | None = None
    ) -> tuple[Sensor, ...]:
        """Read the sensors of a GPX file.

        Parameters
        ----------
        path : pathlib.Path
            The GPX file.
        deployed_from : datetime.datetime
            Time-zone aware ``from`` instant of every imported placement.
        note_suffix : str, optional
            Text appended to the placement note ``"imported from <file name>"`` after ``"; "``,
            e.g. to mark ``deployed_from`` as a placeholder.

        Returns
        -------
        tuple of Sensor
            One sensor per waypoint, in file order.

        Raises
        ------
        GpxFormatError
            If the file cannot be read or parsed, is not GPX, or a waypoint lacks a name or
            valid coordinates.
        ValueError
            If a waypoint name contains no sensor id, or ``deployed_from`` is naive.
        """
        note = f"imported from {path.name}"
        if note_suffix is not None:
            note = f"{note}; {note_suffix}"
        sensors = tuple(
            self._sensor(waypoint, deployed_from, note) for waypoint in self.waypoints(path)
        )
        logger.info("Imported %d sensors from %s", len(sensors), path)
        return sensors

    def waypoints(self, path: Path) -> tuple[GpxWaypoint, ...]:
        """Read the waypoints of a GPX file.

        Parameters
        ----------
        path : pathlib.Path
            The GPX file.

        Returns
        -------
        tuple of GpxWaypoint
            The waypoints in file order.

        Raises
        ------
        GpxFormatError
            If the file cannot be read or parsed, is not GPX, or a waypoint is incomplete.
        """
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as error:
            raise GpxFormatError(f"Cannot read GPX file {path}: {error}") from error
        match = _NAMESPACE_PATTERN.match(root.tag)
        prefix = match.group(0) if match is not None else ""
        if root.tag.removeprefix(prefix) != GPX_ROOT_TAG:
            raise GpxFormatError(f"{path} is not a GPX file (root element {root.tag!r}).")
        return tuple(self._waypoint(element, prefix, path) for element in root.iter(f"{prefix}wpt"))

    @staticmethod
    def _waypoint(element: ET.Element, prefix: str, path: Path) -> GpxWaypoint:
        name = (element.findtext(f"{prefix}name") or "").strip()
        if not name:
            raise GpxFormatError(f"A waypoint in {path} has no <name>.")
        elevation = element.findtext(f"{prefix}ele")
        try:
            return GpxWaypoint(
                name=name,
                lat_deg=float(element.attrib["lat"]),
                lon_deg=float(element.attrib["lon"]),
                elevation_m=float(elevation) if elevation is not None else None,
            )
        except (KeyError, ValueError) as error:
            raise GpxFormatError(
                f"Waypoint {name!r} in {path} has missing or invalid lat/lon/ele: {error}"
            ) from error

    def _sensor(self, waypoint: GpxWaypoint, deployed_from: datetime, note: str) -> Sensor:
        sensor_id = SensorId.parse(waypoint.name)
        placement = Placement(
            from_utc=deployed_from,
            to_utc=None,
            lon_deg=waypoint.lon_deg,
            lat_deg=waypoint.lat_deg,
            elevation_m=waypoint.elevation_m,
            note=note,
        )
        return Sensor(
            id=sensor_id,
            portal_name=f"{self._portal_prefix} {sensor_id}",
            label=waypoint.name,
            site=None,
            variety=None,
            status="active",
            placements=(placement,),
            notes=None,
        )
