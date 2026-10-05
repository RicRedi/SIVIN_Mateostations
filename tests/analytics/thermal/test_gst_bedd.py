"""``gst`` and ``bedd``: hand-computed examples (synthetic data)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from pydantic import ValidationError

from sivin.analytics.base import IndexContext
from sivin.analytics.thermal import BeddIndex, BeddParams, GstIndex, GstParams
from sivin.analytics.thermal.base import NO_COMPLETE_DAYS
from sivin.core.daily import DailyWeather

DailyFactory = Callable[..., DailyWeather]
ContextFactory = Callable[..., IndexContext]
ConstantDays = Callable[[date, int, tuple[float, float, float]], dict[date, tuple[float, ...]]]

# Synthetic (tmin, tmean, tmax) in °C.
HAND_DAYS = {
    date(2026, 4, 1): (8.0, 13.0, 16.0),  # minmax mean 12, DTR 8
    date(2026, 4, 2): (4.0, 9.0, 12.0),  # minmax mean 8, DTR 8
    date(2026, 4, 3): (12.0, 18.0, 22.0),  # minmax mean 17, DTR 10
    date(2026, 4, 4): (20.0, 25.0, 30.0),  # incomplete (coverage 0.5)
    date(2026, 4, 5): (14.0, 22.0, 34.0),  # minmax mean 24, DTR 20
    date(2026, 4, 6): (10.0, 17.0, 26.0),  # minmax mean 18, DTR 16
}
HAND_COVERAGE = {date(2026, 4, 4): 0.5}


@pytest.fixture
def hand_context(make_daily: DailyFactory, make_context: ContextFactory) -> IndexContext:
    return make_context(make_daily(HAND_DAYS, HAND_COVERAGE))


def test_gst_hand_computed(hand_context: IndexContext) -> None:
    result = GstIndex().compute(hand_context)
    # (12 + 8 + 17 + 24 + 18) / 5 = 79 / 5 = 15.8 °C (Apr 4 incomplete)
    assert result.value == pytest.approx(15.8)
    assert result.unit == "°C"
    assert result.daily is not None
    assert result.daily.tolist() == [12.0, 8.0, 17.0, 24.0, 18.0]
    assert result.coverage == pytest.approx(5 / 214)
    assert result.classification is None


def test_gst_sample_mean(hand_context: IndexContext) -> None:
    result = GstIndex(GstParams(daily_mean="sample_mean")).compute(hand_context)
    assert result.value == pytest.approx((13 + 9 + 18 + 22 + 17) / 5)  # 15.8 as well by design
    assert result.daily is not None
    assert result.daily.tolist() == [13.0, 9.0, 18.0, 22.0, 17.0]


@pytest.mark.parametrize(
    ("mean_c", "label"),
    [
        (12.0, "too_cool"),
        (13.0, "too_cool"),
        (14.0, "cool"),
        (16.0, "intermediate"),
        (18.0, "warm"),
        (19.0, "warm"),
        (20.0, "hot"),
        (25.0, "too_hot"),
    ],
)
def test_gst_full_season_classes(
    mean_c: float,
    label: str,
    make_daily: DailyFactory,
    make_context: ContextFactory,
    constant_days: ConstantDays,
) -> None:
    days = constant_days(date(2026, 4, 1), 214, (mean_c - 5.0, mean_c, mean_c + 5.0))
    result = GstIndex().compute(make_context(make_daily(days)))
    assert result.value == pytest.approx(mean_c)
    assert result.complete is True
    assert result.classification == label


def test_gst_empty_season(make_daily: DailyFactory, make_context: ContextFactory) -> None:
    result = GstIndex().compute(make_context(make_daily({date(2026, 11, 1): (1, 3, 5)})))
    assert result.value is None
    assert result.details["status"] == NO_COMPLETE_DAYS


def test_bedd_hand_computed(hand_context: IndexContext) -> None:
    result = BeddIndex().compute(hand_context)
    # Apr 1: 2 + 0.25 * (8 - 10) = 1.5
    # Apr 2: 0 - 0.5 = -0.5 -> 0
    # Apr 3: 7 + 0 (DTR 10 is inside 10-13) = 7
    # Apr 5: 14 + 0.25 * (20 - 13) = 15.75 -> capped at 9
    # Apr 6: 8 + 0.25 * (16 - 13) = 8.75
    assert result.value == pytest.approx(26.25)
    assert result.daily is not None
    assert result.daily.tolist() == pytest.approx([1.5, 1.5, 8.5, 17.5, 26.25])
    assert result.classification is None
    assert result.details["n_days"] == 5


def test_bedd_without_dtr_adjustment_and_cap(hand_context: IndexContext) -> None:
    params = BeddParams(dtr_factor=0.0, cap_c_d=100.0)
    result = BeddIndex(params).compute(hand_context)
    assert result.value == pytest.approx(2 + 0 + 7 + 14 + 8)  # plain GDD = 31


def test_bedd_cap_before_adjustment(hand_context: IndexContext) -> None:
    result = BeddIndex(BeddParams(cap_order="before_adjustment")).compute(hand_context)
    # Apr 1: 2 - 0.5 = 1.5; Apr 2: max(0, -0.5) = 0; Apr 3: 7
    # Apr 5: min(9, 14) + 1.75 = 10.75; Apr 6: 8 + 0.75 = 8.75 -> 28.0
    assert result.value == pytest.approx(28.0)
    with pytest.raises(ValidationError):
        BeddParams.model_validate({"cap_order": "never"})


def test_bedd_empty_and_validation(make_daily: DailyFactory, make_context: ContextFactory) -> None:
    result = BeddIndex().compute(make_context(make_daily({date(2026, 3, 1): (1, 3, 5)})))
    assert result.value is None
    with pytest.raises(ValidationError, match="must not be below"):
        BeddParams(dtr_lower_c=14.0, dtr_upper_c=13.0)
    with pytest.raises(ValidationError):
        BeddParams(cap_c_d=0.0)
