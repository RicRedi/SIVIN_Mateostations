"""SYNTHETIC test data for quality control. Nothing here is a measurement of a real sensor.

The generator builds deterministic (seeded) series that imitate the vineyard sensors:

* irregular sampling around 1825 s with random jitter, values rounded to 0.1,
* **outdoor** phases (:class:`Weather`): seasonal mean (about -0.5 °C in January, 20.5 °C in
  July) + a daily synoptic AR(1) anomaly + a diurnal cycle whose range depends on the season
  and on a day-to-day (Markov) cloudiness (clear: 8-15 °C, overcast: a quarter of it) + AR(1)
  sample noise; daily mean relative humidity depends on season and cloudiness, the diurnal
  humidity cycle is anti-correlated with temperature, clipped to 0-100 %; optional fog or
  inversion episodes (humidity about 99 %, tiny temperature range), heat waves and fronts,
* **indoor** phases (:class:`Office`): a room with day-time heating on weekdays (local time
  Europe/Prague), thermal inertia and steady humidity; variants from 12 °C (unheated) to
  30 °C (hot) and a humid room,
* **car** phases: a short hot or cold transient between office and vineyard.

Helpers inject spikes, steps, ramps (fronts), stuck periods, missing values and gaps. All
numbers are invented for tests and chosen to look plausible for South Moravia.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

FloatArray = npt.NDArray[np.float64]

SENSOR = SensorId("77678271")
"""A real serial number used as identity only; the data attached to it are synthetic."""

START_UTC = pd.Timestamp("2026-04-01T00:00:00Z")
INTERVAL_S = 1825.0
JITTER_S = 20.0
DAY_S = 86_400.0
YEAR_DAYS = 365.25
LOCAL_ZONE = "Europe/Prague"

ANNUAL_MEAN_C = 10.0
ANNUAL_AMPLITUDE_C = 10.5
COLDEST_DAY_OF_YEAR = 15.0
SYNOPTIC_SIGMA_C = 3.0
SYNOPTIC_PHI = 0.7
CLEAR_RANGE_WINTER_C = 8.0
CLEAR_RANGE_SUMMER_EXTRA_C = 7.0
OVERCAST_RANGE_REDUCTION = 0.75
WARMEST_HOUR_UTC = 13.0
NOISE_PHI = 0.9
NOISE_SIGMA_C = 0.3
RH_WINTER_PCT = 85.0
RH_SUMMER_DROP_PCT = 18.0
RH_PER_CLOUDINESS_PCT = 12.0
RH_PER_C = -3.0
RH_NOISE_PCT = 1.5
FOG_RH_PCT = 99.0
FOG_RANGE_C = 1.2
HEAT_WAVE_RH_DROP_PCT = 15.0
EPISODE_EDGE_H = 6.0
FRONT_HOLD_DAYS = 3.0
FRONT_RECOVERY_DAYS = 2.0


@dataclass(frozen=True)
class Weather:
    """Outdoor weather options of a phase (times in days since the start of the trace).

    Attributes
    ----------
    cloudiness : float or None
        Fixed cloudiness 0 (clear) to 1 (overcast); ``None`` for day-to-day Markov cloudiness.
    fog : tuple of (start_day, end_day, temp_c)
        Fog or inversion episodes at about ``temp_c`` with humidity about 99 %.
    heat_waves : tuple of (start_day, end_day, delta_c)
        Episodes ``delta_c`` warmer and 15 % drier.
    fronts : tuple of (day, delta_c, duration_h)
        Temperature change by ``delta_c`` within ``duration_h``, held for 3 days.
    """

    cloudiness: float | None = None
    fog: tuple[tuple[float, float, float], ...] = ()
    heat_waves: tuple[tuple[float, float, float], ...] = ()
    fronts: tuple[tuple[float, float, float], ...] = ()


@dataclass(frozen=True)
class Office:
    """An indoor room: base temperature, weekday day-time heating and steady humidity."""

    level_c: float = 21.0
    heating_c: float = 1.5
    rh_pct: float = 40.0
    noise_c: float = 0.15


OFFICES = {
    "standard": Office(),
    "unheated": Office(level_c=12.0, heating_c=0.5, rh_pct=55.0),
    "cool": Office(level_c=16.0, heating_c=2.0, rh_pct=50.0),
    "warm": Office(level_c=27.0, heating_c=1.5, rh_pct=55.0),
    "hot": Office(level_c=30.0, heating_c=2.0, rh_pct=50.0),
    "humid": Office(level_c=22.0, heating_c=1.0, rh_pct=68.0),
}
"""Office variants used by the acceptance tests."""

Phase = tuple[str, float] | tuple[str, float, Weather | Office | float]
"""``(kind, days)`` or ``(kind, days, options)``; kind ``indoor``, ``outdoor`` or ``car``."""


@dataclass(frozen=True)
class Trace:
    """Synthetic raw columns that can be modified and turned into a series.

    Attributes
    ----------
    t_s : numpy.ndarray of float
        Sample times in seconds since the Unix epoch.
    temp_c, rh_pct : numpy.ndarray of float
        Values in °C and %.
    boundaries : tuple of int
        Positions of the first sample of each phase after the first.
    """

    t_s: FloatArray
    temp_c: FloatArray
    rh_pct: FloatArray
    boundaries: tuple[int, ...] = field(default=())

    def __len__(self) -> int:
        return int(self.t_s.size)

    def series(self, sensor_id: SensorId = SENSOR) -> MeasurementSeries:
        """Return the trace as a validated series."""
        times = pd.to_datetime(np.round(self.t_s * 1e9).astype(np.int64), unit="ns", utc=True)
        return MeasurementSeries.from_records(sensor_id, times, self.temp_c, self.rh_pct)

    def timestamp(self, position: int) -> pd.Timestamp:
        """Return the UTC time of one sample."""
        return pd.Timestamp(round(self.t_s[position] * 1e9), unit="ns", tz="UTC")

    def with_spike(self, position: int, delta_c: float = 0.0, delta_pct: float = 0.0) -> Trace:
        """Add ``delta`` to one sample only."""
        temp, rh = self.temp_c.copy(), self.rh_pct.copy()
        temp[position] += delta_c
        rh[position] += delta_pct
        return replace(self, temp_c=temp, rh_pct=rh)

    def with_step(self, position: int, delta_c: float) -> Trace:
        """Add ``delta_c`` to every temperature from ``position`` on."""
        temp = self.temp_c.copy()
        temp[position:] += delta_c
        return replace(self, temp_c=temp)

    def with_ramp(self, position: int, delta_c: float, duration_s: float) -> Trace:
        """Change the temperature linearly by ``delta_c`` over ``duration_s`` and keep it."""
        elapsed = np.clip((self.t_s - self.t_s[position]) / duration_s, 0.0, 1.0)
        return replace(self, temp_c=self.temp_c + delta_c * elapsed)

    def with_stuck(self, start: int, stop: int, rh: bool = False) -> Trace:
        """Repeat the value at ``start`` for rows ``[start, stop)``."""
        temp, rh_values = self.temp_c.copy(), self.rh_pct.copy()
        if rh:
            rh_values[start:stop] = rh_values[start]
        else:
            temp[start:stop] = temp[start]
        return replace(self, temp_c=temp, rh_pct=rh_values)

    def with_missing(self, positions: Sequence[int], rh_only: bool = False) -> Trace:
        """Set values to NaN."""
        temp, rh = self.temp_c.copy(), self.rh_pct.copy()
        rh[list(positions)] = np.nan
        if not rh_only:
            temp[list(positions)] = np.nan
        return replace(self, temp_c=temp, rh_pct=rh)

    def since(self, position: int) -> Trace:
        """Rows from ``position`` on (boundaries shifted, earlier ones dropped)."""
        bounds = tuple(b - position for b in self.boundaries if b > position)
        return Trace(self.t_s[position:], self.temp_c[position:], self.rh_pct[position:], bounds)

    def without_rows(self, start: int, stop: int) -> Trace:
        """Drop rows ``[start, stop)`` (a gap); boundaries are not adjusted."""
        keep = np.r_[0:start, stop : len(self)]
        return replace(self, t_s=self.t_s[keep], temp_c=self.temp_c[keep], rh_pct=self.rh_pct[keep])


class SyntheticSensor:
    """Seeded generator of synthetic traces made of indoor, car and outdoor phases.

    Parameters
    ----------
    seed : int
        Seed of the random generator.
    start_utc : pandas.Timestamp
        Time of the first sample.
    """

    def __init__(self, seed: int, start_utc: pd.Timestamp = START_UTC) -> None:
        self._rng = np.random.default_rng(seed)
        self._start_s = start_utc.value / 1e9

    def times(self, n_samples: int) -> FloatArray:
        """Irregular sample times: 1825 s ± uniform jitter of 20 s."""
        steps = INTERVAL_S + self._rng.uniform(-JITTER_S, JITTER_S, n_samples)
        steps[0] = 0.0
        return self._start_s + np.cumsum(steps)

    def trace(self, phases: Sequence[Phase]) -> Trace:
        """Build a trace from phases (see :data:`Phase`)."""
        n_per_phase = [max(round(p[1] * DAY_S / INTERVAL_S), 1) for p in phases]
        t_s = self.times(sum(n_per_phase))
        temp, rh = np.empty_like(t_s), np.empty_like(t_s)
        boundaries: list[int] = []
        start = 0
        for phase, n_samples in zip(phases, n_per_phase, strict=True):
            kind, options = phase[0], phase[2] if len(phase) == 3 else None
            part = slice(start, start + n_samples)
            if kind == "outdoor":
                weather = options if isinstance(options, Weather) else Weather()
                phase_temp, phase_rh = self.outdoor(t_s, weather)
                temp[part], rh[part] = phase_temp[part], phase_rh[part]
            elif kind == "indoor":
                office = options if isinstance(options, Office) else Office()
                temp[part], rh[part] = self.indoor(t_s[part], office)
            else:
                car_c = float(options) if isinstance(options, int | float) else 40.0
                temp[part] = car_c + self._rng.normal(0.0, 0.5, n_samples)
                rh[part] = 20.0
            if start:
                boundaries.append(start)
            start += n_samples
        return Trace(
            t_s, np.round(temp, 1), np.round(np.clip(rh, 0.0, 100.0), 1), tuple(boundaries)
        )

    def outdoor(self, t_s: FloatArray, weather: Weather) -> tuple[FloatArray, FloatArray]:
        """Outdoor temperature (°C) and relative humidity (%) at times ``t_s``."""
        days = (t_s - t_s[0]) / DAY_S
        day_of_year = (t_s - pd.Timestamp("2026-01-01T00:00:00Z").value / 1e9) / DAY_S
        season = 0.5 - 0.5 * np.cos(2 * np.pi * (day_of_year - COLDEST_DAY_OF_YEAR) / YEAR_DAYS)
        mean_c = ANNUAL_MEAN_C - ANNUAL_AMPLITUDE_C * np.cos(
            2 * np.pi * (day_of_year - COLDEST_DAY_OF_YEAR) / YEAR_DAYS
        )
        n_days = int(days[-1]) + 2
        anomaly = np.interp(days, np.arange(n_days) + 0.5, self._daily_ar1(n_days))
        cloud = self._cloudiness(n_days, weather.cloudiness)[days.astype(int)]
        daily_range = (CLEAR_RANGE_WINTER_C + CLEAR_RANGE_SUMMER_EXTRA_C * season) * (
            1 - OVERCAST_RANGE_REDUCTION * cloud
        )
        hour = (t_s % DAY_S) / 3600.0
        diurnal = 0.5 * daily_range * np.cos(2 * np.pi * (hour - WARMEST_HOUR_UTC) / 24.0)
        noise = self._ar1(t_s.size, NOISE_SIGMA_C * np.sqrt(1 - NOISE_PHI**2), NOISE_PHI)
        temp = mean_c + anomaly + diurnal + noise
        rh_mean = (
            RH_WINTER_PCT - RH_SUMMER_DROP_PCT * season + RH_PER_CLOUDINESS_PCT * (cloud - 0.5)
        )
        rh = rh_mean + RH_PER_C * diurnal + self._rng.normal(0.0, RH_NOISE_PCT, t_s.size)
        for first, last, fog_c in weather.fog:
            w = _window(days, first, last)
            fog_temp = fog_c + 0.5 * FOG_RANGE_C * np.cos(
                2 * np.pi * (hour - WARMEST_HOUR_UTC) / 24
            )
            temp = (1 - w) * temp + w * (fog_temp + 0.3 * noise)
            rh = (1 - w) * rh + w * (FOG_RH_PCT + self._rng.normal(0.0, 0.5, t_s.size))
        for first, last, delta_c in weather.heat_waves:
            w = _window(days, first, last)
            temp, rh = temp + delta_c * w, rh - HEAT_WAVE_RH_DROP_PCT * w
        for day, delta_c, duration_h in weather.fronts:
            onset = np.clip((days - day) * 24 / duration_h, 0, 1)
            recovery = np.clip((days - day - FRONT_HOLD_DAYS) / FRONT_RECOVERY_DAYS, 0, 1)
            temp = temp + delta_c * onset * (1 - recovery)
        return temp, np.clip(rh, 0.0, 100.0)

    def indoor(self, t_s: FloatArray, office: Office) -> tuple[FloatArray, FloatArray]:
        """Indoor temperature (°C) and relative humidity (%) at times ``t_s``."""
        local = pd.to_datetime(t_s, unit="s", utc=True).tz_convert(LOCAL_ZONE)
        hour = local.hour.to_numpy() + local.minute.to_numpy() / 60.0
        heating = ((local.weekday.to_numpy() < 5) & (hour >= 7) & (hour < 17)).astype(float)
        target = office.level_c + office.heating_c * heating
        target = target + self._rng.normal(0.0, office.noise_c, t_s.size)
        temp = np.empty_like(target)
        level = target[0]
        for i, value in enumerate(target):
            level = 0.7 * level + 0.3 * value
            temp[i] = level
        rh = office.rh_pct - 3.0 * heating + self._rng.normal(0.0, 1.0, t_s.size)
        return temp, rh

    def _cloudiness(self, n_days: int, fixed: float | None) -> FloatArray:
        if fixed is not None:
            return np.full(n_days, fixed)
        cloud = np.empty(n_days)
        cloud[0] = self._rng.uniform()
        for d in range(1, n_days):
            step = 0.6 * cloud[d - 1] + 0.4 * self._rng.uniform() + self._rng.normal(0, 0.1)
            cloud[d] = np.clip(step, 0.0, 1.0)
        return cloud

    def _daily_ar1(self, n_days: int) -> FloatArray:
        return self._ar1(n_days, SYNOPTIC_SIGMA_C * np.sqrt(1 - SYNOPTIC_PHI**2), SYNOPTIC_PHI)

    def _ar1(self, n_samples: int, sigma: float, phi: float) -> FloatArray:
        innovations = self._rng.normal(0.0, sigma, n_samples)
        noise = np.empty(n_samples)
        level = 0.0
        for i, innovation in enumerate(innovations):
            level = phi * level + innovation
            noise[i] = level
        return noise


def _window(days: FloatArray, first: float, last: float) -> FloatArray:
    """0 outside ``[first, last]`` days, 1 inside, with linear edges of 6 h."""
    rise = np.clip((days - first) * 24 / EPISODE_EDGE_H, 0, 1)
    fall = np.clip((last - days) * 24 / EPISODE_EDGE_H, 0, 1)
    return np.minimum(rise, fall)


def flat_trace(values_c: Sequence[float], interval_s: float = INTERVAL_S) -> Trace:
    """A small hand-written trace with regular sampling and constant 60 % humidity."""
    t_s = START_UTC.value / 1e9 + interval_s * np.arange(len(values_c), dtype=np.float64)
    temp = np.asarray(values_c, dtype=np.float64)
    return Trace(t_s, temp, np.full(temp.shape, 60.0))


def custom_trace(
    offsets_s: Sequence[float],
    temp_c: Sequence[float],
    rh_pct: Sequence[float] | None = None,
) -> Trace:
    """A small hand-written trace with explicit sample times (seconds after ``START_UTC``)."""
    t_s = START_UTC.value / 1e9 + np.asarray(offsets_s, dtype=np.float64)
    temp = np.asarray(temp_c, dtype=np.float64)
    rh = np.full(temp.shape, 60.0) if rh_pct is None else np.asarray(rh_pct, dtype=np.float64)
    return Trace(t_s, temp, rh)
