"""``gdd_winkler`` and ``huglin``: hand-computed examples and legacy parity (synthetic data)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.analytics.base import IndexContext, index_registry
from sivin.analytics.thermal import (
    GddWinklerIndex,
    GddWinklerParams,
    HuglinIndex,
    HuglinParams,
    LatitudeBand,
)
from sivin.analytics.thermal.base import NO_COMPLETE_DAYS
from sivin.analytics.thermal.huglin import NO_COEFFICIENT
from sivin.core.daily import DailyWeather
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries

PRAGUE = "Europe/Prague"
SAMPLE_INTERVAL_S = 1825
SYNTHETIC_SEED = 20261005

DailyFactory = Callable[..., DailyWeather]
ContextFactory = Callable[..., IndexContext]
ConstantDays = Callable[[date, int, tuple[float, float, float]], dict[date, tuple[float, ...]]]

# Four synthetic days (tmin, tmean, tmax) around the start of the GDD/Huglin season.
HAND_DAYS = {
    date(2026, 3, 31): (15.0, 19.0, 25.0),  # outside the season
    date(2026, 4, 1): (8.0, 13.0, 16.0),
    date(2026, 4, 2): (4.0, 9.0, 12.0),
    date(2026, 4, 3): (12.0, 18.0, 22.0),
    date(2026, 4, 4): (20.0, 25.0, 30.0),  # incomplete (coverage 0.5)
}
HAND_COVERAGE = {date(2026, 4, 4): 0.5}


@pytest.fixture
def hand_context(make_daily: DailyFactory, make_context: ContextFactory) -> IndexContext:
    return make_context(make_daily(HAND_DAYS, HAND_COVERAGE))


def test_gdd_hand_computed(hand_context: IndexContext) -> None:
    result = GddWinklerIndex().compute(hand_context)
    # minmax means: Apr 1 (8+16)/2 = 12 -> 2; Apr 2 (4+12)/2 = 8 -> 0; Apr 3 (12+22)/2 = 17 -> 7
    # Mar 31 is outside the season, Apr 4 is incomplete.
    assert result.value == 9.0
    assert result.unit == "°C·d"
    assert result.daily is not None
    assert result.daily.tolist() == [2.0, 2.0, 9.0]
    assert list(result.daily.index) == [date(2026, 4, d) for d in (1, 2, 3)]
    assert result.coverage == pytest.approx(3 / 214)  # April 1 - October 31 = 214 days
    assert result.complete is False
    assert result.classification is None  # no region for an incomplete season
    assert result.details["n_days"] == 3
    assert result.estimated is False


def test_gdd_sample_mean_option(hand_context: IndexContext) -> None:
    result = GddWinklerIndex(GddWinklerParams(daily_mean="sample_mean")).compute(hand_context)
    # sample means 13 -> 3, 9 -> 0, 18 -> 8
    assert result.value == 11.0


def test_gdd_full_season_region(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 4, 1), 214, (12.0, 15.0, 24.0))
    result = GddWinklerIndex().compute(make_context(make_daily(days)))
    # (12 + 24) / 2 - 10 = 8 °C·d per day * 214 days = 1712 -> region III (1666.7, 1944.4]
    assert result.value == pytest.approx(1712.0)
    assert result.coverage == 1.0
    assert result.complete is True
    assert result.classification == "region_iii"


def test_gdd_season_below_coverage_threshold_has_no_region(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 4, 1), 192, (12.0, 15.0, 24.0))  # 192 / 214 = 0.897
    result = GddWinklerIndex().compute(make_context(make_daily(days)))
    assert result.value == pytest.approx(192 * 8.0)
    assert result.complete is False
    assert result.classification is None


def test_gdd_empty_season(make_daily: DailyFactory, make_context: ContextFactory) -> None:
    ctx = make_context(make_daily({date(2026, 3, 31): (15.0, 19.0, 25.0)}))
    result = GddWinklerIndex().compute(ctx)
    assert result.value is None
    assert result.coverage == 0.0
    assert result.complete is False
    assert result.daily is None
    assert result.details == {"n_days": 0, "status": NO_COMPLETE_DAYS}


def test_huglin_hand_computed(hand_context: IndexContext) -> None:
    result = HuglinIndex().compute(hand_context)
    # K = 1.06 at 48.88° N; minmax means 12, 8, 17 with maxima 16, 12, 22:
    # Apr 1: ((12-10) + (16-10)) / 2 = 4   -> 4.24
    # Apr 2: ((8-10) + (12-10)) / 2 = 0     -> 0
    # Apr 3: ((17-10) + (22-10)) / 2 = 9.5 -> 10.07
    assert result.value == pytest.approx(14.31)
    assert result.daily is not None
    assert result.daily.tolist() == pytest.approx([4.24, 4.24, 14.31])
    assert result.details["k"] == 1.06
    assert result.coverage == pytest.approx(3 / 183)  # April 1 - September 30 = 183 days
    assert result.classification is None


def test_huglin_full_season_class(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 4, 1), 183, (12.0, 15.0, 24.0))
    result = HuglinIndex().compute(make_context(make_daily(days)))
    # ((18 - 10) + (24 - 10)) / 2 = 11 * 1.06 = 11.66 per day * 183 = 2133.78
    assert result.value == pytest.approx(2133.78)
    assert result.complete is True
    assert result.classification == "temperate_warm"  # (2100, 2400]


@pytest.mark.parametrize(
    ("latitude_deg", "expected_k"),
    [(40.0, 1.02), (41.99, 1.02), (42.0, 1.03), (45.0, 1.04), (47.5, 1.05), (48.88, 1.06)],
)
def test_huglin_k_by_latitude(latitude_deg: float, expected_k: float) -> None:
    assert HuglinParams().coefficient(latitude_deg) == expected_k


@pytest.mark.parametrize("latitude_deg", [None, 39.9, 50.0, -48.88])
def test_huglin_without_k(
    latitude_deg: float | None, make_daily: DailyFactory, make_context: ContextFactory
) -> None:
    assert HuglinParams().coefficient(latitude_deg) is None
    ctx = make_context(make_daily(HAND_DAYS, HAND_COVERAGE), latitude_deg=latitude_deg)
    result = HuglinIndex().compute(ctx)
    assert result.value is None
    assert result.details["status"] == NO_COEFFICIENT
    # with an override the latitude is not needed: 1.05 * (4 + 0 + 9.5) = 14.175
    overridden = HuglinIndex(HuglinParams(k_override=1.05)).compute(ctx)
    assert overridden.value == pytest.approx(14.175)


def test_huglin_empty_season(make_daily: DailyFactory, make_context: ContextFactory) -> None:
    result = HuglinIndex().compute(make_context(make_daily({date(2026, 10, 1): (5, 9, 14)})))
    assert result.value is None
    assert result.details["status"] == NO_COMPLETE_DAYS


def test_huglin_params_validation() -> None:
    with pytest.raises(ValidationError):
        HuglinParams(k_override=0.0)
    with pytest.raises(ValidationError, match="must exceed"):
        LatitudeBand(min_lat_deg=50.0, max_lat_deg=48.0, k=1.0)
    custom = HuglinParams(k_bands=(LatitudeBand(min_lat_deg=48.0, max_lat_deg=49.0, k=1.1),))
    assert custom.coefficient(48.5) == 1.1


def test_registry_creates_thermal_indices_from_config_mappings() -> None:
    gdd = index_registry.create("gdd_winkler", {"daily_mean": "sample_mean"})
    assert isinstance(gdd, GddWinklerIndex)
    huglin = index_registry.create("huglin", {"k_override": 1.05})
    assert isinstance(huglin, HuglinIndex)
    with pytest.raises(ValidationError):
        index_registry.create("huglin", {"k_overide": 1.05})


def _synthetic_june_series(sensor_id: SensorId) -> MeasurementSeries:
    """Ten synthetic local days (June 1-10, 2026) sampled every 1825 s, seeded noise."""
    start = pd.Timestamp("2026-06-01 00:00", tz=PRAGUE)
    end = pd.Timestamp("2026-06-11 00:00", tz=PRAGUE)
    stamps = pd.date_range(start, end, freq=f"{SAMPLE_INTERVAL_S}s", inclusive="left")
    hours = (stamps - start).total_seconds().to_numpy() / 3600.0
    rng = np.random.default_rng(SYNTHETIC_SEED)
    # Mean around 11 °C, so some days contribute nothing (exercises the clip at 0).
    temp_c = 11.0 + 7.0 * np.sin(2 * np.pi * (hours - 9.0) / 24.0) + rng.normal(0, 2.0, len(hours))
    temp_c += np.repeat(rng.normal(0, 3.0, 10), int(np.ceil(len(hours) / 10)))[: len(hours)]
    return MeasurementSeries.from_records(sensor_id, stamps, temp_c, np.full(len(hours), 70.0))


def _legacy_daily(series: MeasurementSeries) -> pd.DataFrame:
    """Daily max/min/mean the way the legacy script grouped them (by local calendar date)."""
    frame = series.frame
    local = frame[Column.TIMESTAMP].dt.tz_convert(PRAGUE)
    return frame.groupby(local.dt.date)[Column.TEMP].agg(["max", "min", "mean"])


def _legacy_gdd(series: MeasurementSeries, base_temp: float = 10.0) -> float:
    """Formula of legacy ``vineyard_analyst.calculate_gdd``."""
    daily = _legacy_daily(series)
    return float(((daily["max"] + daily["min"]) / 2 - base_temp).clip(lower=0).sum())


def _legacy_huglin(series: MeasurementSeries, lat_coeff: float = 1.05) -> float:
    """Formula of legacy ``vineyard_analyst.calculate_huglin_index`` (data within Apr-Sep)."""
    daily = _legacy_daily(series)
    hi_daily = ((daily["mean"] - 10) + (daily["max"] - 10)) / 2
    return float((hi_daily.clip(lower=0) * lat_coeff).sum())


@pytest.fixture
def raw_context(sensor_id: SensorId, make_context: ContextFactory) -> IndexContext:
    series = _synthetic_june_series(sensor_id)
    daily = DailyWeather.from_series(
        series, PRAGUE, float(SAMPLE_INTERVAL_S), int(QcFlag.DEFAULT_EXCLUDE)
    )
    assert len(daily.complete_days(0.9)) == 10  # every synthetic day is complete
    return make_context(daily, series=series)


def test_gdd_parity_with_legacy(raw_context: IndexContext) -> None:
    legacy = _legacy_gdd(raw_context.series)
    assert legacy > 0.0
    result = GddWinklerIndex().compute(raw_context)
    assert result.value == pytest.approx(legacy, rel=1e-12)


def test_huglin_parity_with_legacy(raw_context: IndexContext) -> None:
    legacy = _legacy_huglin(raw_context.series)
    daily = _legacy_daily(raw_context.series)
    assert ((daily["mean"] + daily["max"]) / 2 < 10).any()  # the clip at 0 is exercised
    params = HuglinParams(daily_mean="sample_mean", k_override=1.05)
    result = HuglinIndex(params).compute(raw_context)
    assert result.value == pytest.approx(legacy, rel=1e-12)
