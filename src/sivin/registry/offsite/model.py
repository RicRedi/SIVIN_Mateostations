"""Off-site periods and the validated log (MIGRATION_PLAN §2.8).

:class:`OffSitePeriod` is one entry of ``sensors/offsite_log.yaml``: sensor, ``from``, ``to``
(``open`` or ``null`` while the sensor is still off site; a blank ``to:`` is an error), reason
and note, with times stored in UTC. :class:`OffSiteLog` is the validated, immutable collection:
known sensors only, no overlaps per sensor, at most one open period per sensor and it must be
the last.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from itertools import pairwise
from typing import Annotated, Literal, Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    PlainValidator,
    ValidationInfo,
    WithJsonSchema,
    field_serializer,
    field_validator,
    model_validator,
)

from sivin.core.defaults import DEFAULT_TIMEZONE
from sivin.core.ids import SERIAL_DIGITS, SensorId
from sivin.core.schema import MeasurementSeries
from sivin.registry.model import format_utc
from sivin.registry.offsite.local_time import (
    JSON_TIME_PATTERN,
    LocalTimeReader,
    format_local,
    timezone_of,
)
from sivin.registry.offsite.messages import (
    BLANK_HINTS,
    OPEN_END,
    OffSiteLogError,
    report,
    unknown_sensor_message,
)
from sivin.registry.offsite.strict_yaml import BlankValue
from sivin.registry.registry import SensorRegistry

OffSiteReason = Literal["office", "service", "transport", "storage", "other"]
"""Why a sensor was not in the vineyard (the ``reason`` of an entry)."""


def _to_sensor_id(value: object) -> SensorId:
    """Accept a :class:`SensorId`, any spelling :meth:`SensorId.parse` recognises or an int."""
    if isinstance(value, SensorId):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if isinstance(value, str):
        return SensorId.parse(value)
    raise ValueError(
        f"expected a sensor name, got {type(value).__name__}; write the serial in quotes, "
        'e.g. sensor: "77799986"'
    )


AnySensorName = Annotated[
    SensorId,
    PlainValidator(_to_sensor_id),
    PlainSerializer(str, return_type=str),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 1,
            "description": (
                f"Sensor: the {SERIAL_DIGITS}-digit serial or any known spelling of its name "
                "('8615620 77799986', '77799986 (VUT)', legacy short name if unique)."
            ),
        }
    ),
]
"""A sensor named in the log; resolved to its canonical :class:`SensorId`."""

LogTime = Annotated[
    AwareDatetime,
    WithJsonSchema({"type": "string", "pattern": JSON_TIME_PATTERN}),
]
"""A ``from`` / ``to`` value: local time or ISO 8601 with offset in the file, UTC in Python."""

LogEndTime = Annotated[
    AwareDatetime | None,
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "string", "pattern": JSON_TIME_PATTERN},
                {"const": OPEN_END},
                {"type": "null"},
            ]
        }
    ),
]
"""The ``to`` value: a time as :data:`LogTime`, or ``open`` / ``null`` for an open period."""


class OffSitePeriod(BaseModel):
    """One entry of the off-site log: a period when a sensor was not in the vineyard.

    The period is half-open: ``from <= t < to``.

    Parameters
    ----------
    sensor : SensorId
        The sensor; text in any spelling :meth:`SensorId.parse` recognises.
    from_utc : datetime.datetime
        Start (alias ``from``), inclusive. Local wall-clock time ``YYYY-MM-DD HH:MM`` of the
        zone in the validation context (key :data:`TIMEZONE_CONTEXT_KEY`, default
        Europe/Prague) or ISO 8601 with an offset or ``Z``; stored in UTC.
    to_utc : datetime.datetime or None
        End (alias ``to``), exclusive, same formats; ``open`` (or ``null``) while the sensor
        is still off site, stored as ``None``. The key is required and a blank value
        (:class:`BlankValue`) is rejected, so an open end is always written on purpose.
    reason : {"office", "service", "transport", "storage", "other"}
        Why the sensor was not in the vineyard.
    note : str or None
        Free text, optional.

    Raises
    ------
    pydantic.ValidationError
        If a time cannot be read, is ambiguous or nonexistent locally, or ``from >= to``.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True
    )

    sensor: AnySensorName = Field(description="The sensor (any known spelling of its name).")
    from_utc: LogTime = Field(
        alias="from",
        description=(
            "Start, inclusive: local time 'YYYY-MM-DD HH:MM' (Europe/Prague unless configured "
            "otherwise) or ISO 8601 with an offset or 'Z'."
        ),
    )
    to_utc: LogEndTime = Field(
        alias="to",
        description=(
            f"End, exclusive, same formats as 'from'; '{OPEN_END}' (or null) while still off site."
        ),
    )
    reason: OffSiteReason = Field(
        description="Why the sensor was not in the vineyard: office, service, transport, "
        "storage or other."
    )
    note: str | None = Field(None, min_length=1, description="Free-text note (optional).")

    @field_validator("sensor", "reason", "note", mode="before")
    @classmethod
    def _not_blank(cls, value: object, info: ValidationInfo) -> object:
        _reject_blank(value, info)
        return value

    @field_validator("from_utc", "to_utc", mode="before")
    @classmethod
    def _read_time(cls, value: object, info: ValidationInfo) -> datetime | None:
        _reject_blank(value, info)
        if value is None:
            if info.field_name == "from_utc":
                raise ValueError(BLANK_HINTS["from"])
            return None
        is_open_word = isinstance(value, str) and value.strip().lower() == OPEN_END
        if info.field_name == "to_utc" and is_open_word:
            return None
        return LocalTimeReader(timezone_of(info)).read(value)

    @field_serializer("from_utc", "to_utc")
    def _serialize_instant(self, value: datetime | None) -> str | None:
        return None if value is None else format_utc(value)

    @model_validator(mode="after")
    def _ordered(self, info: ValidationInfo) -> Self:
        if self.to_utc is not None and not self.from_utc < self.to_utc:
            zone = timezone_of(info)
            raise ValueError(
                f"'from' ({format_local(self.from_utc, zone)}) must be before 'to' "
                f"({format_local(self.to_utc, zone)}); swap or correct the times"
            )
        return self

    @property
    def is_open(self) -> bool:
        """``True`` while the sensor is still off site (no ``to``)."""
        return self.to_utc is None

    @property
    def detail(self) -> str:
        """``"<reason>: <note>"`` (or just the reason), the ``detail`` of the site event."""
        return self.reason if self.note is None else f"{self.reason}: {self.note}"

    def contains(self, instant: datetime | pd.Timestamp) -> bool:
        """Tell whether an instant lies in the period (``from <= t < to``).

        Parameters
        ----------
        instant : datetime.datetime or pandas.Timestamp
            Timezone-aware instant.

        Returns
        -------
        bool
            ``True`` inside the period.

        Raises
        ------
        ValueError
            If the instant is naive.
        """
        t_utc = _aware_utc(instant)
        end = self.end_ts
        return self.start_ts <= t_utc and (end is None or t_utc < end)

    def overlaps(self, start: datetime | pd.Timestamp, end: datetime | pd.Timestamp) -> bool:
        """Tell whether the period shares at least one instant with ``[start, end]``.

        Parameters
        ----------
        start, end : datetime.datetime or pandas.Timestamp
            Timezone-aware bounds, both inclusive.

        Returns
        -------
        bool
            ``True`` if some instant ``t`` with ``start <= t <= end`` lies in the period.
        """
        start_utc, end_utc = _aware_utc(start), _aware_utc(end)
        period_end = self.end_ts
        return self.start_ts <= end_utc and (period_end is None or period_end > start_utc)

    def mask(self, t_ns: npt.NDArray[np.int64]) -> npt.NDArray[np.bool_]:
        """Tell for each sample time whether it lies in the period.

        Parameters
        ----------
        t_ns : numpy.ndarray of int64
            Sample times in nanoseconds since the Unix epoch (UTC).

        Returns
        -------
        numpy.ndarray of bool
            ``True`` where ``from <= t < to``.
        """
        inside = t_ns >= self.start_ts.value
        end = self.end_ts
        if end is not None:
            inside &= t_ns < end.value
        return np.asarray(inside, dtype=np.bool_)

    @property
    def start_ts(self) -> pd.Timestamp:
        """``from`` as a UTC :class:`pandas.Timestamp` (nanoseconds)."""
        return pd.Timestamp(self.from_utc).as_unit("ns")

    @property
    def end_ts(self) -> pd.Timestamp | None:
        """``to`` as a UTC :class:`pandas.Timestamp` (nanoseconds); ``None`` while open."""
        return None if self.to_utc is None else pd.Timestamp(self.to_utc).as_unit("ns")


