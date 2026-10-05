"""Tests of MeasurementSeries (MIGRATION_PLAN §2.5). All values are synthetic."""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries, SchemaError

UTC_TIMES = ["2026-01-01T00:00:00Z", "2026-01-01T00:30:25Z", "2026-01-01T01:00:50Z"]


def canonical_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(UTC_TIMES).as_unit("ns"),
            "temp_c": np.array([1.5, 1.0, np.nan]),
            "rh_pct": np.array([90.0, 91.0, 92.0]),
            "qc": np.array([0, 8, 1], dtype=np.int32),
        }
    )


def test_constructor_accepts_canonical_frame(sensor_id: SensorId) -> None:
    series = MeasurementSeries(sensor_id, canonical_frame())
    assert len(series) == 3
    assert not series.is_empty
    assert series.sensor_id == sensor_id
    assert list(series.frame.columns) == [
        "timestamp_utc",
        "temp_c",
        "rh_pct",
        "precip_mm",
        "precip_total_mm",
        "battery_v",
        "qc",
    ]
    assert series.frame[["precip_mm", "precip_total_mm", "battery_v"]].isna().all().all()
    assert "rows=3" in repr(series)


def test_constructor_keeps_a_private_copy(sensor_id: SensorId) -> None:
    frame = canonical_frame()
    series = MeasurementSeries(sensor_id, frame)
    frame.loc[0, "temp_c"] = 99.0
    exposed = series.frame
    exposed.loc[0, "temp_c"] = 99.0
    assert series.frame.loc[0, "temp_c"] == 1.5


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda f: f.assign(timestamp_utc=f["timestamp_utc"].dt.tz_localize(None)), "must be"),
        (lambda f: f.assign(timestamp_utc=f["timestamp_utc"].dt.as_unit("us")), "must be"),
        (lambda f: f.iloc[[1, 0, 2]].reset_index(drop=True), "not sorted"),
        (lambda f: f.iloc[[0, 0, 1]].reset_index(drop=True), "duplicate"),
        (lambda f: f.assign(temp_c=f["temp_c"].astype(np.float32)), "'temp_c' must be float64"),
        (lambda f: f.assign(rh_pct=[90, 91, 92]), "'rh_pct' must be float64"),
        (lambda f: f.assign(qc=f["qc"].astype(np.int64)), "'qc' must be int32"),
        (lambda f: f.assign(qc=np.array([0, 512, 0], dtype=np.int32)), "Invalid QC flag"),
        (lambda f: f.assign(qc=np.array([0, -1, 0], dtype=np.int32)), "Invalid QC flag"),
        (lambda f: f.drop(columns="rh_pct"), "missing \\['rh_pct'\\]"),
        (lambda f: f.assign(extra=1.0), "unknown \\['extra'\\]"),
        (lambda f: f.assign(source=["a.csv", None, "a.csv"]), "strings only"),
        (lambda f: f.assign(source=[1, 2, 3]), "strings only"),
        (lambda f: f.assign(sensor_id="77680921"), "other than 77678271"),
        (lambda f: f.assign(temp_c=[1.0, np.inf, 2.0]), "infinite"),
        (lambda f: f.assign(rh_pct=[1.0, -np.inf, 2.0]), "infinite"),
    ],
)
def test_constructor_rejects_schema_violations(
    sensor_id: SensorId, mutate: object, message: str
) -> None:
    assert callable(mutate)
    with pytest.raises(SchemaError, match=message):
        MeasurementSeries(sensor_id, mutate(canonical_frame()))


def test_constructor_rejects_missing_timestamp(sensor_id: SensorId) -> None:
    frame = canonical_frame()
    frame.loc[2, "timestamp_utc"] = pd.NaT
    with pytest.raises(SchemaError, match="missing timestamps"):
        MeasurementSeries(sensor_id, frame)


def test_constructor_rejects_non_frame(sensor_id: SensorId) -> None:
    with pytest.raises(SchemaError, match="DataFrame"):
        MeasurementSeries(sensor_id, [1, 2, 3])  # type: ignore[arg-type]


def test_matching_sensor_id_column_is_dropped(sensor_id: SensorId) -> None:
    frame = canonical_frame().assign(sensor_id="77678271", source="x.csv")
    series = MeasurementSeries(sensor_id, frame)
    assert list(series.frame.columns) == [
        "timestamp_utc",
        "temp_c",
        "rh_pct",
        "precip_mm",
        "precip_total_mm",
        "battery_v",
        "qc",
        "source",
    ]


