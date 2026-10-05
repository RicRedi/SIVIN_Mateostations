"""Short export identifiers in the ``source`` column (owner decision 2026-10-05).

All measurement values are synthetic; the file names follow the portal's documented spelling.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sivin.core.ids import SensorId
from sivin.core.schema import Column
from sivin.storage.source import ExportSourceIds
from sivin.storage.store import MeasurementStore

from .conftest import UtcSeriesFactory

XLSX_WITHOUT_TIME = "MeteoData_8615620 77678271.xlsx"
XLSX_WITHOUT_TIME_SHA256 = "e23fdca307a7e91bb19cc02f1019c4dfb3c422995948676e203465d96c58fe89"
"""``printf 'MeteoData_8615620 77678271.xlsx' | sha256sum``."""

IDS = ExportSourceIds()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("MeteoData_8615620 77678271 (VUT)_20260301_223857.csv", "20260301T223857"),
        ("MeteoData_8615620_77799986_VUT_20260301_223842.csv", "20260301T223842"),
        ("MeteoData_8615620 77680921  (VUT)_20260105_173301.xlsx", "20260105T173301"),
        ("MeteoData_8615620 77678271 (VUT)_20260301_223857 (1).xlsx", "20260301T223857"),
        ("/data/downloads/MeteoData_8615620 77678271 (VUT)_20260301_223857.csv", "20260301T223857"),
        (
            r"C:\Users\x\Downloads\MeteoData_8615620 77678271 (VUT)_20260301_223857.csv",
            "20260301T223857",
        ),
        ("20260501_060000", "20260501T060000"),
        (XLSX_WITHOUT_TIME, "h" + XLSX_WITHOUT_TIME_SHA256[:12]),
        (f"/somewhere/{XLSX_WITHOUT_TIME}", "h" + XLSX_WITHOUT_TIME_SHA256[:12]),
        ("20260301T223857", "20260301T223857"),
        ("h" + XLSX_WITHOUT_TIME_SHA256[:12], "h" + XLSX_WITHOUT_TIME_SHA256[:12]),
        ("", ""),
    ],
)
def test_short_identifier_of_a_source(source: str, expected: str) -> None:
    assert IDS.of(source) == expected
    assert IDS.of(IDS.of(source)) == expected  # idempotent


@pytest.mark.parametrize(
    ("value", "is_id"),
    [
        ("20260301T223857", True),
        ("h0123456789ab", True),
        ("h0123456789AB", False),
        ("h0123456789a", False),
        ("20260301_223857", False),
        ("export.csv", False),
        ("", False),
    ],
)
def test_is_identifier(value: str, is_id: bool) -> None:
    assert ExportSourceIds.is_identifier(value) is is_id


def test_shorten_returns_the_same_series_when_nothing_changes(
    make_utc_series: UtcSeriesFactory,
) -> None:
    without_source = make_utc_series(["2026-05-01T00:00:00Z"], [1.0], [50.0], source=None)
    identifiers = make_utc_series(["2026-05-01T00:00:00Z"], [1.0], [50.0], "20260501T060000")
    assert IDS.shorten(without_source) is without_source
    assert IDS.shorten(identifiers) is identifiers


def test_shorten_maps_every_row(make_utc_series: UtcSeriesFactory) -> None:
    series = make_utc_series(
        ["2026-05-01T00:00:00Z", "2026-05-01T00:30:00Z", "2026-05-01T01:00:00Z"],
        [1.0, 2.0, 3.0],
        [50.0, 51.0, 52.0],
        ["MeteoData_8615620_77678271_VUT_20260501_060000.csv", "", "20260502T060000"],
    )
    shortened = IDS.shorten(series)
    assert shortened.frame[Column.SOURCE].tolist() == ["20260501T060000", "", "20260502T060000"]
    assert shortened.frame[Column.TEMP].tolist() == [1.0, 2.0, 3.0]


def test_store_writes_short_identifiers(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    store.append(
        make_utc_series(
            ["2026-05-01T00:00:00Z"],
            [12.3],
            [80.0],
            "MeteoData_8615620 77678271 (VUT)_20260501_060000.csv",
        )
    )
    lines = (store.root / "raw" / str(sensor_id) / "2026.csv").read_text().splitlines()
    assert lines[1] == "2026-05-01T00:00:00Z,12.3,80.0,,,,20260501T060000"
    assert store.read(sensor_id).frame[Column.SOURCE].tolist() == ["20260501T060000"]


def test_old_file_with_full_names_reads_as_identifiers_and_is_rewritten_only_on_change(
    tmp_path: Path, make_utc_series: UtcSeriesFactory, sensor_id: SensorId
) -> None:
    path = tmp_path / "data" / "raw" / str(sensor_id) / "2026.csv"
    path.parent.mkdir(parents=True)
    old_text = (
        "timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source\n"
        "2026-05-01T00:00:00Z,12.3,80.0,,,,MeteoData_8615620 77678271 (VUT)_20260501_060000.csv\n"
    )
    path.write_text(old_text, encoding="utf-8")
    store = MeasurementStore(tmp_path / "data")

    assert store.read(sensor_id).frame[Column.SOURCE].tolist() == ["20260501T060000"]
    identical = make_utc_series(["2026-05-01T00:00:00Z"], [12.3], [80.0], "20260501T060000")
    assert store.append(identical).files_written == ()
    assert path.read_text(encoding="utf-8") == old_text

    later = make_utc_series(
        ["2026-05-01T00:30:00Z"],
        [12.4],
        [81.0],
        "MeteoData_8615620 77678271 (VUT)_20260502_060000.csv",
    )
    store.append(later)
    assert path.read_text(encoding="utf-8").splitlines()[1:] == [
        "2026-05-01T00:00:00Z,12.3,80.0,,,,20260501T060000",
        "2026-05-01T00:30:00Z,12.4,81.0,,,,20260502T060000",
    ]


def test_conflicts_name_the_identifiers(
    store: MeasurementStore, make_utc_series: UtcSeriesFactory
) -> None:
    store.append(make_utc_series(["2026-05-01T00:00:00Z"], [3.0], [70.0], "x_20260501_060000.csv"))
    result = store.append(
        make_utc_series(["2026-05-01T00:00:00Z"], [3.1], [70.0], "x_20260502_060000.csv")
    )
    (decision,) = result.conflicts
    assert decision.conflict.stored_source == "20260501T060000"
    assert decision.conflict.incoming_source == "20260502T060000"
