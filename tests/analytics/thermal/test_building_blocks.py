"""Classification, daily mean definitions and thermal-time accumulation (synthetic data)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.analytics.thermal.base import ThermalParams
from sivin.analytics.thermal.classification import ClassBound, IntervalClassification
from sivin.analytics.thermal.daily_mean import (
    DailyMeanDefinition,
    DailyMeanRegistry,
    MinMaxMean,
    SampleMean,
    daily_mean_registry,
)
from sivin.analytics.thermal.thermal_time import ThermalTimeModel
from sivin.core.daily import DailyWeather


def _classes() -> IntervalClassification:
    return IntervalClassification(
        bounds=(ClassBound(label="low", upper=10.0), ClassBound(label="mid", upper=20.0)),
        top_label="high",
    )


def test_classification_bounds_are_inclusive_upper() -> None:
    classes = _classes()
    assert classes.classify(-5.0) == "low"
    assert classes.classify(10.0) == "low"
    assert classes.classify(10.000001) == "mid"
    assert classes.classify(20.0) == "mid"
    assert classes.classify(20.5) == "high"


@pytest.mark.parametrize(
    ("bounds", "top", "message"),
    [
        ((("a", 2.0), ("b", 1.0)), "c", "strictly increasing"),
        ((("a", 1.0), ("b", 1.0)), "c", "strictly increasing"),
        ((("a", 1.0), ("b", 2.0)), "a", "unique"),
    ],
)
def test_classification_validation(
    bounds: tuple[tuple[str, float], ...], top: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        IntervalClassification(
            bounds=tuple(ClassBound(label=label, upper=upper) for label, upper in bounds),
            top_label=top,
        )
    with pytest.raises(ValidationError):
        IntervalClassification(bounds=(), top_label="x")


def test_daily_mean_definitions(make_daily: Callable[..., DailyWeather]) -> None:
    days: DailyWeather = make_daily(
        {date(2026, 5, 1): (10.0, 13.0, 20.0), date(2026, 5, 2): (6.0, 9.5, 14.0)}
    )
    assert MinMaxMean().mean_temp_c(days).tolist() == [15.0, 10.0]  # (10+20)/2, (6+14)/2
    assert SampleMean().mean_temp_c(days).tolist() == [13.0, 9.5]
    assert list(MinMaxMean().mean_temp_c(days).index) == [date(2026, 5, 1), date(2026, 5, 2)]


def test_daily_mean_registry() -> None:
    assert daily_mean_registry.names() == ("minmax", "sample_mean")
    assert isinstance(daily_mean_registry.create("minmax"), MinMaxMean)
    assert "sample_mean" in daily_mean_registry
    with pytest.raises(KeyError, match="known: minmax, sample_mean"):
        daily_mean_registry.create("median")

    registry = DailyMeanRegistry()
    assert registry.register(SampleMean) is SampleMean
    with pytest.raises(ValueError, match="already registered"):
        registry.register(SampleMean)


def test_new_daily_mean_definition_is_a_registered_class(
    make_daily: Callable[..., DailyWeather],
) -> None:
    registry = DailyMeanRegistry()

    @registry.register
    class MaxOnly(DailyMeanDefinition):
        name = "max_only"

        def mean_temp_c(self, days: DailyWeather) -> pd.Series:
            return days.frame["temp_max"]

    days = make_daily({date(2026, 5, 1): (10.0, 13.0, 20.0)})
    assert registry.create("max_only").mean_temp_c(days).tolist() == [20.0]


def test_thermal_params_reject_unknown_daily_mean() -> None:
    assert ThermalParams().daily_mean == "minmax"
    assert ThermalParams(daily_mean="sample_mean").daily_mean == "sample_mean"
    with pytest.raises(ValidationError, match="Unknown daily mean definition 'median'"):
        ThermalParams(daily_mean="median")


def test_thermal_time_accumulation_and_threshold() -> None:
    days = [date(2026, 3, d) for d in (1, 2, 4, 5)]  # March 3 missing (incomplete day)
    mean_c = pd.Series([2.0, -1.0, 5.0, float("nan")], index=days)
    curve = ThermalTimeModel(base_temp_c=0.0).accumulate(mean_c)
    # 2, 2 + 0, 2 + 0 + 5; the NaN day is dropped
    assert curve.cumulative_c_d.tolist() == [2.0, 2.0, 7.0]
    assert list(curve.cumulative_c_d.index) == days[:3]
    assert curve.total_c_d == 7.0
    assert curve.date_reached(2.0) == date(2026, 3, 1)  # reaching counts (>=)
    assert curve.date_reached(6.5) == date(2026, 3, 4)
    assert curve.date_reached(7.5) is None


def test_thermal_time_empty() -> None:
    curve = ThermalTimeModel(base_temp_c=5.0).accumulate(pd.Series([], dtype=float))
    assert curve.total_c_d == 0.0
    assert curve.date_reached(1.0) is None
