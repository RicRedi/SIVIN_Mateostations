"""Tests of the ClimateIndex extension point with a test-only dummy index."""

from __future__ import annotations

import dataclasses
from datetime import date

import pandas as pd
import pytest
from pydantic import Field, ValidationError

from sivin.analytics.base import (
    ClimateIndex,
    IndexContext,
    IndexParams,
    IndexRegistry,
    IndexResult,
    index_registry,
)
from sivin.core.daily import DailyWeather
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries
from sivin.core.season import MonthDay, Season

PRAGUE = "Europe/Prague"
SIX_HOURS_S = 6 * 3600.0


class MeanAboveParams(IndexParams):
    base_temp_c: float = Field(10.0, description="Base temperature in °C (test value).")


class MeanAboveIndex(ClimateIndex[MeanAboveParams]):
    """Sum of (daily mean - base) over complete days of three test days in September."""

    index_id = "test_mean_above"
    unit = "°C·d"
    params_model = MeanAboveParams
    season = Season(MonthDay(9, 1), MonthDay(9, 3))

    def compute(self, ctx: IndexContext) -> IndexResult:
        selection = self._season_days(ctx, self.season)
        excess = (selection.days.frame["temp_mean"] - self.params.base_temp_c).clip(lower=0)
        return IndexResult(
            index_id=self.index_id,
            sensor_id=ctx.sensor_id,
            year=ctx.year,
            value=float(excess.sum()),
            unit=self.unit,
            coverage=selection.coverage,
            complete=selection.complete,
            details={"n_days": len(selection.days)},
        )


@pytest.fixture
def context(sensor_id: SensorId) -> IndexContext:
    """Synthetic 6-hourly data on Sep 1-3; Sep 2 has only 2 samples (coverage 0.5)."""
    local = [
        *[f"2026-09-01 {h:02d}:00" for h in (0, 6, 12, 18)],  # temps 12,14,16,18 -> mean 15
        *[f"2026-09-02 {h:02d}:00" for h in (0, 6)],  # incomplete day
        *[f"2026-09-03 {h:02d}:00" for h in (0, 6, 12, 18)],  # temps 8,10,12,14 -> mean 11
    ]
    temps = [12.0, 14.0, 16.0, 18.0, 30.0, 30.0, 8.0, 10.0, 12.0, 14.0]
    stamps = pd.DatetimeIndex(pd.to_datetime(local)).tz_localize(PRAGUE)
    series = MeasurementSeries.from_records(sensor_id, stamps, temps, [70.0] * len(temps))
    daily = DailyWeather.from_series(series, PRAGUE, SIX_HOURS_S, int(QcFlag.DEFAULT_EXCLUDE))
    return IndexContext(
        sensor_id=sensor_id,
        year=2026,
        daily=daily,
        series=series,
        latitude_deg=48.88,
        elevation_m=184.0,
        timezone=PRAGUE,
        min_daily_coverage=0.9,
        min_season_coverage=0.9,
        exclude_mask=int(QcFlag.DEFAULT_EXCLUDE),
    )


def test_dummy_index_hand_computed(context: IndexContext) -> None:
    result = MeanAboveIndex().compute(context)
    # Complete days: Sep 1 (mean 15 -> 5) and Sep 3 (mean 11 -> 1); Sep 2 is incomplete.
    assert result.value == 6.0
    assert result.coverage == pytest.approx(2 / 3)
    assert result.complete is False  # 0.667 < min_season_coverage 0.9
    assert result.details == {"n_days": 2}
    assert result.estimated is False
    assert result.classification is None


