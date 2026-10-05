"""Shared builders for registry tests. All sensors built here are synthetic.

Serial numbers other than the four real ones from ``sensor_location.gpx`` are invented, and all
coordinates are made-up points in South Moravia.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from sivin.registry.model import Placement, Sensor

PlacementFactory = Callable[..., Placement]
SensorFactory = Callable[..., Sensor]

T_2025_12_01 = datetime(2025, 12, 1, tzinfo=UTC)
T_2026_03_01 = datetime(2026, 3, 1, tzinfo=UTC)
T_2026_06_01 = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.fixture
def make_placement() -> PlacementFactory:
    """Build a synthetic placement; defaults: open, from 2025-12-01, a point near Mikulov."""

    def factory(
        from_utc: datetime = T_2025_12_01,
        to_utc: datetime | None = None,
        lat_deg: float = 48.80,
        lon_deg: float = 16.60,
        elevation_m: float | None = 200.0,
        note: str | None = None,
    ) -> Placement:
        return Placement(
            from_utc=from_utc,
            to_utc=to_utc,
            lat_deg=lat_deg,
            lon_deg=lon_deg,
            elevation_m=elevation_m,
            note=note,
        )

    return factory


@pytest.fixture
def make_sensor(make_placement: PlacementFactory) -> SensorFactory:
    """Build a synthetic active sensor with one open placement unless told otherwise.

    The portal name defaults to ``"8615620 <serial>"``.
    """

    def factory(
        serial: str = "11112222",
        *,
        portal_name: str | None = None,
        site: str | None = None,
        status: str = "active",
        placements: tuple[Placement, ...] | None = None,
    ) -> Sensor:
        return Sensor.model_validate(
            {
                "id": serial,
                "portal_name": portal_name if portal_name is not None else f"8615620 {serial}",
                "label": f"{serial} (synthetic)",
                "site": site,
                "variety": None,
                "status": status,
                "placements": placements if placements is not None else (make_placement(),),
                "notes": None,
            }
        )

    return factory
