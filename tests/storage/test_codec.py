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

HEADER = "timestamp_utc,temp_c,rh_pct,source\n"


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
    )
    expected = (
        HEADER + "2026-01-01T00:00:00Z,1.2,92.0,a.csv\n"
        '2026-01-01T00:30:25Z,-0.5,,"b, ""quoted"".csv"\n'
        "2026-01-01T01:00:50Z,12.0,100.0,c.csv\n"
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
        HEADER + "2025-12-31T23:30:00Z,-0.0,,\n"
        '2026-01-01T00:00:00.5Z,0.30000000000000004,99.9,"a,b"\n'
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
    assert lines[1] == "2026-01-01T00:00:00Z,0.0000001,100.0,synthetic.csv"
    assert lines[2] == "2026-01-01T00:30:00Z,10000000000000000.0,0.25,synthetic.csv"


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
    assert _encode(series) == (HEADER + "2026-01-01T00:00:00Z,1.5,50.0,\n").encode()
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
        (HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,2.0\n", r"test.csv:2: expected 4"),
        (HEADER.encode() + b"2026-01-01 00:00:00,1.0,2.0,\n", "malformed timestamp"),
        (HEADER.encode() + b"2026-01-01T00:00:00+01:00,1.0,2.0,\n", "malformed timestamp"),
        (HEADER.encode() + b"2026-01-01T00:00:00Z,1,2.0,\n", "malformed value '1'"),
        (HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,nan,\n", "malformed value 'nan'"),
        (HEADER.encode() + b"2026-01-01T00:00:00Z,1e3,2.0,\n", "malformed value"),
        (HEADER.encode() + b'2026-01-01T00:00:00Z,"1,5",2.0,\n', "malformed value"),
        (
            HEADER.encode() + b"2026-01-01T01:00:00Z,1.0,2.0,\n2026-01-01T00:00:00Z,1.0,2.0,\n",
            "strictly increasing",
        ),
        (
            HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,2.0,\n2026-01-01T00:00:00Z,1.0,2.0,\n",
            "strictly increasing",
        ),
        (HEADER.encode() + b"2026-02-30T00:00:00Z,1.0,2.0,\n", "invalid timestamp"),
        (HEADER.encode() + b"2026-01-01T00:00:00Z," + b"9" * 400 + b".0,2.0,\n", "infinite"),
        (HEADER.encode() + b"2026-01-01T00:00:00Z,1.0,2.0,\xff\n", "not a readable CSV"),
        (HEADER.encode() + b'2026-01-01T00:00:00Z,1.0,2.0,"open\n', "not a readable CSV"),
    ],
)
def test_malformed_files_are_rejected(content: bytes, message: str, sensor_id: SensorId) -> None:
    with pytest.raises(StoreFormatError, match=message):
        _decode(content, sensor_id)


def test_file_suffix() -> None:
    assert CsvSeriesCodec.file_suffix == ".csv"
