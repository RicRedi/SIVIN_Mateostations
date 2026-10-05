"""Tests of the Broome Botrytis model with humidity-estimated wetness (synthetic, hand-computed)."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.analytics.base import IndexContext, index_registry
from sivin.analytics.disease import (
    BotrytisBroome,
    BotrytisBroomeParams,
    BroomeCoefficients,
    RiskBand,
    SamplingParams,
    SeasonWindow,
    WetnessPeriodDetector,
    logistic,
)
from sivin.core.flags import QcFlag

ContextFactory = Callable[..., IndexContext]
HOURLY = SamplingParams(nominal_interval_s=3600.0, max_sample_duration_s=5400.0)
NAN = math.nan

# Hand-computed with a = -2.647866, b = -0.374927, c = 0.061601, d = -0.001511:
# W = 3 h, T = 20 °C: -2.647866 - 1.124781 + 3.696060 - 1.813200 = -1.889787,
#   Y = 1 / (1 + e^1.889787) = 1 / (1 + 6.617959) = 0.1312688
# W = 5 h, T = 15 °C: -2.647866 - 1.874635 + 4.620075 - 1.699875 = -1.602301,
#   Y = 1 / (1 + e^1.602301) = 1 / (1 + 4.964442) = 0.1676603
Y_3H_20C = 0.1312688
Y_5H_15C = 0.1676603


def window(first_day: int, last_day: int) -> SeasonWindow:
    return SeasonWindow(start_month=6, start_day=first_day, end_month=6, end_day=last_day)


def two_nights() -> tuple[list[str], list[float], list[float]]:
    """Jun 1-2, hourly. Event 1: Jun 1 10-12 h, RH 92 %, 20 °C (3 h).

    Event 2: Jun 1 21 h - Jun 2 01 h, RH 95/95/85/95/95 % (the 85 % hour is bridged),
    temperatures 14/16/15/15/15 °C (5 h, mean 15 °C). All other hours RH 70 %, 18 °C.
    """
    times = [f"2026-06-0{d} {h:02d}:00" for d in (1, 2) for h in range(24)]
    temps = [18.0] * 48
    rh = [70.0] * 48
    for hour in (10, 11, 12):
        temps[hour], rh[hour] = 20.0, 92.0
    for hour, temp_c, rh_pct in zip(
        (21, 22, 23, 24, 25),
        (14.0, 16.0, 15.0, 15.0, 15.0),
        (95.0, 95.0, 85.0, 95.0, 95.0),
        strict=True,
    ):
        temps[hour], rh[hour] = temp_c, rh_pct
    return times, temps, rh


def test_logit_and_probability_hand_computed() -> None:
    coefficients = BroomeCoefficients()
    assert coefficients.logit(5.0, 15.0) == pytest.approx(-1.602301, abs=1e-9)
    assert coefficients.infection_probability(5.0, 15.0) == pytest.approx(Y_5H_15C, abs=1e-7)
    assert coefficients.infection_probability(3.0, 20.0) == pytest.approx(Y_3H_20C, abs=1e-7)
    # W = 12 h, T = 20 °C: -2.647866 - 4.499124 + 14.78424 - 7.2528 = 0.38445 -> Y = 0.5949459
    assert coefficients.infection_probability(12.0, 20.0) == pytest.approx(0.5949459, abs=1e-7)
    assert coefficients.logit(0.0, 25.0) == coefficients.intercept


def test_logistic_is_stable() -> None:
    assert logistic(0.0) == 0.5
    assert logistic(800.0) == 1.0
    assert logistic(-800.0) == 0.0
    assert logistic(-1.602301) == pytest.approx(Y_5H_15C, abs=1e-7)


def test_index_on_two_hand_built_nights(make_context: ContextFactory) -> None:
    times, temps, rh = two_nights()
    ctx = make_context(times, temps, rh)
    params = BotrytisBroomeParams(sampling=HOURLY, season=window(1, 2))
    result = BotrytisBroome(params).compute(ctx)
    assert result.estimated is True
    assert result.unit == "1"
    assert result.value == pytest.approx(Y_5H_15C, abs=1e-7)
    assert result.coverage == 1.0
    assert result.complete is True
    assert result.classification is None  # no risk bands configured
    assert result.daily is not None
    assert list(result.daily.index) == [date(2026, 6, 1), date(2026, 6, 2)]
    assert result.daily.to_list() == pytest.approx([Y_3H_20C, Y_5H_15C], abs=1e-7)
    details = dict(result.details)
    assert details["n_events"] == 2
    assert details["wetness_proxy"] == "rh_pct >= 90"
    assert details["event_001_start_utc"] == "2026-06-01T08:00:00+00:00"  # 10:00 CEST
    assert details["event_001_duration_h"] == 3.0
    assert details["event_001_mean_temp_c"] == 20.0
    assert details["event_002_start_utc"] == "2026-06-01T19:00:00+00:00"  # 21:00 CEST
    assert details["event_002_duration_h"] == 5.0
    assert details["event_002_mean_temp_c"] == 15.0
    assert details["event_002_infection_probability"] == pytest.approx(Y_5H_15C, abs=1e-7)


def test_events_carry_the_period(make_context: ContextFactory) -> None:
    times, temps, rh = two_nights()
    params = BotrytisBroomeParams(sampling=HOURLY, season=window(1, 2))
    events = BotrytisBroome(params).infection_events(make_context(times, temps, rh))
    second = events[1].period
    assert second.end_date == date(2026, 6, 2)
    assert second.interruption_h == 1.0
    assert second.end_utc == pd.Timestamp("2026-06-02T00:00:00", tz="UTC")  # 01:00 CEST + 1 h
    # A period counts on the day it ends: with the period Jun 1 only, event 2 is left out.
    jun_1 = BotrytisBroomeParams(sampling=HOURLY, season=window(1, 1))
    (only,) = BotrytisBroome(jun_1).infection_events(make_context(times, temps, rh))
    assert only.period.duration_h == 3.0


def test_missing_humidity_lowers_coverage_and_ends_events(make_context: ContextFactory) -> None:
    times, temps, rh = two_nights()
    # Jun 3: valid temperatures, humidity missing all day (synthetic RH channel failure).
    times += [f"2026-06-03 {h:02d}:00" for h in range(24)]
    temps += [18.0] * 24
    rh += [NAN] * 24
    ctx = make_context(times, temps, rh)
    assert ctx.daily.frame.loc[date(2026, 6, 3), "temp_coverage"] == 1.0  # temperature-only OK
    params = BotrytisBroomeParams(sampling=HOURLY, season=window(1, 3))
    result = BotrytisBroome(params).compute(ctx)
    # Jun 3 counts as not covered (rh_coverage 0): coverage 2/3, incomplete, daily NaN.
    assert result.coverage == pytest.approx(2 / 3)
    assert result.complete is False
    assert result.daily is not None
    assert math.isnan(result.daily[date(2026, 6, 3)])
    assert result.value == pytest.approx(Y_5H_15C, abs=1e-7)


def test_missing_or_excluded_humidity_inside_a_wet_spell_splits_it(
    make_context: ContextFactory,
) -> None:
    times = [f"2026-06-01 {h:02d}:00" for h in range(6)]
    params = BotrytisBroomeParams(sampling=HOURLY, max_dry_interruption_h=2.0)
    detector = WetnessPeriodDetector(params)
    mask = int(QcFlag.DEFAULT_EXCLUDE)
    missing = make_context(times, [15.0] * 6, [95.0, 95.0, NAN, 95.0, 95.0, 70.0])
    flagged = make_context(
        times, [15.0] * 6, [95.0] * 5 + [70.0], qc=[0, 0, int(QcFlag.SPIKE), 0, 0, 0]
    )
    for ctx in (missing, flagged):
        periods = detector.detect(ctx.series, mask, ctx.timezone)
        # A dry hour would be bridged (<= 2 h), an unknown hour is not: 2 h + 2 h.
        assert [p.duration_h for p in periods] == [2.0, 2.0]


def test_mean_temperature_is_weighted_by_sample_duration(make_context: ContextFactory) -> None:
    times = ["2026-06-01 00:00", "2026-06-01 00:30", "2026-06-01 02:00"]
    ctx = make_context(times, [10.0, 20.0, 30.0], [95.0] * 3, expected_interval_s=1800.0)
    params = BotrytisBroomeParams(
        sampling=SamplingParams(nominal_interval_s=1800.0, max_sample_duration_s=5400.0)
    )
    (period,) = WetnessPeriodDetector(params).detect(ctx.series, ctx.exclude_mask, ctx.timezone)
    # Durations 1800, 5400, 1800 s: W = 2.5 h, T = (10*1800 + 20*5400 + 30*1800) / 9000 = 20.
    assert period.duration_h == 2.5
    assert period.mean_temp_c == 20.0


def test_short_events_and_events_without_temperature_are_left_out(
    make_context: ContextFactory,
) -> None:
    times, temps, rh = two_nights()
    ctx = make_context(times, temps, rh)
    long_only = BotrytisBroomeParams(sampling=HOURLY, season=window(1, 2), min_event_duration_h=4)
    result = BotrytisBroome(long_only).compute(ctx)
    assert result.details["n_events"] == 1
    assert result.details["event_001_duration_h"] == 5.0
    for hour in (10, 11, 12):
        temps[hour] = NAN
    params = BotrytisBroomeParams(sampling=HOURLY, season=window(1, 2))
    without_temp = BotrytisBroome(params).compute(make_context(times, temps, rh))
    assert without_temp.details["n_events"] == 1
    assert without_temp.daily is not None
    # Jun 1 temperature coverage 21/24 = 0.875 < 0.9 and no scored event: NaN, not 0.
    assert math.isnan(without_temp.daily[date(2026, 6, 1)])


def test_risk_bands(make_context: ContextFactory) -> None:
    times, temps, rh = two_nights()
    bands = (
        RiskBand(label="low", min_probability=0.0),
        RiskBand(label="high", min_probability=0.15),
    )
    params = BotrytisBroomeParams(sampling=HOURLY, season=window(1, 2), risk_bands=bands)
    assert BotrytisBroome(params).compute(make_context(times, temps, rh)).classification == "high"
    dry = make_context(times, temps, [70.0] * 48)
    result = BotrytisBroome(params).compute(dry)
    assert result.value == 0.0
    assert result.classification == "low"
    with pytest.raises(ValidationError, match="start at probability 0"):
        BotrytisBroomeParams(risk_bands=(RiskBand(label="x", min_probability=0.1),))
    with pytest.raises(ValidationError, match="strictly ascending"):
        BotrytisBroomeParams(risk_bands=(bands[0], bands[0]))


def test_empty_season_and_registry(make_context: ContextFactory) -> None:
    times, temps, rh = two_nights()
    august = SeasonWindow(start_month=8, start_day=1, end_month=8, end_day=31)
    index = index_registry.create("botrytis_broome", {"season": august.model_dump()})
    assert isinstance(index, BotrytisBroome)
    result = index.compute(make_context(times, temps, rh))
    assert result.value is None
    assert result.daily is None
    assert result.coverage == 0.0
    assert result.complete is False
    assert result.estimated is True
