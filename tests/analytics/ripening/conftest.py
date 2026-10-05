"""Builders of synthetic hourly series and index contexts for the ripening tests.

Every value built here is synthetic (chosen by hand for the expected results in the tests),
not a measurement of a real sensor.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from sivin.analytics.base import IndexContext
from sivin.core.daily import DailyWeather
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

PRAGUE = "Europe/Prague"
HOUR_S = 3600.0
HOURS_PER_DAY = 24

ContextFactory = Callable[..., IndexContext]
DaySeriesFactory = Callable[..., MeasurementSeries]


def local_stamps(day: date, hours: Sequence[float]) -> pd.DatetimeIndex:
    """UTC timestamps of local Europe/Prague wall-clock hours (fractions allowed) of one day."""
    naive = [datetime(day.year, day.month, day.day) + timedelta(hours=h) for h in hours]
    return pd.DatetimeIndex(naive).tz_localize(PRAGUE).tz_convert("UTC")


def two_level_day(temp_min_c: float, temp_max_c: float) -> list[float]:
    """24 hourly temperatures: 12 h at the minimum, then 12 h at the maximum."""
    return [temp_min_c] * 12 + [temp_max_c] * 12


@pytest.fixture
def hourly_days(sensor_id: SensorId) -> DaySeriesFactory:
    """Build a series of whole local days sampled every hour (00:00 .. 23:00).

    ``temps`` maps a local date to its 24 hourly temperatures; ``rh`` optionally maps it to
    24 humidities (default 60 %). A trailing sample at 00:00 of the following day can be added
    so that the 23:00 sample represents a full hour.
    """

    def factory(
        temps: Mapping[date, Sequence[float]],
        rh: Mapping[date, Sequence[float]] | None = None,
        trailing_sample: bool = False,
    ) -> MeasurementSeries:
        stamps: list[pd.Timestamp] = []
        temp_c: list[float] = []
        rh_pct: list[float] = []
        for day, day_temps in temps.items():
            assert len(day_temps) == HOURS_PER_DAY
            stamps.extend(local_stamps(day, range(HOURS_PER_DAY)))
            temp_c.extend(day_temps)
            rh_pct.extend(rh[day] if rh and day in rh else [60.0] * HOURS_PER_DAY)
        if trailing_sample:
            last_day = max(temps) + timedelta(days=1)
            stamps.extend(local_stamps(last_day, [0]))
            temp_c.append(10.0)
            rh_pct.append(60.0)
        return MeasurementSeries.from_records(sensor_id, pd.DatetimeIndex(stamps), temp_c, rh_pct)

    return factory


@pytest.fixture
def make_context(sensor_id: SensorId) -> ContextFactory:
    """Build an :class:`IndexContext` for a series (daily aggregates at a given interval)."""

    def factory(
        series: MeasurementSeries,
        year: int,
        expected_interval_s: float = HOUR_S,
        min_daily_coverage: float = 0.9,
        min_season_coverage: float = 0.9,
        exclude_mask: int = int(QcFlag.DEFAULT_EXCLUDE),
    ) -> IndexContext:
        daily = DailyWeather.from_series(series, PRAGUE, expected_interval_s, exclude_mask)
        return IndexContext(
            sensor_id=sensor_id,
            year=year,
            daily=daily,
            series=series,
            latitude_deg=48.88,
            elevation_m=184.0,
            timezone=PRAGUE,
            min_daily_coverage=min_daily_coverage,
            min_season_coverage=min_season_coverage,
            exclude_mask=exclude_mask,
        )

    return factory