def test_from_records_normalises(sensor_id: SensorId, caplog: pytest.LogCaptureFixture) -> None:
    times = [
        "2026-01-01T02:00:00+01:00",  # = 01:00 UTC
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",  # duplicate of the first row, later in input -> kept
    ]
    with caplog.at_level(logging.WARNING):
        series = MeasurementSeries.from_records(
            sensor_id, times, [5, 1, 7], [50, 10, 70], qc=[8, 0, 0], source="export.csv"
        )
    frame = series.frame
    assert frame["timestamp_utc"].dtype == pd.DatetimeTZDtype("ns", "UTC")
    assert frame["timestamp_utc"].tolist() == [
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T01:00:00Z"),
    ]
    assert frame["temp_c"].tolist() == [1.0, 7.0]
    assert frame["rh_pct"].tolist() == [10.0, 70.0]
    assert frame["qc"].tolist() == [0, 0]
    assert frame["qc"].dtype == np.int32
    assert frame["source"].tolist() == ["export.csv", "export.csv"]
    assert "dropped 1 row(s)" in caplog.text


def test_from_records_defaults_qc_to_zero(sensor_id: SensorId) -> None:
    series = MeasurementSeries.from_records(sensor_id, UTC_TIMES, [1, 2, 3], [4, 5, 6])
    assert series.frame["qc"].tolist() == [0, 0, 0]
    assert "source" not in series.frame.columns


def test_from_records_accepts_datetimes_and_per_row_sources(sensor_id: SensorId) -> None:
    times = pd.Series(pd.to_datetime(UTC_TIMES[:2]))
    series = MeasurementSeries.from_records(sensor_id, times, [1, 2], [3, 4], source=["a", "b"])
    assert series.frame["source"].tolist() == ["a", "b"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timestamps_utc": ["2026-01-01 00:00", "2026-01-01 00:30"]}, "timezone-aware"),
        ({"timestamps_utc": ["not a time", "2026-01-01T00:00Z"]}, "Cannot parse"),
        ({"temp_c": [1.0]}, "'temp_c' has shape"),
        ({"rh_pct": ["wet", "dry"]}, "'rh_pct' cannot be converted"),
        ({"qc": [0.5, 0.0]}, "must contain integers"),
        ({"qc": [0, 1024]}, "Invalid QC flag"),
        ({"source": ["only one"]}, "'source' has 1 rows"),
    ],
)
def test_from_records_rejects_bad_input(
    sensor_id: SensorId, kwargs: dict[str, object], message: str
) -> None:
    arguments: dict[str, object] = {
        "timestamps_utc": UTC_TIMES[:2],
        "temp_c": [1.0, 2.0],
        "rh_pct": [3.0, 4.0],
    }
    arguments.update(kwargs)
    with pytest.raises(SchemaError, match=message):
        MeasurementSeries.from_records(sensor_id, **arguments)  # type: ignore[arg-type]


def test_empty(sensor_id: SensorId) -> None:
    series = MeasurementSeries.empty(sensor_id)
    assert series.is_empty
    assert len(series) == 0
    assert series.frame["timestamp_utc"].dtype == pd.DatetimeTZDtype("ns", "UTC")
    assert repr(series) == "MeasurementSeries(sensor_id=77678271, rows=0)"


def test_between_is_inclusive_and_timezone_aware(sensor_id: SensorId) -> None:
    series = MeasurementSeries(sensor_id, canonical_frame())
    selected = series.between(
        datetime.fromisoformat("2026-01-01T01:30:25+01:00"),  # = 00:30:25 UTC
        pd.Timestamp("2026-01-01T01:00:50Z"),
    )
    assert selected.timestamps.tolist() == [
        pd.Timestamp("2026-01-01T00:30:25Z"),
        pd.Timestamp("2026-01-01T01:00:50Z"),
    ]
    assert selected.frame.index.tolist() == [0, 1]
    assert len(series) == 3


def test_between_rejects_naive_bounds(sensor_id: SensorId) -> None:
    series = MeasurementSeries(sensor_id, canonical_frame())
    with pytest.raises(ValueError, match="'start' must be timezone-aware"):
        series.between("2026-01-01 00:00", "2026-01-02T00:00Z")


