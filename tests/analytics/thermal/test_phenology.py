"""``budburst``, ``gfv`` and ``gsr``: hand-computed stage dates (synthetic data).

The critical sums used here (except the GFV defaults) are synthetic test values, not
literature values.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from pydantic import ValidationError

from sivin.analytics.base import IndexContext
from sivin.analytics.thermal import (
    BudburstIndex,
    BudburstParams,
    GfvIndex,
    GfvParams,
    GsrIndex,
    GsrParams,
    PhenologyStage,
)
from sivin.analytics.thermal.base import NO_COMPLETE_DAYS
from sivin.analytics.thermal.phenology import NOT_CONFIGURED, NOT_REACHED
from sivin.core.daily import DailyWeather

DailyFactory = Callable[..., DailyWeather]
ContextFactory = Callable[..., IndexContext]
ConstantDays = Callable[[date, int, tuple[float, float, float]], dict[date, tuple[float, ...]]]

MARCH_TO_OCTOBER_DAYS = 245  # March 1 - October 31


def test_gfv_both_stages_reached(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 3, 1), MARCH_TO_OCTOBER_DAYS, (6.0, 11.0, 18.0))
    result = GfvIndex().compute(make_context(make_daily(days)))
    # minmax mean 12 °C, base 0 -> 12 °C·d per day from March 1.
    # flowering F* 1282: 1282 / 12 = 106.8 -> day 107 (sum 1284) = June 15 = DOY 166
    # véraison F* 2528: 2528 / 12 = 210.7 -> day 211 (sum 2532) = September 27 = DOY 270
    assert result.value == 270.0
    assert result.unit == "DOY"
    assert result.details["flowering_date"] == "2026-06-15"
    assert result.details["flowering_doy"] == 166
    assert result.details["veraison_date"] == "2026-09-27"
    assert result.details["veraison_doy"] == 270
    assert result.details["flowering_f_star_c_d"] == 1282.0
    assert result.details["thermal_sum_c_d"] == 245 * 12.0
    assert result.daily is not None
    assert float(result.daily.iloc[0]) == 12.0
    # coverage until véraison: 211 complete days of 211
    assert result.coverage == 1.0
    assert result.complete is True
    assert result.estimated is False


def test_gfv_veraison_not_reached(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 3, 1), MARCH_TO_OCTOBER_DAYS, (5.0, 10.0, 15.0))
    result = GfvIndex().compute(make_context(make_daily(days)))
    # 10 °C·d per day: flowering on day 129 (sum 1290) = July 7 = DOY 188;
    # véraison would need 253 days > 245 days of the period.
    assert result.value is None
    assert result.details["flowering_date"] == "2026-07-07"
    assert result.details["flowering_doy"] == 188
    assert result.details["veraison_date"] == NOT_REACHED
    assert "veraison_doy" not in result.details
    assert result.details["status"] == "veraison not reached"
    assert result.coverage == 1.0  # whole period March 1 - October 31


def test_gfv_running_season_is_incomplete(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 3, 1), 122, (6.0, 11.0, 18.0))  # March 1 - June 30
    result = GfvIndex().compute(make_context(make_daily(days)))
    assert result.details["flowering_date"] == "2026-06-15"
    assert result.value is None
    assert result.coverage == pytest.approx(122 / 245)
    assert result.complete is False


def test_gfv_empty_season(make_daily: DailyFactory, make_context: ContextFactory) -> None:
    result = GfvIndex().compute(make_context(make_daily({date(2026, 2, 1): (1, 2, 3)})))
    assert result.value is None
    assert result.details["status"] == NO_COMPLETE_DAYS


def test_gfv_params_validation() -> None:
    with pytest.raises(ValidationError, match="must increase"):
        GfvParams(flowering_f_star_c_d=2600.0)
    with pytest.raises(ValidationError):
        GfvParams(veraison_f_star_c_d=-1.0)


def test_budburst_not_configured_by_default(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 1, 1), 10, (4.0, 8.0, 14.0))
    result = BudburstIndex().compute(make_context(make_daily(days)))
    assert result.value is None
    assert result.details["status"] == NOT_CONFIGURED
    assert result.estimated is True


def test_budburst_configured(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 1, 1), 10, (4.0, 8.0, 14.0))
    params = BudburstParams(f_star_c_d=20.0)  # synthetic F*
    result = BudburstIndex(params).compute(make_context(make_daily(days)))
    # minmax mean 9, base 5 -> 4 °C·d per day: 20 reached on day 5 = January 5 (DOY 5)
    assert result.value == 5.0
    assert result.details["budburst_date"] == "2026-01-05"
    assert result.details["thermal_sum_c_d"] == 40.0
    assert result.coverage == 1.0  # January 1-5, all complete
    assert result.complete is True
    assert result.estimated is True


def test_budburst_with_incomplete_day(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 1, 1), 10, (4.0, 8.0, 14.0))
    ctx = make_context(make_daily(days, {date(2026, 1, 3): 0.5}))
    result = BudburstIndex(BudburstParams(f_star_c_d=20.0)).compute(ctx)
    # January 3 is skipped: sums 4, 8, (skip), 12, 16, 20 -> January 6 (DOY 6)
    assert result.value == 6.0
    assert result.coverage == pytest.approx(5 / 6)
    assert result.complete is False  # 0.833 < 0.9


def test_gsr_not_configured(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 4, 1), 30, (6.0, 11.0, 18.0))
    result = GsrIndex().compute(make_context(make_daily(days)))
    assert result.value is None
    assert result.details["status"] == NOT_CONFIGURED
    assert result.details["n_days"] == 30


def test_gsr_configured_targets(
    make_daily: DailyFactory, make_context: ContextFactory, constant_days: ConstantDays
) -> None:
    days = constant_days(date(2026, 3, 25), 37, (6.0, 11.0, 18.0))  # March 25 - April 30
    targets = (
        PhenologyStage(label="sugar_low", f_star_c_d=120.0),  # synthetic F*
        PhenologyStage(label="sugar_high", f_star_c_d=240.0),  # synthetic F*
    )
    result = GsrIndex(GsrParams(targets=targets)).compute(make_context(make_daily(days)))
    # accumulation starts April 1 (March days ignored); 12 °C·d per day:
    # 120 on day 10 = April 10 (DOY 100), 240 on day 20 = April 20 (DOY 110)
    assert result.details["sugar_low_date"] == "2026-04-10"
    assert result.details["sugar_low_doy"] == 100
    assert result.value == 110.0
    assert result.details["thermal_sum_c_d"] == 30 * 12.0


def test_gsr_params_validation() -> None:
    low = PhenologyStage(label="a", f_star_c_d=100.0)
    with pytest.raises(ValidationError, match="must increase"):
        GsrParams(targets=(PhenologyStage(label="b", f_star_c_d=200.0), low))
    with pytest.raises(ValidationError, match="unique"):
        GsrParams(targets=(low, PhenologyStage(label="a", f_star_c_d=200.0)))
    with pytest.raises(ValidationError):
        PhenologyStage(label="Sugar 200 g/L", f_star_c_d=100.0)
