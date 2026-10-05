"""Value objects passed between the site builder and its writers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from sivin.core.daily import DailyWeather
from sivin.core.ids import SensorId
from sivin.quality.pipeline import QualityResult
from sivin.site.labels import IndexSpec

IndexEntries = Mapping[str, Mapping[str, Any]]
"""Index id → published index entry (``value``, ``unit``, ...) of one sensor and season."""


@dataclass(frozen=True, slots=True)
class SensorData:
    """The quality-controlled data of one sensor, ready to be written.

    Attributes
    ----------
    sensor_id : SensorId
        The sensor.
    result : QualityResult
        QC result over the sensor's whole stored record (flags set, values set aside).
    daily : DailyWeather
        Daily aggregates of :attr:`result` (local days of the display time zone).
    """

    sensor_id: SensorId
    result: QualityResult
    daily: DailyWeather


@dataclass(frozen=True, slots=True)
class LatestSample:
    """The last valid sample of a sensor (``latest.json`` without ``stale``).

    Attributes
    ----------
    t : int
        Time in Unix seconds (UTC).
    temp_c : float or None
        Temperature in °C (rounded).
    rh_pct : float or None
        Relative humidity in % (rounded).
    qc : int
        QC flags of the sample (informative flags only; it is valid).
    """

    t: int
    temp_c: float | None
    rh_pct: float | None
    qc: int


@dataclass(frozen=True, slots=True)
class SensorSummary:
    """What the site-wide files need to know about one published sensor.

    Attributes
    ----------
    first_t, last_t : int
        First and last sample time in Unix seconds (UTC).
    raw_months : tuple of str
        UTC months with a raw file, ``YYYY-MM``, increasing.
    latest : LatestSample or None
        The last valid sample; ``None`` if the sensor has none (e.g. always off site).
    years : tuple of int
        Calendar years (display time zone) from the first to the last sample.
    """

    first_t: int
    last_t: int
    raw_months: tuple[str, ...]
    latest: LatestSample | None
    years: tuple[int, ...]

    def to_state(self) -> dict[str, Any]:
        """Return the summary as JSON data for the build state.

        Returns
        -------
        dict
            All fields; ``latest`` as a mapping or ``None``.
        """
        latest = self.latest
        return {
            "first_t": self.first_t,
            "last_t": self.last_t,
            "raw_months": list(self.raw_months),
            "latest": None
            if latest is None
            else {"t": latest.t, "temp_c": latest.temp_c, "rh_pct": latest.rh_pct, "qc": latest.qc},
            "years": list(self.years),
        }

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> SensorSummary:
        """Rebuild a summary from :meth:`to_state` data.

        Parameters
        ----------
        data : Mapping
            Output of :meth:`to_state`.

        Returns
        -------
        SensorSummary
            The summary.

        Raises
        ------
        KeyError, TypeError, ValueError
            If the data are malformed.
        """
        latest = data["latest"]
        return cls(
            first_t=int(data["first_t"]),
            last_t=int(data["last_t"]),
            raw_months=tuple(str(month) for month in data["raw_months"]),
            latest=None
            if latest is None
            else LatestSample(
                int(latest["t"]), latest["temp_c"], latest["rh_pct"], int(latest["qc"])
            ),
            years=tuple(int(year) for year in data["years"]),
        )


@dataclass(frozen=True, slots=True)
class PublishedSensor:
    """A sensor of the site with its registry status and summary.

    Attributes
    ----------
    sensor_id : SensorId
        The sensor.
    status : str
        Registry life-cycle state: ``active``, ``inactive`` or ``retired``.
    summary : SensorSummary
        Its data availability and latest sample.
    indices : Mapping of int to IndexEntries
        Season → index id → published entry.
    failed : bool
        The sensor failed in this build; its files are those of an earlier build.
    last_built_at : str or None
        For a failed sensor: ``generated_at`` of its last successful build (ISO 8601 UTC).
    """

    sensor_id: SensorId
    status: str
    summary: SensorSummary
    indices: Mapping[int, IndexEntries] = field(default_factory=dict)
    failed: bool = False
    last_built_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "indices", MappingProxyType(dict(self.indices)))


@dataclass(frozen=True, slots=True)
class SiteSnapshot:
    """Everything the site-wide files are written from.

    Attributes
    ----------
    generated_at : datetime.datetime
        Time of the build (aware).
    display_timezone : str
        IANA zone of the local days (``time.display_timezone``).
    sensors : tuple of PublishedSensor
        The published sensors, sorted by id.
    seasons : tuple of int
        The seasons with an indices file, increasing.
    indices : tuple of IndexSpec
        The indices listed in the manifest, sorted by id.
    registry : bytes
        The sensor registry file, published unchanged as ``sensors.geojson``.
    """

    generated_at: datetime
    display_timezone: str
    sensors: tuple[PublishedSensor, ...]
    seasons: tuple[int, ...]
    indices: tuple[IndexSpec, ...]
    registry: bytes
