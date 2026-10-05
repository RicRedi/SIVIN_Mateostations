"""Sensors and their placement history (MIGRATION_PLAN §2.4).

A :class:`Sensor` carries its identity, descriptive fields and a non-empty, time-ordered history
of :class:`Placement` objects. The ``from`` instant of each placement is the deployment instant
and is the ground truth for the deployment detector. Both models are frozen; changing a sensor
means building a new one (see :meth:`Sensor.moved_to`).

The field aliases (``from``, ``to``, ``lat``, ``lon``) are the keys of the registry file
``sensors/sensors.geojson``; the Python attribute names carry the units.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    PlainValidator,
    WithJsonSchema,
    field_serializer,
    field_validator,
    model_validator,
)

from sivin.core.ids import SERIAL_DIGITS, SensorId
from sivin.registry.settings import (
    MAX_LATITUDE_DEG,
    MAX_LONGITUDE_DEG,
    MIN_LATITUDE_DEG,
    MIN_LONGITUDE_DEG,
)

logger = logging.getLogger(__name__)

SensorStatus = Literal["active", "inactive", "retired"]
"""Life-cycle state of a sensor.

``active``: deployed and measuring, its last placement is open. ``inactive``: temporarily out
(e.g. in service), the last placement may be open or closed. ``retired``: permanently out of
use, no placement is open.
"""

_UTC_SUFFIX: Final = "+00:00"
"""ISO 8601 offset of UTC as written by :meth:`datetime.isoformat`; written as ``Z``."""


def _to_sensor_id(value: object) -> SensorId:
    """Accept a :class:`SensorId` or its canonical 8-digit string (no other spelling)."""
    if isinstance(value, SensorId):
        return value
    if isinstance(value, str):
        return SensorId(value)
    raise ValueError(f"expected an {SERIAL_DIGITS}-digit string, got {type(value).__name__}")


SensorIdField = Annotated[
    SensorId,
    PlainValidator(_to_sensor_id),
    PlainSerializer(str, return_type=str),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": f"^[0-9]{{{SERIAL_DIGITS}}}$",
            "description": f"Canonical sensor id: the {SERIAL_DIGITS}-digit device serial.",
        }
    ),
]
"""A :class:`SensorId` that serialises as the canonical 8-digit string."""


def format_utc(instant: datetime) -> str:
    """Format an aware instant as ISO 8601 in UTC with the ``Z`` suffix.

    Parameters
    ----------
    instant : datetime.datetime
        Time-zone aware instant.

    Returns
    -------
    str
        E.g. ``"2025-12-01T00:00:00Z"``; fractional seconds only when present.
    """
    text = instant.astimezone(UTC).isoformat()
    return text.removesuffix(_UTC_SUFFIX) + "Z"


UTC_TIMESTAMP_PATTERN: Final = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$"
)
"""Text form of an instant in the registry file: ISO 8601 in UTC with ``Z``.

