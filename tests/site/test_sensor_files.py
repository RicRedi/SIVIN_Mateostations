"""Per-sensor files, summaries and the sensor builder (hand-computed; data synthetic)."""

from __future__ import annotations

import json
import math

import pandas as pd
from tests.site.helpers import SENSOR, result, series

from sivin.core.flags import QcFlag
from sivin.quality.events import EventKind, EventSource, QualityEvent
from sivin.site.events import SiteEventMapping
from sivin.site.files import SiteFile
from sivin.site.model import LatestSample, SensorData
from sivin.site.sensor_builder import DailyAggregation, SensorSiteBuilder, SummaryBuilder
from sivin.site.sensor_files import (
    DailyWriter,
    RawMonthsWriter,
    SiteEventsWriter,
    default_sensor_writers,
)

PRAGUE = "Europe/Prague"
EXCLUDE = int(QcFlag.DEFAULT_EXCLUDE)
AGGREGATION = DailyAggregation(PRAGUE, 1830.0, EXCLUDE, int(QcFlag.PRE_DEPLOYMENT))

T_JAN = 1_769_902_200
"""2026-01-31T23:30:00Z = 2026-01-01 (1 767 225 600) + 30 d + 23.5 h."""
T_FEB_1 = 1_769_904_030
"""2026-02-01T00:00:30Z = 2026-01-01 + 31 d + 30 s."""
T_FEB_2 = 1_769_905_860
"""2026-02-01T00:31:00Z = 2026-01-01 + 31 d + 1860 s."""


def three_rows() -> SensorData:
    """Three SYNTHETIC samples across a UTC month boundary, all on local day 2026-02-01."""
    data = series(
        ["2026-01-31T23:30:00", "2026-02-01T00:00:30", "2026-02-01T00:31:00"],
        temp_c=[1.234, -0.004, 2.0],
        rh_pct=[92.0, math.nan, 80.0],
        qc=[0, int(QcFlag.MISSING), 0],
        precip_mm=[math.nan, math.nan, 0.2],
    )
    return SensorData(SENSOR, result(data), AGGREGATION.of(data))


def document(file: SiteFile) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(file.content)
    return loaded


def test_hand_computed_times() -> None:
    new_year = 1_767_225_600
    assert new_year + 30 * 86_400 + 84_600 == T_JAN
    assert new_year + 31 * 86_400 + 30 == T_FEB_1
    assert new_year + 31 * 86_400 + 1860 == T_FEB_2


def test_raw_months_are_utc_months_with_optional_columns_when_present() -> None:
    january, february = RawMonthsWriter().files(three_rows())
    assert january.path == "series/77678271/raw/2026-01.json"
    assert (
        january.content
        == (
            f'{{"sensor_id":"77678271","t":[{T_JAN}],"temp_c":[1.23],"rh_pct":[92.0],"qc":[0]}}\n'
        ).encode()
    )
    assert february.path == "series/77678271/raw/2026-02.json"
    assert document(february) == {
        "sensor_id": "77678271",
        "t": [T_FEB_1, T_FEB_2],
        "temp_c": [0.0, 2.0],
        "rh_pct": [None, 80.0],
        "precip_mm": [None, 0.2],
        "qc": [1, 0],
    }
    assert list(document(february)) == ["sensor_id", "t", "temp_c", "rh_pct", "precip_mm", "qc"]


def test_daily_file_in_local_days() -> None:
    (daily,) = DailyWriter().files(three_rows())
    assert daily.path == "series/77678271/daily.json"
    # Valid rows 1 and 3 (row 2 has no humidity): T 1.234 and 2.0, RH 92 and 80;
    # coverage 2 * 1830 s / 86 400 s = 0.04236; precipitation of row 3 only.
    assert document(daily) == {
        "sensor_id": "77678271",
        "date": ["2026-02-01"],
        "temp_min": [1.23],
        "temp_mean": [1.62],
        "temp_max": [2.0],
        "rh_min": [80.0],
        "rh_mean": [86.0],
        "rh_max": [92.0],
        "coverage": [0.042],
        "precip_sum_mm": [0.2],
        "precip_n_samples": [1],
    }


