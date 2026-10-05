"""SYNTHETIC test data for quality control. Nothing here is a measurement of a real sensor.

The generator builds deterministic (seeded) series that imitate the vineyard sensors:

* irregular sampling around 1825 s with random jitter,
* **outdoor** phases: seasonal mean + diurnal sinusoid + AR(1) noise; relative humidity
  anti-correlated with temperature plus its own AR(1) noise, clipped to 0-100 %,
* **indoor** phases (office, service): about 22 °C with a tiny daily cycle, humidity 35-45 %.

Helpers inject spikes, steps, ramps (cold fronts), stuck periods, missing values and gaps.
All numbers are invented for tests and chosen to look plausible for South Moravia.
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
YEAR_S = 365.25 * DAY_S

ANNUAL_MEAN_C = 10.5
ANNUAL_AMPLITUDE_C = 10.0
WARMEST_DAY_OF_YEAR = 200.0
DIURNAL_AMPLITUDE_C = 5.0
WARMEST_HOUR_UTC = 13.0
AR_PHI = 0.9
AR_SIGMA_C = 0.35
RH_MEAN_PCT = 72.0
RH_PER_C = -3.0
AR_SIGMA_RH_PCT = 1.5

INDOOR_LEVEL_C = 22.0
INDOOR_DIURNAL_AMPLITUDE_C = 0.4
INDOOR_NOISE_C = 0.1
INDOOR_RH_PCT = 40.0
INDOOR_RH_NOISE_PCT = 1.0


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

    def without_rows(self, start: int, stop: int) -> Trace:
        """Drop rows ``[start, stop)`` (a gap); boundaries are not adjusted."""
        keep = np.r_[0:start, stop : len(self)]
        return replace(self, t_s=self.t_s[keep], temp_c=self.temp_c[keep], rh_pct=self.rh_pct[keep])


class SyntheticSensor:
    """Seeded generator of synthetic traces made of indoor and outdoor phases.

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

    def trace(self, phases: Sequence[tuple[str, float]]) -> Trace:
        """Build a trace from ``(kind, days)`` phases, kind ``"indoor"`` or ``"outdoor"``."""
        n_per_phase = [round(days * DAY_S / INTERVAL_S) for _, days in phases]
        t_s = self.times(sum(n_per_phase))
        outdoor_temp, outdoor_rh = self.outdoor(t_s)
        indoor_temp, indoor_rh = self.indoor(t_s)
        temp, rh = np.empty_like(t_s), np.empty_like(t_s)
        boundaries: list[int] = []
        start = 0
        for (kind, _), n_samples in zip(phases, n_per_phase, strict=True):
            source_temp, source_rh = (
                (indoor_temp, indoor_rh) if kind == "indoor" else (outdoor_temp, outdoor_rh)
            )
            temp[start : start + n_samples] = source_temp[start : start + n_samples]
            rh[start : start + n_samples] = source_rh[start : start + n_samples]
            if start:
                boundaries.append(start)
            start += n_samples
        return Trace(t_s, np.round(temp, 1), np.round(rh, 1), tuple(boundaries))

    def outdoor(self, t_s: FloatArray) -> tuple[FloatArray, FloatArray]:
        """Outdoor temperature (°C) and relative humidity (%) at times ``t_s``."""
        day_of_year = (t_s - pd.Timestamp("2026-01-01T00:00:00Z").value / 1e9) / DAY_S
        seasonal = ANNUAL_MEAN_C + ANNUAL_AMPLITUDE_C * np.cos(
            2 * np.pi * (day_of_year - WARMEST_DAY_OF_YEAR) * DAY_S / YEAR_S
        )
        hour = (t_s % DAY_S) / 3600.0
        diurnal = DIURNAL_AMPLITUDE_C * np.cos(2 * np.pi * (hour - WARMEST_HOUR_UTC) / 24.0)
        temp = seasonal + diurnal + self._ar1(t_s.size, AR_SIGMA_C)
        rh = RH_MEAN_PCT + RH_PER_C * (temp - seasonal) + self._ar1(t_s.size, AR_SIGMA_RH_PCT)
        return temp, np.clip(rh, 0.0, 100.0)

    def indoor(self, t_s: FloatArray) -> tuple[FloatArray, FloatArray]:
        """Indoor temperature (°C) and relative humidity (%) at times ``t_s``."""
        hour = (t_s % DAY_S) / 3600.0
        temp = (
            INDOOR_LEVEL_C
            + INDOOR_DIURNAL_AMPLITUDE_C * np.cos(2 * np.pi * (hour - WARMEST_HOUR_UTC) / 24.0)
            + self._rng.normal(0.0, INDOOR_NOISE_C, t_s.size)
        )
        rh = INDOOR_RH_PCT + self._rng.normal(0.0, INDOOR_RH_NOISE_PCT, t_s.size)
        return temp, rh

    def _ar1(self, n_samples: int, sigma: float) -> FloatArray:
        innovations = self._rng.normal(0.0, sigma, n_samples)
        noise = np.empty(n_samples)
        level = 0.0
        for i, innovation in enumerate(innovations):
            level = AR_PHI * level + innovation
            noise[i] = level
        return noise


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
