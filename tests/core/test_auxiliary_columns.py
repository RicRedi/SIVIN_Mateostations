"""Precipitation and battery columns in MeasurementSeries and DailyWeather (WP-1.9).

All values are SYNTHETIC; expectations are computed by hand in the comments.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from sivin.core.daily import (
    ALL_DAILY_COLUMNS,
    AUXILIARY_DAILY_COLUMNS,
    DAILY_COLUMNS,
    DEFAULT_AUXILIARY_EXCLUDE,
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

    The auxiliary aggregates use the default auxiliary mask (PRE_DEPLOYMENT | MANUAL_EXCLUDE),
    so the T/RH problems of 2026-01-11 do not remove precipitation or battery readings.

    2026-01-10: precip 0.0, 0.3, NaN, 1.2 -> sum 1.5 mm from 3 values;
                battery 3.6, 3.5, 3.4, NaN -> min 3.4 V
    2026-01-11: 00:00 precip 2.0 with a temperature SPIKE (counted), 06:00 precip 0.5 with
                temperature NaN (counted), 12:00 precip NaN
                -> sum 2.5 mm from 2 values; battery 3.0, 3.1, NaN -> min 3.0 V
    2026-01-12: 00:00 precip 0.0, battery 3.2 -> sum 0.0 mm from 1 value, min 3.2 V
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
    assert frame["precip_sum_mm"].tolist() == [pytest.approx(1.5), pytest.approx(2.5), 0.0]
    assert frame["precip_n_samples"].tolist() == [3, 2, 1]
    assert frame["battery_min_v"].tolist() == [3.4, 3.0, 3.2]
    # The T/RH valid-sample count is not affected by the missing precipitation of
    # 2026-01-10 12:00, and the T/RH problems of 2026-01-11 still count there.
    assert frame["n_samples"].tolist() == [4, 1, 1]


def test_daily_frames_without_auxiliary_columns_still_construct(
    rainy_days: DailyWeather, sensor_id: SensorId
) -> None:
    old_style = rainy_days.frame[list(DAILY_COLUMNS)]
    rebuilt = DailyWeather(sensor_id, old_style, PRAGUE)
    assert list(rebuilt.frame.columns) == list(ALL_DAILY_COLUMNS)
    assert rebuilt.frame[["precip_sum_mm", "battery_min_v"]].isna().all().all()
    assert rebuilt.frame["precip_n_samples"].tolist() == [0, 0, 0]
    assert rebuilt.frame["precip_n_samples"].dtype == np.int64
    assert AUXILIARY_DAILY_COLUMNS == ("precip_sum_mm", "precip_n_samples", "battery_min_v")
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
    with pytest.raises(SchemaError, match="must not be negative"):
        DailyWeather(sensor_id, frame.assign(precip_n_samples=np.int64(-1)), PRAGUE)


def test_empty_daily_has_auxiliary_columns(sensor_id: SensorId) -> None:
    empty = DailyWeather.from_series(MeasurementSeries.empty(sensor_id), PRAGUE, 1830.0, EXCLUDE)
    assert list(empty.frame.columns) == list(ALL_DAILY_COLUMNS)
    assert len(empty) == 0


def test_reviewer_example_rain_and_low_battery_survive_a_missing_temperature(
    sensor_id: SensorId,
) -> None:
    # Review WP-1.9 round 1: six samples of one local day; the second has no temperature.
    # T/RH rule: 5 valid samples. Auxiliary values: all 6 rows count ->
    # precip 1 + 2 + 3 + 0 + 0 + 0 = 6.0 mm, battery min 3.1 V (the row without temperature).
    series = MeasurementSeries.from_records(
        sensor_id,
        _local([f"2026-05-04 {hour:02d}:00" for hour in range(0, 24, 4)]),
        [1.0, NAN, 3.0, 4.0, 5.0, 6.0],
        [80.0] * 6,
        precip_mm=[1.0, 2.0, 3.0, 0.0, 0.0, 0.0],
        battery_v=[3.6, 3.1, 3.6, 3.6, 3.6, 3.6],
    )
    day = DailyWeather.from_series(series, PRAGUE, 4 * 3600.0, EXCLUDE).frame.iloc[0]
    assert day["n_samples"] == 5
    assert day["temp_min"] == 1.0
    assert day["precip_sum_mm"] == 6.0
    assert day["precip_n_samples"] == 6
    assert day["battery_min_v"] == 3.1


def test_auxiliary_mask_excludes_off_site_and_manual_rows_and_is_configurable(
    sensor_id: SensorId,
) -> None:
    # Row 0 off site (PRE_DEPLOYMENT), row 1 MANUAL_EXCLUDE, row 2 OUT_OF_RANGE (T/RH only).
    series = MeasurementSeries.from_records(
        sensor_id,
        _local(["2026-05-04 00:00", "2026-05-04 06:00", "2026-05-04 12:00"]),
        [1.0, 2.0, 99.0],
        [80.0] * 3,
        qc=[int(QcFlag.PRE_DEPLOYMENT), int(QcFlag.MANUAL_EXCLUDE), int(QcFlag.OUT_OF_RANGE)],
        precip_mm=[5.0, 7.0, 0.4],
        battery_v=[2.9, 3.0, 3.5],
    )
    assert int(QcFlag.PRE_DEPLOYMENT | QcFlag.MANUAL_EXCLUDE) == DEFAULT_AUXILIARY_EXCLUDE
    default = DailyWeather.from_series(series, PRAGUE, SIX_HOURS_S, EXCLUDE).frame.iloc[0]
    assert (default["precip_sum_mm"], default["precip_n_samples"]) == (0.4, 1)
    assert default["battery_min_v"] == 3.5
    assert default["n_samples"] == 0
    everything = DailyWeather.from_series(
        series, PRAGUE, SIX_HOURS_S, EXCLUDE, auxiliary_exclude_mask=0
    ).frame.iloc[0]
    assert everything["precip_sum_mm"] == pytest.approx(12.4)
    assert everything["battery_min_v"] == 2.9
    strict = DailyWeather.from_series(
        series, PRAGUE, SIX_HOURS_S, EXCLUDE, auxiliary_exclude_mask=EXCLUDE
    ).frame.iloc[0]
    assert math.isnan(strict["precip_sum_mm"])
    assert strict["precip_n_samples"] == 0