def _reject_blank(value: object, info: ValidationInfo) -> None:
    """Raise with a hint if a key was written without a value (or as empty text)."""
    if isinstance(value, BlankValue) or (isinstance(value, str) and not value.strip()):
        key = {"from_utc": "from", "to_utc": "to"}.get(info.field_name or "", info.field_name)
        raise ValueError(BLANK_HINTS.get(key or "", "is empty"))


def _aware_utc(instant: datetime | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(instant)
    if timestamp.tz is None:
        raise ValueError(f"instant must be timezone-aware, got {instant!r}")
    return timestamp.tz_convert("UTC")


class OffSiteLogFile(BaseModel):
    """The whole off-site log file: ``entries``, a list of :class:`OffSitePeriod`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[OffSitePeriod, ...] = Field(
        description="Periods when a sensor was not in the vineyard; may be empty."
    )


class OffSiteLog:
    """Validated, immutable collection of off-site periods.

    Rules: every sensor is in the registry; per sensor the periods do not overlap (touching
    is allowed: one may end exactly when the next starts); at most one period per sensor is
    open and it is the last one of that sensor.

    Parameters
    ----------
    periods : iterable of OffSitePeriod
        The periods in file order.
    registry : SensorRegistry
        The sensor registry the sensors are checked against.
    timezone : str, optional
        IANA zone in which times are shown in error messages (the log's zone).
    labels : sequence of str, optional
        How error messages name each period, e.g. ``"entry #3 (line 12)"``; default
        ``"entry #N"`` (1-based position in ``periods``).

    Raises
    ------
    OffSiteLogError
        If a rule is violated; the message names the offending entries and how to fix them.
    """

    __slots__ = ("_by_sensor", "_periods")

    def __init__(
        self,
        periods: Iterable[OffSitePeriod],
        registry: SensorRegistry,
        *,
        timezone: str = DEFAULT_TIMEZONE,
        labels: Sequence[str] | None = None,
    ) -> None:
        self._periods: tuple[OffSitePeriod, ...] = tuple(periods)
        names = list(labels) if labels is not None else []
        names += [f"entry #{index + 1}" for index in range(len(names), len(self._periods))]
        problems = [
            f"{names[index]}, 'sensor': {unknown_sensor_message(str(period.sensor), registry)}"
            for index, period in enumerate(self._periods)
            if period.sensor not in registry
        ]
        indexed: dict[SensorId, list[tuple[str, OffSitePeriod]]] = {}
        for index, period in enumerate(self._periods):
            indexed.setdefault(period.sensor, []).append((names[index], period))
        by_sensor: dict[SensorId, tuple[OffSitePeriod, ...]] = {}
        for sensor_id, entries in indexed.items():
            entries.sort(key=lambda entry: entry[1].from_utc)
            problems += _sequence_problems(entries, timezone)
            by_sensor[sensor_id] = tuple(period for _, period in entries)
        if problems:
            raise OffSiteLogError(report(problems))
        self._by_sensor = by_sensor

    @classmethod
    def empty(cls) -> Self:
        """Return a log without periods (every sensor measures in the vineyard).

        Returns
        -------
        OffSiteLog
            The empty log.
        """
        return cls((), SensorRegistry())

    def __iter__(self) -> Iterator[OffSitePeriod]:
        return iter(self._periods)

    def __len__(self) -> int:
        return len(self._periods)

    def __repr__(self) -> str:
        return f"OffSiteLog(periods={len(self)}, sensors={len(self._by_sensor)})"

    def sensors(self) -> tuple[SensorId, ...]:
        """Return the sensors that have at least one period, sorted.

        Returns
        -------
        tuple of SensorId
            Sensor ids.
        """
        return tuple(sorted(self._by_sensor))

    def periods_for(self, sensor_id: SensorId) -> tuple[OffSitePeriod, ...]:
        """Return the periods of one sensor in time order.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.

        Returns
        -------
        tuple of OffSitePeriod
            Its periods; empty if it has none.
        """
        return self._by_sensor.get(sensor_id, ())

    def is_off_site(self, sensor_id: SensorId, instant: datetime | pd.Timestamp) -> bool:
        """Tell whether a sensor was off site at an instant.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.
        instant : datetime.datetime or pandas.Timestamp
            Timezone-aware instant.

        Returns
        -------
        bool
            ``True`` if a period of the sensor contains the instant.

        Raises
        ------
        ValueError
            If the instant is naive.
        """
        return any(period.contains(instant) for period in self.periods_for(sensor_id))

    def mask(self, series: MeasurementSeries) -> npt.NDArray[np.bool_]:
        """Tell for each row of a series whether it was recorded off site.

        Parameters
        ----------
        series : MeasurementSeries
            Measurements of one sensor.

        Returns
        -------
        numpy.ndarray of bool
            One value per row, ``True`` inside a period of ``series.sensor_id``
            (``from <= t < to``).
        """
        t_ns = series.timestamps.to_numpy(dtype="datetime64[ns]").view(np.int64)
        inside = np.zeros(len(series), dtype=np.bool_)
        for period in self.periods_for(series.sensor_id):
            inside |= period.mask(t_ns)
        return inside


def _sequence_problems(entries: Sequence[tuple[str, OffSitePeriod]], timezone: str) -> list[str]:
    """Overlaps and misplaced open periods of one sensor's entries, sorted by ``from``."""
    problems: list[str] = []
    for (label, period), (next_label, following) in pairwise(entries):
        if period.to_utc is None:
            problems.append(
                f"{label}, 'to': sensor {period.sensor} has an open period ('to: {OPEN_END}') "
                f"that is not its last one ({next_label} starts "
                f"{format_local(following.from_utc, timezone)}); write the end time into "
                f"{label} or remove the later entry"
            )
        elif period.to_utc > following.from_utc:
            problems.append(
                f"{next_label}, 'from': the period of sensor {period.sensor} starting "
                f"{format_local(following.from_utc, timezone)} overlaps {label} "
                f"({format_local(period.from_utc, timezone)} - "
                f"{format_local(period.to_utc, timezone)}); periods of one sensor must not "
                "overlap - correct the times or merge the two entries"
            )
    return problems