This is exactly what :func:`format_utc` writes; other offsets are rejected in the file so that
the JSON Schema (``pattern``) and the Python loader accept the same texts.
"""

_UTC_TIMESTAMP_REGEX: Final = re.compile(UTC_TIMESTAMP_PATTERN)


def _require_utc_text(value: object) -> object:
    """Reject a timestamp string that is not ISO 8601 UTC with ``Z``; pass other values on."""
    if isinstance(value, str) and _UTC_TIMESTAMP_REGEX.fullmatch(value) is None:
        raise ValueError(
            f"timestamp {value!r} must be ISO 8601 in UTC with 'Z', e.g. '2025-12-01T00:00:00Z'"
        )
    return value


UtcTimestamp = Annotated[
    AwareDatetime,
    BeforeValidator(_require_utc_text),
    WithJsonSchema({"type": "string", "format": "date-time", "pattern": UTC_TIMESTAMP_PATTERN}),
]
"""An aware datetime; as text it must be ISO 8601 UTC with ``Z`` (schema ``pattern``)."""


class Placement(BaseModel):
    """One placement of a sensor: where it stood from one instant to another.

    Parameters
    ----------
    from_utc : datetime.datetime
        Deployment instant (alias ``from``); any aware datetime in Python, stored in UTC. In
        the file it is text in ISO 8601 UTC with ``Z`` (:data:`UTC_TIMESTAMP_PATTERN`).
    to_utc : datetime.datetime or None
        End of the placement (alias ``to``), exclusive; ``None`` while it lasts.
    lon_deg : float
        Longitude in degrees east, WGS 84 (alias ``lon``).
    lat_deg : float
        Latitude in degrees north, WGS 84 (alias ``lat``).
    elevation_m : float or None
        Elevation in metres above sea level, if known.
    note : str or None
        Free text, e.g. where the placement data came from.

    Every parameter is required, also the nullable ones, because every key is present in the
    registry file (MIGRATION_PLAN §2.4) and the web contract (WP-3.1) relies on that.

    Raises
    ------
    pydantic.ValidationError
        If a datetime is naive, ``from_utc`` is not before ``to_utc`` or a coordinate is out of
        range.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True
    )

    from_utc: UtcTimestamp = Field(
        alias="from", description="Deployment instant, ISO 8601 in UTC with 'Z'."
    )
    to_utc: UtcTimestamp | None = Field(
        alias="to",
        description="End of the placement (exclusive), ISO 8601 UTC with 'Z'; null while open.",
    )
    lon_deg: float = Field(
        alias="lon",
        ge=MIN_LONGITUDE_DEG,
        le=MAX_LONGITUDE_DEG,
        allow_inf_nan=False,
        description="Longitude in degrees east (WGS 84).",
    )
    lat_deg: float = Field(
        alias="lat",
        ge=MIN_LATITUDE_DEG,
        le=MAX_LATITUDE_DEG,
        allow_inf_nan=False,
        description="Latitude in degrees north (WGS 84).",
    )
    elevation_m: float | None = Field(
        allow_inf_nan=False,
        description="Elevation in metres above sea level; null if unknown.",
    )
    note: str | None = Field(min_length=1, description="Free-text note (no unit); null if none.")

    @field_validator("from_utc", "to_utc")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else value.astimezone(UTC)

    @field_serializer("from_utc", "to_utc")
    def _serialize_instant(self, value: datetime | None) -> str | None:
        return None if value is None else format_utc(value)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.to_utc is not None and not self.from_utc < self.to_utc:
            raise ValueError(
                f"placement 'from' ({format_utc(self.from_utc)}) must be before "
                f"'to' ({format_utc(self.to_utc)})"
            )
        return self

    @property
    def is_open(self) -> bool:
        """Whether the placement lasts until now (``to`` is ``None``)."""
        return self.to_utc is None

    def contains(self, instant: datetime) -> bool:
        """Tell whether an instant falls into the placement, ``[from, to)``.

        Parameters
        ----------
        instant : datetime.datetime
            Time-zone aware instant.

        Returns
        -------
        bool
            ``True`` if ``from <= instant`` and (``to`` is ``None`` or ``instant < to``).
        """
        return self.from_utc <= instant and (self.to_utc is None or instant < self.to_utc)

    def closed_at(self, end_utc: datetime) -> Placement:
        """Return a copy of this placement that ends at ``end_utc``.

        Parameters
        ----------
        end_utc : datetime.datetime
            Time-zone aware end instant (exclusive).

        Returns
        -------
        Placement
            The closed placement.

        Raises
        ------
        pydantic.ValidationError
            If ``end_utc`` is naive or not after ``from``.
        """
        return self.model_validate(dict(self) | {"to_utc": end_utc})


