"""SYNTHETIC data for the site tests (no value here is a measurement)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries
from sivin.quality.events import QualityEvent
from sivin.quality.pipeline import QualityResult

SENSOR = SensorId("77678271")
"""A real serial (identity only)."""

OTHER = SensorId("77680921")
"""Another real serial (identity only)."""


def series(
    times_utc: Sequence[str],
    temp_c: Sequence[float],
    rh_pct: Sequence[float],
    qc: Sequence[int] | None = None,
    precip_mm: Sequence[float] | None = None,
    battery_v: Sequence[float] | None = None,
    sensor_id: SensorId = SENSOR,
) -> MeasurementSeries:
    """A synthetic series from ISO UTC strings."""
    timestamps = pd.DatetimeIndex(list(times_utc), tz="UTC")
    return MeasurementSeries.from_records(
        sensor_id,
        timestamps,
        temp_c,
        rh_pct,
        qc=None if qc is None else np.asarray(qc, dtype=np.int32),
        precip_mm=precip_mm,
        battery_v=battery_v,
    )


def result(data: MeasurementSeries, events: Sequence[QualityEvent] = ()) -> QualityResult:
    """A QC result wrapping ``data`` as already checked."""
    return QualityResult(data, tuple(events))
