"""Tests of CsvSeriesCodec. All values are synthetic."""

from __future__ import annotations

import io
import math

import numpy as np
import pandas as pd
import pytest

from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries
from sivin.storage.codec import CsvSeriesCodec
from sivin.storage.errors import StoreFormatError

from .conftest import UtcSeriesFactory

HEADER = "timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source\n"
"""Header of the current layout (since WP-1.9)."""

LEGACY_HEADER = "timestamp_utc,temp_c,rh_pct,source\n"
"""Header of the layout written before WP-1.9; still readable."""


def _encode(series: MeasurementSeries) -> bytes:
    buffer = io.BytesIO()
    CsvSeriesCodec().write(series, buffer)
    return buffer.getvalue()


def _decode(data: bytes, sensor_id: SensorId) -> MeasurementSeries:
    return CsvSeriesCodec().read(io.BytesIO(data), sensor_id, "test.csv")


def test_exact_bytes_of_a_small_file(make_utc_series: UtcSeriesFactory) -> None:
    series = make_utc_series(
        ["2026-01-01T00:00:00Z", "2026-01-01T00:30:25Z", "2026-01-01T01:00:50Z"],
        [1.2, -0.5, 12.0],
        [92.0, math.nan, 100.0],
        source=["a.csv", 'b, "quoted".csv', "c.csv"],
        qc=[0, 1, 4],
        precip_mm=[0.0, 0.3, math.nan],
        precip_total_mm=[323.0, 323.3, 323.3],
        battery_v=[3.6, math.nan, 3.5],
    )
    expected = (
        HEADER + "2026-01-01T00:00:00Z,1.2,92.0,0.0,323.0,3.6,a.csv\n"
        '2026-01-01T00:30:25Z,-0.5,,0.3,323.3,,"b, ""quoted"".csv"\n'
        "2026-01-01T01:00:50Z,12.0,100.0,,323.3,3.5,c.csv\n"
    )
    assert _encode(series) == expected.encode("utf-8")


