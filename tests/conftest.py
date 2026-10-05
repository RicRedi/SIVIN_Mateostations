"""Shared fixtures. All data built here are synthetic and exist only for tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd
import pytest

from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

PRAGUE = "Europe/Prague"

SeriesFactory = Callable[..., MeasurementSeries]


@pytest.fixture
def sensor_id() -> SensorId:
    """A real serial number of one deployed sensor (identity only, no measured data)."""
    return SensorId("77678271")


@pytest.fixture
def make_series(sensor_id: SensorId) -> SeriesFactory:
    """Build a synthetic series from local Europe/Prague wall-clock strings."""

    def factory(
        local_times: Sequence[str],
        temp_c: Sequence[float],
        rh_pct: Sequence[float],
        qc: Sequence[int] | None = None,
    ) -> MeasurementSeries:
        timestamps = pd.DatetimeIndex(pd.to_datetime(list(local_times))).tz_localize(PRAGUE)
        return MeasurementSeries.from_records(sensor_id, timestamps, temp_c, rh_pct, qc=qc)

    return factory