def test_daily_battery_column_when_present() -> None:
    data = series(["2026-02-01T10:00:00"], [5.0], [70.0], battery_v=[3.456])
    (daily,) = DailyWriter().files(SensorData(SENSOR, result(data), AGGREGATION.of(data)))
    assert document(daily)["battery_min_v"] == [3.46]
    assert "precip_sum_mm" not in document(daily)


def test_events_file_lists_published_events_only() -> None:
    data = series(["2026-02-01T10:00:00"], [5.0], [70.0])
    events = [
        QualityEvent(
            EventKind.OFF_SITE,
            pd.Timestamp("2026-02-01T09:00:00Z"),
            "office: synthetic",
            source=EventSource.LOG,
        ),
        QualityEvent(EventKind.GAP, pd.Timestamp("2026-02-01T09:00:00Z"), "gap"),
    ]
    writer = SiteEventsWriter(SiteEventMapping([EventKind.OFF_SITE]))
    (file,) = writer.files(SensorData(SENSOR, result(data, events), AGGREGATION.of(data)))
    assert file.path == "events/77678271.json"
    assert document(file) == {
        "sensor_id": "77678271",
        "events": [
            {
                "type": "off_site",
                "t": T_FEB_1 - 30 + 9 * 3600,
                "t_end": None,
                "source": "log",
                "confidence": None,
                "detail": "office: synthetic",
            }
        ],
    }


def test_summary_and_latest_valid_sample() -> None:
    summary = SummaryBuilder(PRAGUE, EXCLUDE).summary(three_rows().result.series)
    assert (summary.first_t, summary.last_t) == (T_JAN, T_FEB_2)
    assert summary.raw_months == ("2026-01", "2026-02")
    assert summary.years == (2026,)  # 2026-01-31T23:30Z is 00:30 local on 1 February
    assert summary.latest == LatestSample(T_FEB_2, 2.0, 80.0, 0)


def test_latest_skips_excluded_and_half_rows() -> None:
    data = series(
        ["2026-02-01T10:00:00", "2026-02-01T10:30:30", "2026-02-01T11:01:00"],
        [5.0, 6.0, 7.0],
        [70.0, 71.0, math.nan],
        qc=[int(QcFlag.STEP), int(QcFlag.SPIKE), 0],
    )
    latest = SummaryBuilder(PRAGUE, EXCLUDE).latest(data)
    assert latest == LatestSample(T_FEB_1 - 30 + 10 * 3600, 5.0, 70.0, int(QcFlag.STEP))


def test_no_latest_when_everything_is_off_site() -> None:
    data = series(["2026-02-01T10:00:00"], [22.0], [35.0], qc=[int(QcFlag.PRE_DEPLOYMENT)])
    assert SummaryBuilder(PRAGUE, EXCLUDE).latest(data) is None


def test_sensor_builder_collects_every_file() -> None:
    builder = SensorSiteBuilder(
        AGGREGATION,
        SummaryBuilder(PRAGUE, EXCLUDE),
        default_sensor_writers(SiteEventMapping([EventKind.OFF_SITE])),
    )
    built = builder.build(SENSOR, three_rows().result)
    assert built is not None
    assert [file.path for file in built.files] == [
        "series/77678271/raw/2026-01.json",
        "series/77678271/raw/2026-02.json",
        "series/77678271/daily.json",
        "events/77678271.json",
    ]
    empty = series([], [], [])
    assert builder.build(SENSOR, result(empty)) is None
    assert RawMonthsWriter().files(SensorData(SENSOR, result(empty), AGGREGATION.of(empty))) == []
    assert DailyWriter().files(SensorData(SENSOR, result(empty), AGGREGATION.of(empty))) == []