def test_round_trip_keeps_nan_and_sources_with_commas_quotes_and_newlines(
    make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    sources = ["x,y.csv", 'say "hi".csv', "two\nlines.csv", "Žabčice ě.xlsx"]
    series = make_utc_series(
        [f"2026-03-0{day}T12:00:00Z" for day in range(1, 5)],
        [math.nan, 0.1, -12.3, math.nan],
        [55.5, math.nan, 0.0, math.nan],
        source=sources,
    )
    decoded = _decode(_encode(series), sensor_id)
    frame = decoded.frame
    assert frame[Column.SOURCE].tolist() == sources
    np.testing.assert_array_equal(frame[Column.TEMP].to_numpy(), [math.nan, 0.1, -12.3, math.nan])
    np.testing.assert_array_equal(frame[Column.RH].to_numpy(), [55.5, math.nan, 0.0, math.nan])
    assert frame[Column.TIMESTAMP].equals(series.frame[Column.TIMESTAMP])
    assert (frame[Column.QC] == 0).all()


def test_read_then_write_is_byte_identical(sensor_id: SensorId) -> None:
    data = (
        HEADER + "2025-12-31T23:30:00Z,-0.0,,,,,\n"
        '2026-01-01T00:00:00.5Z,0.30000000000000004,99.9,0.1,1000.25,3.0,"a,b"\n'
    ).encode()
    assert _encode(_decode(data, sensor_id)) == data


def test_values_are_lossless_for_arbitrary_floats(
    make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    rng = np.random.default_rng(seed=20261005)
    n_rows = 200
    temps = rng.normal(10.0, 15.0, n_rows)
    humidities = rng.uniform(0.0, 100.0, n_rows)
    times = pd.date_range("2026-01-01", periods=n_rows, freq="1825s", tz="UTC")
    series = make_utc_series([t.isoformat() for t in times], temps, humidities)
    decoded = _decode(_encode(series), sensor_id).frame
    np.testing.assert_array_equal(decoded[Column.TEMP].to_numpy(), temps)
    np.testing.assert_array_equal(decoded[Column.RH].to_numpy(), humidities)


def test_values_use_positional_notation_with_one_fractional_digit_minimum(
    make_utc_series: UtcSeriesFactory,
) -> None:
    series = make_utc_series(
        ["2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z"], [1e-7, 1e16], [100.0, 0.25]
    )
    lines = _encode(series).decode().splitlines()
    assert lines[1] == "2026-01-01T00:00:00Z,0.0000001,100.0,,,,synthetic.csv"
    assert lines[2] == "2026-01-01T00:30:00Z,10000000000000000.0,0.25,,,,synthetic.csv"


def test_sub_second_timestamps_are_trimmed_and_lossless(
    make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    times = ["2026-01-01T00:00:00.5Z", "2026-01-01T00:00:01.000000001Z", "2026-01-01T00:00:02Z"]
    series = make_utc_series(times, [1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    encoded = _encode(series)
    assert [line.split(",")[0] for line in encoded.decode().splitlines()[1:]] == times
    assert _decode(encoded, sensor_id).timestamps.equals(series.timestamps)


def test_series_without_source_column_writes_empty_field(sensor_id: SensorId) -> None:
    series = MeasurementSeries.from_records(
        sensor_id, pd.DatetimeIndex(["2026-01-01T00:00:00Z"]), [1.5], [50.0]
    )
    assert _encode(series) == (HEADER + "2026-01-01T00:00:00Z,1.5,50.0,,,,\n").encode()
    assert _decode(_encode(series), sensor_id).frame[Column.SOURCE].tolist() == [""]


def test_empty_series_is_header_only(sensor_id: SensorId) -> None:
    encoded = _encode(MeasurementSeries.empty(sensor_id))
    assert encoded == HEADER.encode()
    assert _decode(encoded, sensor_id).is_empty


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "header"),
        (b"timestamp_utc,temp_c,rh_pct\n", "header"),
        (b"timestamp_utc;temp_c;rh_pct;source\n", "header"),
        (b"timestamp_utc,temp_c,rh_pct,battery_v,source\n", "header"),
        (HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,2.0,\n", r"test.csv:2: expected 7"),
        (HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,2.0,0,,,\n", "malformed value '0'"),
        (HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,2.0,,,inf,\n", "malformed value 'inf'"),
        (LEGACY_HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,2.0\n", r"test.csv:2: expected 4"),
        (LEGACY_HEADER.encode() + b"2026-01-01 00:00:00,1.0,2.0,\n", "malformed timestamp"),
        (LEGACY_HEADER.encode() + b"2026-01-01T00:00:00+01:00,1.0,2.0,\n", "malformed timestamp"),
        (LEGACY_HEADER.encode() + b"2026-01-01T00:00:00Z,1,2.0,\n", "malformed value '1'"),
        (LEGACY_HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,nan,\n", "malformed value 'nan'"),
        (LEGACY_HEADER.encode() + b"2026-01-01T00:00:00Z,1e3,2.0,\n", "malformed value"),
        (LEGACY_HEADER.encode() + b'2026-01-01T00:00:00Z,"1,5",2.0,\n', "malformed value"),
        (
            LEGACY_HEADER.encode()
            + b"2026-01-01T01:00:00Z,1.0,2.0,\n2026-01-01T00:00:00Z,1.0,2.0,\n",
            "strictly increasing",
        ),
        (
            LEGACY_HEADER.encode()
            + b"2026-01-01T00:00:00Z,1.0,2.0,\n2026-01-01T00:00:00Z,1.0,2.0,\n",
            "strictly increasing",
        ),
        (LEGACY_HEADER.encode() + b"2026-02-30T00:00:00Z,1.0,2.0,\n", "invalid timestamp"),
        (LEGACY_HEADER.encode() + b"2026-01-01T00:00:00Z," + b"9" * 400 + b".0,2.0,\n", "infinite"),
        (LEGACY_HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,2.0,\xff\n", "not a readable CSV"),
        (LEGACY_HEADER.encode() + b'2026-01-01T00:00:00Z,1.0,2.0,"open\n', "not a readable CSV"),
    ],
)
def test_malformed_files_are_rejected(content: bytes, message: str, sensor_id: SensorId) -> None:
    with pytest.raises(StoreFormatError, match=message):
        _decode(content, sensor_id)


def test_file_suffix() -> None:
    assert CsvSeriesCodec.file_suffix == ".csv"


def test_auxiliary_columns_round_trip_losslessly(
    make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    series = make_utc_series(
        ["2026-01-01T00:00:00Z", "2026-01-01T00:30:30Z", "2026-01-01T01:01:00Z"],
        [1.0, 2.0, 3.0],
        [50.0, 60.0, 70.0],
        precip_mm=[0.0, 0.30000000000000004, math.nan],
        precip_total_mm=[math.nan, 323.3, 323.6],
        battery_v=[3.6, 3.5, math.nan],
    )
    decoded = _decode(_encode(series), sensor_id).frame
    for column, expected in (
        (Column.PRECIP, [0.0, 0.30000000000000004, math.nan]),
        (Column.PRECIP_TOTAL, [math.nan, 323.3, 323.6]),
        (Column.BATTERY, [3.6, 3.5, math.nan]),
    ):
        np.testing.assert_array_equal(decoded[column].to_numpy(), expected)


def test_legacy_layout_is_read_with_nan_auxiliary_columns(sensor_id: SensorId) -> None:
    data = (
        LEGACY_HEADER + '2025-12-31T23:30:00Z,-0.5,88.0,old.csv\n2026-01-01T00:00:00Z,,90.0,"a,b"\n'
    ).encode()
    frame = _decode(data, sensor_id).frame
    assert frame[Column.TEMP].tolist()[0] == -0.5
    assert math.isnan(frame[Column.TEMP].tolist()[1])
    assert frame[Column.RH].tolist() == [88.0, 90.0]
    assert frame[Column.SOURCE].tolist() == ["old.csv", "a,b"]
    assert frame[[Column.PRECIP, Column.PRECIP_TOTAL, Column.BATTERY]].isna().all().all()


def test_legacy_layout_is_rewritten_in_the_current_layout(sensor_id: SensorId) -> None:
    data = (LEGACY_HEADER + "2026-01-01T00:00:00Z,1.5,50.0,old.csv\n").encode()
    rewritten = _encode(_decode(data, sensor_id))
    assert rewritten == (HEADER + "2026-01-01T00:00:00Z,1.5,50.0,,,,old.csv\n").encode()
