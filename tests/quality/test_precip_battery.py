"""Precipitation and battery checks (WP-1.9).

Synthetic series are SYNTHETIC; the last tests run on the trimmed REAL export of sensor
77799986 (public by owner decision 2026-10-05). Expectations are hand-computed in comments.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries
from sivin.ingest.parsers.base import parser_registry
from sivin.ingest.parsers.columns import ParserSettings
from sivin.quality.checks import (
    BatteryCheck,
    BatterySettings,
    CounterSteps,
    PrecipCounterCheck,
    PrecipCounterSettings,
    PrecipRangeCheck,
    PrecipRangeSettings,
    check_registry,
    runs_of,
)
from sivin.quality.events import EventKind, Severity
from sivin.quality.pipeline import QualityPipeline, QualityPipelineSettings

SENSOR = SensorId("77678271")
NAN = math.nan
START = pd.Timestamp("2026-06-01T00:00:00Z")
STEP_S = 1830.0
REAL_EXPORT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "exports"
    / "real"
    / "MeteoData_8615620_77799986_VUT_20260301_223842.csv"
)


def _series(
    offsets_s: Sequence[float],
    *,
    temp_c: Sequence[float] | None = None,
    qc: Sequence[int] | None = None,
    precip_mm: Sequence[float] | None = None,
    precip_total_mm: Sequence[float] | None = None,
    battery_v: Sequence[float] | None = None,
) -> MeasurementSeries:
    n_rows = len(offsets_s)
    return MeasurementSeries.from_records(
        SENSOR,
        pd.DatetimeIndex([START + pd.Timedelta(seconds=s) for s in offsets_s]),
        temp_c if temp_c is not None else [15.0] * n_rows,
        [70.0] * n_rows,
        qc=qc,
        precip_mm=precip_mm,
        precip_total_mm=precip_total_mm,
        battery_v=battery_v,
    )


def _at(offset_s: float) -> pd.Timestamp:
    return START + pd.Timedelta(seconds=offset_s)


def _regular(n_rows: int) -> list[float]:
    return [i * STEP_S for i in range(n_rows)]


def test_checks_are_registered_with_their_settings() -> None:
    assert isinstance(check_registry.create("precip_range"), PrecipRangeCheck)
    assert isinstance(check_registry.create("precip_counter"), PrecipCounterCheck)
    battery = check_registry.create("battery", {"low_battery_v": 3.4})
    assert isinstance(battery, BatteryCheck)
    assert battery.settings.low_battery_v == 3.4
    with pytest.raises(ValidationError):
        check_registry.create("battery", {"low_battery_volts": 3.4})


def test_default_settings() -> None:
    assert (PrecipRangeSettings().precip_min_mm, PrecipRangeSettings().precip_max_mm) == (
        0.0,
        50.0,
    )
    assert PrecipCounterSettings().tolerance_mm == 0.15
    assert PrecipCounterSettings().max_interval_s == 2745.0  # 1.5 * 1830 s
    assert BatterySettings().low_battery_v == 3.3
    with pytest.raises(ValidationError, match="lower than precip_max_mm"):
        PrecipRangeSettings(precip_min_mm=5.0, precip_max_mm=5.0)


def test_runs_of() -> None:
    mask = np.array([False, True, True, False, True])
    assert runs_of(mask) == ((1, 2), (4, 4))
    # Row 2 does not take part: it neither ends the run of rows 1 and 3 nor belongs to it.
    considered = np.array([True, True, False, True, True])
    assert runs_of(np.array([False, True, False, True, False]), considered) == ((1, 3),)
    assert runs_of(np.array([], dtype=np.bool_)) == ()
    assert runs_of(np.array([True, True])) == ((0, 1),)


class TestPrecipRangeCheck:
    # precip: 0.0, -0.2, NaN, -0.1, 0.5, 60.0 with the default range [0, 50] mm.
    # Implausible: rows 1, 3 (negative) and 5 (> 50 mm). Row 2 is missing and does not end the
    # run of rows 1 and 3 -> runs (1, 3) and (5, 5).
    PRECIP = (0.0, -0.2, NAN, -0.1, 0.5, 60.0)

    def test_events_without_flags(self) -> None:
        series = _series(_regular(6), precip_mm=self.PRECIP)
        outcome = PrecipRangeCheck().check(series)
        assert outcome.flags.tolist() == [0] * 6
        first, second = outcome.events
        assert (first.kind, first.severity, first.origin) == (
            EventKind.PRECIP_OUT_OF_RANGE,
            Severity.WARNING,
            "precip_range",
        )
        assert (first.t_utc, first.end_utc) == (_at(STEP_S), _at(3 * STEP_S))
        assert first.detail.startswith("2 precipitation value(s) outside [0, 50] mm per interval")
        assert "lowest -0.2 mm, highest -0.1 mm" in first.detail
        assert (second.t_utc, second.end_utc) == (_at(5 * STEP_S), _at(5 * STEP_S))
        assert "1 precipitation value(s)" in second.detail
        assert "lowest 60 mm, highest 60 mm" in second.detail

    def test_set_aside_keeps_the_row(self) -> None:
        qc = [0, int(QcFlag.STEP), 0, 0, 0, 0]
        series = _series(_regular(6), qc=qc, precip_mm=self.PRECIP, battery_v=[3.6] * 6)
        cleaned = PrecipRangeCheck().set_aside(series)
        np.testing.assert_array_equal(
            cleaned.frame[Column.PRECIP].to_numpy(), [0.0, NAN, NAN, NAN, 0.5, NAN]
        )
        assert cleaned.frame[Column.QC].tolist() == qc
        assert cleaned.frame[Column.TEMP].tolist() == [15.0] * 6
        assert cleaned.frame[Column.BATTERY].tolist() == [3.6] * 6
        exclude = int(QcFlag.DEFAULT_EXCLUDE)
        assert cleaned.complete_mask(exclude).tolist() == series.complete_mask(exclude).tolist()

    def test_no_precipitation_column_no_event(self) -> None:
        outcome = PrecipRangeCheck().check(_series(_regular(3)))
        assert outcome.events == ()
        assert outcome.flags.tolist() == [0, 0, 0]


class TestPrecipCounterCheck:
    # Row  t (s)  precip  total   increase  outcome
    #  0       0    0.0   323.0        -    first counter value
    #  1    1830    0.3   323.3      0.3    agrees
    #  2    3660    0.3   323.7      0.4    differs by 0.1 <= 0.15 (rounding): agrees
    #  3    5490    0.0   324.5      0.8    mismatch (0.8)
    #  4    7320    0.1   325.0      0.5    mismatch (0.4)
    #  5   10830    0.0   326.0      1.0    not compared: 3510 s > 2745 s after row 4
    #  6   12660    0.0     0.0   -326.0    reset (not compared)
    #  7   14490    0.2     0.2      0.2    agrees
    #  8   16320    NaN     0.2      0.0    not compared: no interval value
    #  9   18150    0.5     NaN        -    not compared: no counter value
    # 10   19980    0.0     0.7      0.5    not compared: the previous row has no counter
    T_S = (0, 1830, 3660, 5490, 7320, 10830, 12660, 14490, 16320, 18150, 19980)
    PRECIP = (0.0, 0.3, 0.3, 0.0, 0.1, 0.0, 0.0, 0.2, NAN, 0.5, 0.0)
    TOTAL = (323.0, 323.3, 323.7, 324.5, 325.0, 326.0, 0.0, 0.2, 0.2, NAN, 0.7)

    def test_counter_steps_by_hand(self) -> None:
        steps = CounterSteps.of(
            np.array(self.T_S, dtype=np.float64),
            np.array(self.PRECIP),
            np.array(self.TOTAL),
            PrecipCounterSettings(),
        )
        np.testing.assert_allclose(
            steps.increase_mm,
            [NAN, 0.3, 0.4, 0.8, 0.5, 1.0, -326.0, 0.2, 0.0, NAN, 0.5],
            atol=1e-9,
        )
        assert np.flatnonzero(steps.reset).tolist() == [6]
        assert np.flatnonzero(steps.compared).tolist() == [1, 2, 3, 4, 7]
        assert np.flatnonzero(steps.mismatch).tolist() == [3, 4]

    def test_events(self) -> None:
        series = _series(
            [float(t) for t in self.T_S], precip_mm=self.PRECIP, precip_total_mm=self.TOTAL
        )
        outcome = PrecipCounterCheck().check(series)
        assert outcome.flags.tolist() == [0] * len(self.T_S)
        mismatch, reset = outcome.events
        assert (reset.kind, reset.severity, reset.t_utc) == (
            EventKind.PRECIP_COUNTER_RESET,
            Severity.INFO,
            _at(12660),
        )
        assert reset.detail == "precipitation counter decreased by 326 mm to 0 mm (device reset)"
        assert (mismatch.kind, mismatch.severity) == (
            EventKind.PRECIP_COUNTER_MISMATCH,
            Severity.WARNING,
        )
        assert (mismatch.t_utc, mismatch.end_utc) == (_at(5490), _at(7320))
        assert mismatch.detail == (
            "2 interval precipitation value(s) differ from the counter increase by more than "
            "0.15 mm (largest difference 0.8 mm)"
        )

    def test_small_decrease_is_rounding_not_a_reset(self) -> None:
        series = _series(_regular(3), precip_mm=[0.0, 0.0, 0.1], precip_total_mm=[5.1, 5.0, 5.1])
        assert PrecipCounterCheck().check(series).events == ()

    def test_without_counter_nothing_is_compared(self) -> None:
        series = _series(_regular(3), precip_mm=[0.0, 4.0, 0.1])
        assert PrecipCounterCheck().check(series).events == ()


class TestBatteryCheck:
    # 3.6, 3.2, NaN, 3.1, 3.4, 3.2 below 3.3 V: rows 1, 3, 5; the NaN of row 2 does not end the
    # run -> runs (1, 3) with lowest 3.1 V and (5, 5) with 3.2 V.
    def test_low_battery_events_without_flags(self) -> None:
        series = _series(_regular(6), battery_v=[3.6, 3.2, NAN, 3.1, 3.4, 3.2])
        outcome = BatteryCheck().check(series)
        assert outcome.flags.tolist() == [0] * 6
        first, second = outcome.events
        assert (first.kind, first.severity, first.origin) == (
            EventKind.LOW_BATTERY,
            Severity.WARNING,
            "battery",
        )
        assert (first.t_utc, first.end_utc) == (_at(STEP_S), _at(3 * STEP_S))
        assert first.detail == "low battery: 2 reading(s) below 3.3 V (lowest 3.1 V)"
        assert (second.t_utc, second.end_utc) == (_at(5 * STEP_S), _at(5 * STEP_S))
        assert second.detail == "low battery: 1 reading(s) below 3.3 V (lowest 3.2 V)"

    def test_threshold_is_exclusive_and_missing_is_silent(self) -> None:
        series = _series(_regular(3), battery_v=[3.3, NAN, 3.5])
        assert BatteryCheck().check(series).events == ()


def test_pipeline_flags_do_not_change_when_the_checks_are_enabled() -> None:
    temps = [15.0, 15.1, 15.2, 40.0, 15.3, NAN]
    series = _series(
        _regular(6),
        temp_c=temps,
        precip_mm=[0.0, -1.0, 0.0, 0.0, 0.2, 0.0],
        precip_total_mm=[1.0, 1.0, 1.0, 5.0, 5.2, 5.2],
        battery_v=[3.0] * 6,
    )
    base = ("missing", "sampling", "range")
    settings = {
        "deployed_checks": (),
        "detect_deployment": False,
        "check_settings": {"range": {"temp_climate_max_c": 35.0}},
    }
    plain = QualityPipeline.from_settings(
        QualityPipelineSettings(screening_checks=base, **settings)
    ).run(series)
    extended = QualityPipeline.from_settings(
        QualityPipelineSettings(
            screening_checks=(*base, "precip_range", "precip_counter", "battery"), **settings
        )
    ).run(series)
    qc = extended.series.frame[Column.QC].tolist()
    assert qc == plain.series.frame[Column.QC].tolist()
    assert qc == [0, 0, 0, int(QcFlag.OUT_OF_RANGE), 0, int(QcFlag.MISSING)]
    kinds = sorted(str(event.kind) for event in extended.events if event.origin)
    assert {"precip_out_of_range", "precip_counter_mismatch", "low_battery"} <= set(kinds)


@pytest.fixture(scope="module")
def real_series() -> MeasurementSeries:
    settings = ParserSettings(latest_timestamp=datetime(2030, 1, 1))
    parsed = parser_registry.for_file(REAL_EXPORT, settings).parse(REAL_EXPORT)
    (series,) = parsed.series
    return series


def test_real_export_precipitation_is_consistent_within_the_default_tolerance(
    real_series: MeasurementSeries,
) -> None:
    assert PrecipRangeCheck().check(real_series).events == ()
    assert PrecipCounterCheck().check(real_series).events == ()


def test_real_export_shows_the_rounding_difference_with_a_strict_tolerance(
    real_series: MeasurementSeries,
) -> None:
    # Lines "2025-12-19 13:36:46;...;0,0;323,6" and "2025-12-19 14:07:16;...;0,3;324,0;3,50"
    # (CET): interval 0.3 mm, counter +0.4 mm -> difference 0.1 mm > 0.05 mm.
    strict = PrecipCounterCheck(PrecipCounterSettings(tolerance_mm=0.05))
    (event,) = strict.check(real_series).events
    assert event.kind is EventKind.PRECIP_COUNTER_MISMATCH
    assert event.t_utc == pd.Timestamp("2025-12-19T13:07:16Z")
    assert "1 interval precipitation value(s)" in event.detail
    assert "largest difference 0.1 mm" in event.detail


def test_real_export_low_battery_at_the_start(real_series: MeasurementSeries) -> None:
    # The two oldest lines read 3,00 V (2025-07-30 10:22:29 and 13:54:45 CEST); the next line
    # (2025-07-31 13:21:23) reads 3,70 V and no later line is below 3.3 V.
    (event,) = BatteryCheck().check(real_series).events
    assert event.t_utc == pd.Timestamp("2025-07-30T08:22:29Z")
    assert event.end_utc == pd.Timestamp("2025-07-30T11:54:45Z")
    assert event.detail == "low battery: 2 reading(s) below 3.3 V (lowest 3 V)"