class Sensor(BaseModel):
    """A sensor of the registry with its placement history.

    Parameters
    ----------
    id : SensorId or str
        Canonical id, the 8-digit serial (written as a string).
    portal_name : str
        Device name in the provider's portal, e.g. ``"8615620 77678271"``; must contain the id.
    label : str
        Human-readable name, e.g. the GPX waypoint name ``"77678271 (VUT)"``.
    site : str or None
        Vineyard or site name.
    variety : str or None
        Grape variety at the sensor.
    status : {"active", "inactive", "retired"}
        Life-cycle state, see :data:`SensorStatus`.
    placements : tuple of Placement
        Non-empty placement history in time order.
    notes : str or None
        Free text.

    Every parameter is required, also the nullable ones (pass ``None``), as in the file.

    Raises
    ------
    pydantic.ValidationError
        If the placements are unsorted or overlap, an open placement is not the last one,
        ``portal_name`` names another serial, or ``status`` contradicts the placements.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True
    )

    id: SensorIdField = Field(description="Canonical id: the 8-digit device serial number.")
    portal_name: str = Field(
        min_length=1,
        description="Device name in the provider's portal, e.g. '8615620 77678271'.",
    )
    label: str = Field(min_length=1, description="Human-readable name, e.g. '77678271 (VUT)'.")
    site: str | None = Field(min_length=1, description="Vineyard or site name; null if unknown.")
    variety: str | None = Field(
        min_length=1, description="Grape variety at the sensor; null if unknown."
    )
    status: SensorStatus = Field(description="Life-cycle state: active, inactive or retired.")
    placements: tuple[Placement, ...] = Field(
        min_length=1, description="Placement history in time order; only the last may be open."
    )
    notes: str | None = Field(min_length=1, description="Free text; null if none.")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        self._check_placement_history()
        self._check_portal_name()
        self._check_status()
        return self

    def _check_placement_history(self) -> None:
        for index, (earlier, later) in enumerate(
            zip(self.placements, self.placements[1:], strict=False)
        ):
            if earlier.to_utc is None:
                raise ValueError(
                    f"placement {index} of sensor {self.id} is open (to = null) but is not the "
                    "last one; close it at the 'from' of the next placement"
                )
            if not earlier.from_utc < later.from_utc:
                raise ValueError(
                    f"placements of sensor {self.id} are not sorted by 'from' "
                    f"(placement {index + 1} starts at {format_utc(later.from_utc)})"
                )
            if earlier.to_utc > later.from_utc:
                raise ValueError(
                    f"placements {index} and {index + 1} of sensor {self.id} overlap: "
                    f"{format_utc(earlier.to_utc)} > {format_utc(later.from_utc)}"
                )

    def _check_portal_name(self) -> None:
        try:
            named = SensorId.parse(self.portal_name)
        except ValueError as error:
            raise ValueError(f"portal_name {self.portal_name!r}: {error}") from error
        if named != self.id:
            raise ValueError(
                f"portal_name {self.portal_name!r} names sensor {named}, not {self.id}"
            )

    def _check_status(self) -> None:
        last_open = self.placements[-1].is_open
        if self.status == "active" and not last_open:
            raise ValueError(
                f"sensor {self.id} is active but its last placement is closed; "
                "set status 'inactive' or 'retired', or reopen the placement"
            )
        if self.status == "retired" and last_open:
            raise ValueError(
                f"sensor {self.id} is retired but its last placement is open; set its 'to'"
            )

    @property
    def is_active(self) -> bool:
        """Whether the sensor's status is ``active``."""
        return self.status == "active"

    @property
    def current_placement(self) -> Placement | None:
        """The open placement (``to`` is ``None``), or ``None`` if the sensor is not placed."""
        last = self.placements[-1]
        return last if last.is_open else None

    @property
    def last_placement(self) -> Placement:
        """The most recent placement, open or closed (its point is the map position)."""
        return self.placements[-1]

    @property
    def deployed_since(self) -> datetime:
        """The ``from`` instant (UTC) of the first placement."""
        return self.placements[0].from_utc

    def placement_at(self, instant: datetime) -> Placement | None:
        """Return the placement in force at an instant.

        Parameters
        ----------
        instant : datetime.datetime
            Time-zone aware instant (a :class:`pandas.Timestamp` with a zone works too).

        Returns
        -------
        Placement or None
            The placement with ``from <= instant < to``; ``None`` before the first deployment,
            between two placements or after the last one ended.

        Raises
        ------
        ValueError
            If ``instant`` is naive.
        """
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError(f"placement_at needs a time-zone aware instant, got {instant!r}")
        return next((p for p in self.placements if p.contains(instant)), None)

    def moved_to(self, placement: Placement) -> Sensor:
        """Return this sensor with a new placement appended.

        An open placement is closed at the new placement's ``from`` instant first. An
        ``inactive`` sensor that moves to an open placement becomes ``active`` (it is back in
        the field); otherwise the status is kept. A retired sensor cannot be moved.

        Parameters
        ----------
        placement : Placement
            The new placement; it must start after the current one.

        Returns
        -------
        Sensor
            The moved sensor.

        Raises
        ------
        ValueError
            If the sensor is retired.
        pydantic.ValidationError
            If the new placement does not fit after the existing history.
        """
        if self.status == "retired":
            raise ValueError(
                f"sensor {self.id} is retired and cannot be moved; set its status first if it "
                "returns to use"
            )
        history = list(self.placements)
        if history[-1].is_open:
            history[-1] = history[-1].closed_at(placement.from_utc)
        logger.debug("Moving sensor %s from %s", self.id, format_utc(placement.from_utc))
        status = "active" if self.status == "inactive" and placement.is_open else self.status
        return self.replaced(placements=(*history, placement), status=status)

    def replaced(self, **changes: object) -> Sensor:
        """Return a validated copy with some fields changed.

        Parameters
        ----------
        **changes : object
            Field names (Python names, e.g. ``status``) and new values.

        Returns
        -------
        Sensor
            The new sensor; all rules are checked again.

        Raises
        ------
        pydantic.ValidationError
            If the result violates a rule or a field name is unknown.
        """
        return self.model_validate(dict(self) | changes)
