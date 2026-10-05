"""Fixtures of the disease-model tests. All data built here are synthetic."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd
import pytest

from sivin.analytics.base import IndexContext
from sivin.core.daily import DailyWeather
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

PRAGUE = "Europe/Prague"
HOUR_S = 3600.0

ContextFactory = Callable[..., IndexContext]


@pytest.fixture
def make_context(sensor_id: SensorId) -> ContextFactory:
    """Build an :class:`IndexContext` from synthetic local Europe/Prague samples.

    ``local_times`` are wall-clock strings; ``expected_interval_s`` is the nominal interval
    used for the daily coverage.
    """

    def factory(
        local_times: Sequence[str] | pd.DatetimeIndex,
        temp_c: Sequence[float],
        rh_pct: Sequence[float],
        qc: Sequence[int] | None = None,
        expected_interval_s: float = HOUR_S,
        year: int = 2026,
        min_daily_coverage: float = 0.9,
        min_season_coverage: float = 0.9,
    ) -> IndexContext:
        stamps = pd.DatetimeIndex(pd.to_datetime(list(local_times))).tz_localize(PRAGUE)
        series = MeasurementSeries.from_records(sensor_id, stamps, temp_c, rh_pct, qc=qc)
        mask = int(QcFlag.DEFAULT_EXCLUDE)
        daily = DailyWeather.from_series(series, PRAGUE, expected_interval_s, mask)
        return IndexContext(
            sensor_id=sensor_id,
            year=year,
            daily=daily,
            series=series,
            latitude_deg=None,
            elevation_m=None,
            timezone=PRAGUE,
            min_daily_coverage=min_daily_coverage,
            min_season_coverage=min_season_coverage,
            exclude_mask=mask,
        )

    return factory
