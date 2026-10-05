"""Settings of the sensor registry: the geographic area the sensors must lie in.

The models are frozen and reject unknown keys, like every configuration section
(MIGRATION_PLAN §1.3). Wiring them into :class:`~sivin.config.SivinConfig` is left to the
integration workpackage.
"""

from __future__ import annotations

from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MIN_LATITUDE_DEG: Final = -90.0
"""Smallest valid WGS 84 latitude in degrees north."""

MAX_LATITUDE_DEG: Final = 90.0
"""Largest valid WGS 84 latitude in degrees north."""

MIN_LONGITUDE_DEG: Final = -180.0
"""Smallest valid WGS 84 longitude in degrees east."""

MAX_LONGITUDE_DEG: Final = 180.0
"""Largest valid WGS 84 longitude in degrees east."""

CZECH_REPUBLIC_MIN_LAT_DEG: Final = 48.55
"""Southern edge of the Czech Republic (about 48°33' N), rounded outward. [to be verified]"""

CZECH_REPUBLIC_MAX_LAT_DEG: Final = 51.06
"""Northern edge of the Czech Republic (about 51°03' N), rounded outward. [to be verified]"""

CZECH_REPUBLIC_MIN_LON_DEG: Final = 12.09
"""Western edge of the Czech Republic (about 12°05' E), rounded outward. [to be verified]"""

CZECH_REPUBLIC_MAX_LON_DEG: Final = 18.86
"""Eastern edge of the Czech Republic (about 18°51' E), rounded outward. [to be verified]"""


class GeoBounds(BaseModel):
    """A latitude/longitude bounding box (WGS 84, degrees).

    Parameters
    ----------
    min_lat_deg, max_lat_deg : float
        Southern and northern edge in degrees north.
    min_lon_deg, max_lon_deg : float
        Western and eastern edge in degrees east.

    Raises
    ------
    pydantic.ValidationError
        If an edge is outside the WGS 84 range or a minimum is not below its maximum.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_lat_deg: float = Field(
        ge=MIN_LATITUDE_DEG, le=MAX_LATITUDE_DEG, description="Southern edge (degrees north)."
    )
    max_lat_deg: float = Field(
        ge=MIN_LATITUDE_DEG, le=MAX_LATITUDE_DEG, description="Northern edge (degrees north)."
    )
    min_lon_deg: float = Field(
        ge=MIN_LONGITUDE_DEG, le=MAX_LONGITUDE_DEG, description="Western edge (degrees east)."
    )
    max_lon_deg: float = Field(
        ge=MIN_LONGITUDE_DEG, le=MAX_LONGITUDE_DEG, description="Eastern edge (degrees east)."
    )

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.min_lat_deg < self.max_lat_deg:
            raise ValueError("min_lat_deg must be below max_lat_deg")
        if not self.min_lon_deg < self.max_lon_deg:
            raise ValueError("min_lon_deg must be below max_lon_deg")
        return self

    def contains(self, lat_deg: float, lon_deg: float) -> bool:
        """Tell whether a point lies inside the box (edges included).

        Parameters
        ----------
        lat_deg : float
            Latitude in degrees north.
        lon_deg : float
            Longitude in degrees east.

        Returns
        -------
        bool
            ``True`` if the point is inside or on an edge.
        """
        return (
            self.min_lat_deg <= lat_deg <= self.max_lat_deg
            and self.min_lon_deg <= lon_deg <= self.max_lon_deg
        )


CZECH_REPUBLIC: Final = GeoBounds(
    min_lat_deg=CZECH_REPUBLIC_MIN_LAT_DEG,
    max_lat_deg=CZECH_REPUBLIC_MAX_LAT_DEG,
    min_lon_deg=CZECH_REPUBLIC_MIN_LON_DEG,
    max_lon_deg=CZECH_REPUBLIC_MAX_LON_DEG,
)
"""Bounding box of the Czech Republic (MIGRATION_PLAN WP-1.1: coordinates within the country)."""


class RegistrySettings(BaseModel):
    """Settings of the sensor registry (proposed configuration section ``registry``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_area: GeoBounds | None = Field(
        default=CZECH_REPUBLIC,
        description=(
            "Bounding box (degrees, WGS 84) every placement must lie in; catches swapped or "
            "mistyped coordinates. Default: the Czech Republic, rounded outward "
            "[to be verified]. null disables the check."
        ),
    )