def test_params_and_their_validation(context: IndexContext) -> None:
    index = MeanAboveIndex(MeanAboveParams(base_temp_c=12.0))
    assert index.params.base_temp_c == 12.0
    assert index.compute(context).value == 3.0  # (15 - 12) + max(0, 11 - 12)
    with pytest.raises(TypeError, match="expects MeanAboveParams"):
        MeanAboveIndex(IndexParams())  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        MeanAboveParams(base_temp_c=1.0, unknown=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        index.params.base_temp_c = 5.0  # type: ignore[misc]


def test_relaxed_season_coverage_makes_result_complete(context: IndexContext) -> None:
    relaxed = IndexContext(
        sensor_id=context.sensor_id,
        year=context.year,
        daily=context.daily,
        series=context.series,
        latitude_deg=None,
        elevation_m=None,
        timezone=PRAGUE,
        min_daily_coverage=0.5,
        min_season_coverage=0.6,
        exclude_mask=int(QcFlag.DEFAULT_EXCLUDE),
    )
    result = MeanAboveIndex().compute(relaxed)
    assert result.coverage == 1.0
    assert result.complete is True
    assert result.value == 6.0 + 20.0  # Sep 2 now counts: mean 30 -> 20


def test_registry_register_create_and_lookup() -> None:
    registry = IndexRegistry()
    assert registry.register(MeanAboveIndex) is MeanAboveIndex
    assert "test_mean_above" in registry
    assert "huglin" not in registry
    assert registry.ids() == ("test_mean_above",)
    assert len(registry) == 1
    assert registry.get("test_mean_above") is MeanAboveIndex
    created = registry.create("test_mean_above", {"base_temp_c": 5.0})
    assert isinstance(created, MeanAboveIndex)
    assert created.params == MeanAboveParams(base_temp_c=5.0)
    assert registry.create("test_mean_above").params == MeanAboveParams()


def test_registry_string_decorator_form() -> None:
    registry = IndexRegistry()
    assert registry.register("test_mean_above")(MeanAboveIndex) is MeanAboveIndex
    with pytest.raises(ValueError, match="registered as 'other'"):
        IndexRegistry().register("other")(MeanAboveIndex)


def test_registry_rejections() -> None:
    registry = IndexRegistry()
    registry.register(MeanAboveIndex)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(MeanAboveIndex)
    with pytest.raises(KeyError, match="Unknown index 'huglin'; registered: test_mean_above"):
        registry.create("huglin")
    with pytest.raises(ValidationError):
        registry.create("test_mean_above", {"base_temp": 5.0})
    with pytest.raises(TypeError, match="abstract"):
        registry.register(ClimateIndex)
    with pytest.raises(TypeError, match="Only ClimateIndex subclasses"):
        registry.register(dict)  # type: ignore[type-var]

    class NoId(MeanAboveIndex):
        index_id = ""

    class NoUnit(MeanAboveIndex):
        index_id = "no_unit"
        unit = None  # type: ignore[assignment]

    with pytest.raises(TypeError, match="index_id"):
        registry.register(NoId)
    with pytest.raises(TypeError, match="'unit'"):
        registry.register(NoUnit)


def test_project_registry_exists_and_is_independent() -> None:
    assert isinstance(index_registry, IndexRegistry)
    assert "test_mean_above" not in index_registry


def test_index_result_validation_and_read_only_details(sensor_id: SensorId) -> None:
    def make(**kwargs: object) -> IndexResult:
        return IndexResult(
            index_id="x",
            sensor_id=sensor_id,
            year=2026,
            value=None,
            unit="-",
            complete=False,
            **kwargs,  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="coverage must be within"):
        make(coverage=1.5)
    result = make(coverage=0.0, details={"a": 1}, daily=pd.Series([1.0], index=[date(2026, 9, 1)]))
    with pytest.raises(TypeError):
        result.details["a"] = 2  # type: ignore[index]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sensor_id": SensorId("11111111")}, "carries daily data of 77678271"),
        ({"timezone": "UTC"}, "differs from the daily data"),
        ({"min_daily_coverage": 1.5}, "min_daily_coverage must be within 0-1"),
        ({"min_season_coverage": -0.1}, "min_season_coverage must be within 0-1"),
        ({"exclude_mask": 1024}, "unknown QC flag bits"),
        ({"exclude_mask": -1}, "unknown QC flag bits"),
        ({"exclude_mask": True}, "must be an int"),
        ({"latitude_deg": 200.0}, "within -90..90"),
        ({"latitude_deg": -90.5}, "within -90..90"),
    ],
)
def test_index_context_consistency(
    context: IndexContext, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        dataclasses.replace(context, **changes)  # type: ignore[arg-type]


def test_missing_params_model_is_rejected(context: IndexContext) -> None:
    class NoParams(ClimateIndex[IndexParams]):
        index_id = "no_params"
        unit = "-"

        def compute(self, ctx: IndexContext) -> IndexResult:
            raise NotImplementedError

    with pytest.raises(TypeError, match="must set the class variable 'params_model'"):
        IndexRegistry().register(NoParams)
    with pytest.raises(TypeError, match="must set the class variable 'params_model'"):
        NoParams()

    class WithoutParameters(NoParams):
        params_model = IndexParams

    assert IndexRegistry().register(WithoutParameters) is WithoutParameters
    assert WithoutParameters().params == IndexParams()
