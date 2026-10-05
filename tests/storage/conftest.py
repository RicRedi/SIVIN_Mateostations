"""Fixtures of the storage tests. All measurement values here are synthetic."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd
import pytest

from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries
from sivin.storage.store import MeasurementStore

UtcSeriesFactory = Callable[..., MeasurementSeries]


@pytest.fixture
def store(tmp_path: Path) -> MeasurementStore:
    """An empty store in a temporary directory."""
    return MeasurementStore(tmp_path / "data")


@pytest.fixture
def make_utc_series(sensor_id: SensorId) -> UtcSeriesFactory:
    """Build a synthetic series from ISO 8601 UTC strings."""

    def factory(
        utc_times: Sequence[str],
        temp_c: Sequence[float],
        rh_pct: Sequence[float],
        source: str | Sequence[str] | None = "synthetic.csv",
        qc: Sequence[int] | None = None,
        sensor: SensorId | None = None,
    ) -> MeasurementSeries:
        return MeasurementSeries.from_records(
            sensor or sensor_id,
            pd.DatetimeIndex(list(utc_times)),
            temp_c,
            rh_pct,
            qc=qc,
            source=source,
        )

    return factory