def test_with_flags_ors_into_qc_and_returns_new_instance(sensor_id: SensorId) -> None:
    series = MeasurementSeries(sensor_id, canonical_frame())
    flagged = series.with_flags(np.array([QcFlag.SPIKE, QcFlag.STEP, 0]))
    assert flagged.frame["qc"].tolist() == [4, 8, 1]
    assert flagged.frame["qc"].dtype == np.int32
    assert series.frame["qc"].tolist() == [0, 8, 1]
    flagged_again = flagged.with_flags(pd.Series([0, 0, 128]))
    assert flagged_again.frame["qc"].tolist() == [4, 8, 129]


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (np.array([0, 0]), "Expected 3 flag values"),
        (np.array([0.0, 1.0, 0.0]), "must be integers"),
        (np.array([0, 1024, 0]), "Invalid QC flag"),
    ],
)
def test_with_flags_rejects_bad_flags(sensor_id: SensorId, flags: np.ndarray, message: str) -> None:
    series = MeasurementSeries(sensor_id, canonical_frame())
    with pytest.raises(SchemaError, match=message):
        series.with_flags(flags)


def test_valid_mask(sensor_id: SensorId) -> None:
    series = MeasurementSeries(sensor_id, canonical_frame())  # qc = [0, STEP, MISSING]
    assert series.valid_mask(QcFlag.DEFAULT_EXCLUDE).tolist() == [True, True, False]
    assert series.valid_mask(QcFlag.STEP).tolist() == [True, False, True]


def test_complete_mask_needs_both_values_and_no_excluded_flag(sensor_id: SensorId) -> None:
    # Synthetic rows: both values, humidity missing, temperature missing, both values + SPIKE.
    nan = float("nan")
    stamps = pd.date_range("2026-01-10", periods=4, freq="1830s", tz="UTC")
    series = MeasurementSeries.from_records(
        sensor_id,
        stamps,
        [1.0, 2.0, nan, 4.0],
        [50.0, nan, 60.0, 70.0],
        qc=[0, 0, 0, int(QcFlag.SPIKE)],
    )
    complete = series.complete_mask(QcFlag.DEFAULT_EXCLUDE)
    assert complete.tolist() == [True, False, False, False]
    assert complete.name == "complete"
    assert series.complete_mask(0).tolist() == [True, False, False, True]


def test_to_frame_adds_sensor_id(sensor_id: SensorId) -> None:
    long = MeasurementSeries(sensor_id, canonical_frame()).to_frame()
    assert list(long.columns) == [c.value for c in (Column.SENSOR_ID, *list(Column)[1:8])]
    assert long["sensor_id"].tolist() == ["77678271"] * 3
    assert MeasurementSeries(sensor_id, long).frame.equals(
        MeasurementSeries(sensor_id, canonical_frame()).frame
    )


def test_from_records_rejects_naive_series_and_missing_timestamps(sensor_id: SensorId) -> None:
    naive = pd.Series(pd.to_datetime(["2026-01-01 00:00", "2026-01-01 00:30"]))
    with pytest.raises(SchemaError, match="timezone-aware"):
        MeasurementSeries.from_records(sensor_id, naive, [1, 2], [3, 4])
    with pytest.raises(SchemaError, match="must not be missing"):
        MeasurementSeries.from_records(sensor_id, [None, "2026-01-01T00:00Z"], [1, 2], [3, 4])


def test_from_records_rejects_mixed_offset_strings_in_series(sensor_id: SensorId) -> None:
    times = pd.Series(["2026-01-01T00:00:00+01:00", "2026-01-01T00:30:00Z"])
    with pytest.raises(SchemaError, match="Cannot parse timestamps"):
        MeasurementSeries.from_records(sensor_id, times, [1, 2], [3, 4])


def test_column_labels_are_plain_strings(sensor_id: SensorId) -> None:
    series = MeasurementSeries.from_records(sensor_id, UTC_TIMES, [1, 2, 3], [4, 5, 6])
    assert all(type(label) is str for label in series.frame.columns)
    assert all(type(label) is str for label in series.to_frame().columns)


def test_from_records_rejects_nat_before_duplicate_handling(
    sensor_id: SensorId, caplog: pytest.LogCaptureFixture
) -> None:
    times = pd.Series(pd.to_datetime([None, None, "2026-01-01T00:00Z"], utc=True))
    with caplog.at_level(logging.WARNING), pytest.raises(SchemaError, match="must not be missing"):
        MeasurementSeries.from_records(sensor_id, times, [1, 2, 3], [4, 5, 6])
    assert "duplicate" not in caplog.text
