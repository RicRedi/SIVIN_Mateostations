"""Precipitation and battery columns in MeasurementSeries and DailyWeather (WP-1.9).

All values are SYNTHETIC; expectations are computed by hand in the comments.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from sivin.core.daily import (
    ALL_DAILY_COLUMNS,
    AUXILIARY_DAILY_COLUMNS,
    DAILY_COLUMNS,
    DailyWeather,
)
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import (
    AUXILIARY_COLUMNS,
    CANONICAL_ORDER,
    Column,
    MeasurementSeries,
    SchemaError,
)

PRAGUE = "Europe/Prague"
EXCLUDE = int(QcFlag.DEFAULT_EXCLUDE)
SIX_HOURS_S = 6 * 3600.0
NAN = math.nan


def _local(times: list[str]) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(times)).tz_localize(PRAGUE)


def test_auxiliary_columns_and_canonical_order() -> None:
    assert [str(c) for c in AUXILIARY_COLUMNS] == ["precip_mm", "precip_total_mm", "battery_v"]
    assert [str(c) for c in CANONICAL_ORDER] == [
        "timestamp_utc",
        "temp_c",
        "rh_pct",
        "precip_mm",
        "precip_total_mm",
        "battery_v",
        "qc",
        "source",
    ]


def test_from_records_takes_the_auxiliary_columns_in_time_order(sensor_id: SensorId) -> None:
    series = MeasurementSeries.from_records(
        sensor_id,
        ["2026-01-01T01:00Z", "2026-01-01T00:00Z"],
        [2.0, 1.0],
        [60.0, 50.0],
        precip_mm=[0.3, 0.0],
        precip_total_mm=[323.3, 323.0],
        battery_v=[3.5, 3.6],
    )
    frame = series.frame
    assert frame[Column.PRECIP].tolist() == [0.0, 0.3]
    assert frame[Column.PRECIP_TOTAL].tolist() == [323.0, 323.3]
    assert frame[Column.BATTERY].tolist() == [3.6, 3.5]
    assert all(frame[c].dtype == np.float64 for c in AUXILIARY_COLUMNS)


def test_omitted_auxiliary_columns_are_nan(sensor_id: SensorId) -> None:
    series = MeasurementSeries.from_records(
        sensor_id, ["2026-01-01T00:00Z"], [1.0], [50.0], precip_mm=[0.2]
    )
    frame = series.frame
    assert frame[Column.PRECIP].tolist() == [0.2]
    assert frame[[Column.PRECIP_TOTAL, Column.BATTERY]].isna().all().all()
    assert MeasurementSeries.empty(sensor_id).frame[list(AUXILIARY_COLUMNS)].empty


def test_constructor_fills_missing_auxiliary_columns_but_checks_given_ones(
    sensor_id: SensorId,
) -> None:
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(["2026-01-01T00:00Z"]).as_unit("ns"),
            "temp_c": [1.0],
            "rh_pct": [50.0],
            "qc": np.array([0], dtype=np.int32),
            "battery_v": [3.4],
        }
    )
    series = MeasurementSeries(sensor_id, frame)
    assert series.frame[Column.BATTERY].tolist() == [3.4]
    assert series.frame[Column.PRECIP].isna().all()
    with pytest.raises(SchemaError, match="'battery_v' must be float64"):
        MeasurementSeries(sensor_id, frame.assign(battery_v=np.array([3], dtype=np.int64)))
    with pytest.raises(SchemaError, match="'precip_mm' contains infinite"):
        MeasurementSeries(sensor_id, frame.assign(precip_mm=[math.inf]))


def test_from_records_rejects_wrong_auxiliary_lengths(sensor_id: SensorId) -> None:
    with pytest.raises(SchemaError, match="'precip_total_mm' has shape"):
        MeasurementSeries.from_records(
            sensor_id, ["2026-01-01T00:00Z"], [1.0], [50.0], precip_total_mm=[1.0, 2.0]
        )
    with pytest.raises(SchemaError, match="'battery_v' cannot be converted"):
        MeasurementSeries.from_records(
            sensor_id, ["2026-01-01T00:00Z"], [1.0], [50.0], battery_v=["low"]
        )


def test_missing_auxiliary_values_do_not_invalidate_a_row(sensor_id: SensorId) -> None:
    series = MeasurementSeries.from_records(
        sensor_id,
        ["2026-01-01T00:00Z", "2026-01-01T00:30Z", "2026-01-01T01:00Z"],
        [1.0, 2.0, NAN],
        [50.0, 51.0, 52.0],
        precip_mm=[NAN, 0.1, 0.2],
        precip_total_mm=[NAN, NAN, 1.0],
        battery_v=[NAN, NAN, 3.6],
    )
    # Row 1 has no auxiliary values but both T and RH: valid. Row 3 lacks T: invalid.
    assert series.complete_mask(EXCLUDE).tolist() == [True, True, False]


def test_with_values_replaces_only_an_auxiliary_column(sensor_id: SensorId) -> None:
    series = MeasurementSeries.from_records(
        sensor_id,
        ["2026-01-01T00:00Z", "2026-01-01T00:30Z"],
        [1.0, 2.0],
        [50.0, 51.0],
        qc=[0, int(QcFlag.STEP)],
        source="a.csv",
        precip_mm=[-1.0, 0.2],
    )
    cleaned = series.with_values(Column.PRECIP, [NAN, 0.2])
    np.testing.assert_array_equal(cleaned.frame[Column.PRECIP].to_numpy(), [NAN, 0.2])
    unchanged = [c for c in series.frame.columns if c != Column.PRECIP]
    pd.testing.assert_frame_equal(cleaned.frame[unchanged], series.frame[unchanged])
    assert series.frame[Column.PRECIP].tolist() == [-1.0, 0.2]
    with pytest.raises(SchemaError, match="Only the auxiliary columns"):
        series.with_values(Column.TEMP, [NAN, NAN])
    with pytest.raises(SchemaError, match="has shape"):
        series.with_values(Column.BATTERY, [3.0])


def test_to_frame_carries_the_auxiliary_columns(sensor_id: SensorId) -> None:
    series = MeasurementSeries.from_records(
        sensor_id, ["2026-01-01T00:00Z"], [1.0], [50.0], battery_v=[3.6]
    )
    long = series.to_frame()
    assert list(long.columns[:7]) == [
        "sensor_id",
        "timestamp_utc",
        "temp_c",
        "rh_pct",
        "precip_mm",
        "precip_total_mm",
        "battery_v",
    ]
    assert MeasurementSeries(sensor_id, long).frame.equals(series.frame)


@pytest.fixture
def rainy_days(sensor_id: SensorId) -> DailyWeather:
    """Synthetic 6-hourly samples over three local days.

    2026-01-10: precip 0.0, 0.3, NaN, 1.2 -> sum 1.5 mm; battery 3.6, 3.5, 3.4, NaN -> min 3.4 V
    2026-01-11: 00:00 precip 2.0 but SPIKE (excluded), 06:00 precip 0.5 with temperature NaN
                (invalid row), 12:00 precip NaN, battery NaN (valid T/RH)
                -> no valid precipitation value -> NaN; no valid battery value -> NaN
    2026-01-12: 00:00 precip 0.0, battery 3.2 -> sum 0.0 mm, min 3.2 V
    """
    series = MeasurementSeries.from_records(
        sensor_id,
        _local(
            [
                "2026-01-10 00:00",
                "2026-01-10 06:00",
                "2026-01-10 12:00",
                "2026-01-10 18:00",
                "2026-01-11 00:00",
                "2026-01-11 06:00",
                "2026-01-11 12:00",
                "2026-01-12 00:00",
            ]
        ),
        [1.0, 2.0, 3.0, 4.0, 5.0, NAN, 7.0, 8.0],
        [90.0] * 8,
        qc=[0, 0, 0, 0, int(QcFlag.SPIKE), 0, 0, 0],
        precip_mm=[0.0, 0.3, NAN, 1.2, 2.0, 0.5, NAN, 0.0],
        battery_v=[3.6, 3.5, 3.4, NAN, 3.0, 3.1, NAN, 3.2],
    )
    return DailyWeather.from_series(series, PRAGUE, SIX_HOURS_S, EXCLUDE)


def test_daily_precipitation_sum_and_battery_minimum(rainy_days: DailyWeather) -> None:
    frame = rainy_days.frame
    assert list(frame.columns) == list(ALL_DAILY_COLUMNS)
    assert frame.loc[date(2026, 1, 10), "precip_sum_mm"] == pytest.approx(1.5)
    assert frame.loc[date(2026, 1, 10), "battery_min_v"] == 3.4
    assert math.isnan(frame.loc[date(2026, 1, 11), "precip_sum_mm"])
    assert math.isnan(frame.loc[date(2026, 1, 11), "battery_min_v"])
    assert frame.loc[date(2026, 1, 12), "precip_sum_mm"] == 0.0
    assert frame.loc[date(2026, 1, 12), "battery_min_v"] == 3.2
    # The valid-sample count is not affected by the missing precipitation of 2026-01-10 12:00.
    assert frame["n_samples"].tolist() == [4, 1, 1]


def test_daily_frames_without_auxiliary_columns_still_construct(
    rainy_days: DailyWeather, sensor_id: SensorId
) -> None:
    old_style = rainy_days.frame[list(DAILY_COLUMNS)]
    rebuilt = DailyWeather(sensor_id, old_style, PRAGUE)
    assert list(rebuilt.frame.columns) == list(ALL_DAILY_COLUMNS)
    assert rebuilt.frame[list(AUXILIARY_DAILY_COLUMNS)].isna().all().all()
    battery_only = rainy_days.frame[[*DAILY_COLUMNS, "battery_min_v"]]
    partly = DailyWeather(sensor_id, battery_only, PRAGUE).frame
    assert list(partly.columns) == list(ALL_DAILY_COLUMNS)
    assert partly["battery_min_v"].tolist()[0] == 3.4
    assert rainy_days.complete_days(0.9).frame["precip_sum_mm"].tolist() == [pytest.approx(1.5)]


def test_daily_rejects_misplaced_or_mistyped_auxiliary_columns(
    rainy_days: DailyWeather, sensor_id: SensorId
) -> None:
    frame = rainy_days.frame
    reordered = frame[[*DAILY_COLUMNS, "battery_min_v", "precip_sum_mm"]]
    with pytest.raises(SchemaError, match="optionally followed by"):
        DailyWeather(sensor_id, reordered, PRAGUE)
    with pytest.raises(SchemaError, match="'precip_sum_mm' must be float64"):
        DailyWeather(sensor_id, frame.assign(precip_sum_mm="x"), PRAGUE)


def test_empty_daily_has_auxiliary_columns(sensor_id: SensorId) -> None:
    empty = DailyWeather.from_series(MeasurementSeries.empty(sensor_id), PRAGUE, 1830.0, EXCLUDE)
    assert list(empty.frame.columns) == list(ALL_DAILY_COLUMNS)
    assert len(empty) == 0
