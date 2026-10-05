"""Fixtures for the alignment tests. All series built here are synthetic (no measured data)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd
import pytest

from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

T0 = pd.Timestamp("2026-06-01T00:00:00Z")
"""Reference instant of the synthetic series; offsets in the tests are seconds after it."""

SeriesAt = Callable[..., MeasurementSeries]


def at(offset_s: float) -> pd.Timestamp:
    """Return the instant ``offset_s`` seconds after :data:`T0`."""
    return T0 + pd.Timedelta(seconds=offset_s)


@pytest.fixture
def series_at() -> SeriesAt:
    """Build a synthetic series from offsets in seconds after :data:`T0`.

    ``rh_pct`` defaults to ``temp_c + 50`` so both variables carry recognisable values.
    """

    def factory(
        serial: str,
        offsets_s: Sequence[float],
        temp_c: Sequence[float],
        rh_pct: Sequence[float] | None = None,
        qc: Sequence[int] | None = None,
    ) -> MeasurementSeries:
        humidity = [value + 50 for value in temp_c] if rh_pct is None else rh_pct
        return MeasurementSeries.from_records(
            SensorId(serial), [at(s) for s in offsets_s], temp_c, humidity, qc=qc
        )

    return factory
