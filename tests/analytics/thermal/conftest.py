"""Fixtures of the thermal index tests. All data built here are synthetic."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from sivin.analytics.base import IndexContext
from sivin.core.daily import DAILY_COLUMNS, DATE_INDEX_NAME, DailyWeather
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

PRAGUE = "Europe/Prague"
SENSOR_LATITUDE_DEG = 48.88  # latitude of the deployed sensors (sensor_location.gpx), ~48.88° N

DayValues = tuple[float, float, float]
"""Synthetic ``(temp_min, temp_mean, temp_max)`` of one day in °C."""

DailyFactory = Callable[..., DailyWeather]
ContextFactory = Callable[..., IndexContext]


def days_from(first: date, n_days: int) -> list[date]:
    """Return ``n_days`` consecutive dates starting at ``first``."""
    return [first + timedelta(days=offset) for offset in range(n_days)]


@pytest.fixture
def make_daily(sensor_id: SensorId) -> DailyFactory:
    """Build synthetic daily aggregates directly from ``{date: (tmin, tmean, tmax)}``.

    Days listed in ``coverage`` get that temperature coverage, all others 1.0.
    """

    def factory(
        values: Mapping[date, DayValues], coverage: Mapping[date, float] | None = None
    ) -> DailyWeather:
        dates = sorted(values)
        cover = [float((coverage or {}).get(day, 1.0)) for day in dates]
        temps = np.array([values[day] for day in dates], dtype=np.float64).reshape(-1, 3)
        n_samples = [48] * len(dates)
        frame = pd.DataFrame(
            {
                "temp_min": temps[:, 0],
                "temp_mean": temps[:, 1],
                "temp_max": temps[:, 2],
                "rh_min": [60.0] * len(dates),
                "rh_mean": [75.0] * len(dates),
                "rh_max": [90.0] * len(dates),
                "temp_n_samples": n_samples,
                "rh_n_samples": n_samples,
                "temp_coverage": cover,
                "rh_coverage": cover,
                "n_samples": n_samples,
                "coverage": cover,
            },
            index=pd.Index(dates, dtype=object, name=DATE_INDEX_NAME),
        )
        for column in ("temp_n_samples", "rh_n_samples", "n_samples"):
            frame[column] = frame[column].astype(np.int64)
        return DailyWeather(sensor_id, frame[list(DAILY_COLUMNS)], PRAGUE)

    return factory


@pytest.fixture
def make_context(sensor_id: SensorId) -> ContextFactory:
    """Build an :class:`IndexContext` around synthetic daily data (raw series optional)."""

    def factory(
        daily: DailyWeather,
        *,
        year: int = 2026,
        latitude_deg: float | None = SENSOR_LATITUDE_DEG,
        series: MeasurementSeries | None = None,
        min_daily_coverage: float = 0.9,
        min_season_coverage: float = 0.9,
    ) -> IndexContext:
        return IndexContext(
            sensor_id=sensor_id,
            year=year,
            daily=daily,
            series=series if series is not None else MeasurementSeries.empty(sensor_id),
            latitude_deg=latitude_deg,
            elevation_m=184.0,
            timezone=PRAGUE,
            min_daily_coverage=min_daily_coverage,
            min_season_coverage=min_season_coverage,
            exclude_mask=int(QcFlag.DEFAULT_EXCLUDE),
        )

    return factory


@pytest.fixture
def constant_days() -> Callable[[date, int, DayValues], dict[date, DayValues]]:
    """Return a builder of ``n_days`` days from ``first`` with the same synthetic values."""

    def build(first: date, n_days: int, values: DayValues) -> dict[date, DayValues]:
        return dict.fromkeys(days_from(first, n_days), values)

    return build
