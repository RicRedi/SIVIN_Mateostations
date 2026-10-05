"""Tests of the Gubler-Thomas powdery mildew model and index (synthetic data, hand-computed)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.analytics.base import IndexContext, index_registry
from sivin.analytics.disease import (
    DayAssessment,
    GublerThomasModel,
    GublerThomasParams,
    Phase,
    PowderyMildewDayAssessor,
    PowderyMildewGublerThomas,
    RiskClass,
    SamplingParams,
    SeasonWindow,
    fahrenheit_to_celsius,
)
from sivin.core.flags import QcFlag

HOURLY = SamplingParams(nominal_interval_s=3600.0, max_sample_duration_s=5400.0)
FAV, NOT, UNK = True, False, None
"""Day outcomes: favourable, not favourable, undetermined."""
ContextFactory = Callable[..., IndexContext]
JUNE = SeasonWindow(start_month=6, start_day=1, end_month=6, end_day=30)


def day_temps(base_c: float, *spans: tuple[range, float]) -> list[float]:
    """24 hourly temperatures: ``base_c`` except the given hour ranges."""
    temps = [base_c] * 24
    for hours, temp_c in spans:
        for hour in hours:
            temps[hour] = temp_c
    return temps


def assessment(day: int, favourable: bool | None, heat: bool = False) -> DayAssessment:
    return DayAssessment(date(2026, 6, day), favourable, heat, 0.0)


def test_fahrenheit_to_celsius() -> None:
    assert fahrenheit_to_celsius(32.0) == 0.0
    assert fahrenheit_to_celsius(95.0) == 35.0  # (95 - 32) / 1.8
    assert fahrenheit_to_celsius(70.0) == pytest.approx(21.1111, abs=1e-4)  # 38 / 1.8
    assert fahrenheit_to_celsius(85.0) == pytest.approx(29.4444, abs=1e-4)  # 53 / 1.8


def test_state_machine_onset_growth_decline_heat_and_bounds() -> None:
    model = GublerThomasModel(GublerThomasParams())
    sequence = [
        (FAV, False),  # 1 streak 1
        (FAV, False),  # 2 streak 2
        (NOT, False),  # 3 streak reset
        (FAV, False),  # 4 streak 1
        (UNK, False),  # 5 undetermined: streak held at 1
        (FAV, False),  # 6 streak 2
        (FAV, True),  # 7 streak 3 -> onset, 60 (heat ignored before/at onset)
        (FAV, False),  # 8 80
        (FAV, False),  # 9 100
        (FAV, False),  # 10 100 (upper bound)
        (NOT, False),  # 11 90
        (FAV, True),  # 12 90 + 20 - 10 = 100
        (NOT, True),  # 13 100 - 10 - 10 = 80
        (UNK, False),  # 14 80 held
        (UNK, True),  # 15 80 - 10 (observed heat) = 70
        *[(NOT, False)] * 8,  # 16-23 60, 50, 40, 30, 20, 10, 0, 0 (lower bound)
    ]
    days = [assessment(n + 1, fav, heat) for n, (fav, heat) in enumerate(sequence)]
    states = model.run(days)
    expected = [0, 0, 0, 0, 0, 0, 60, 80, 100, 100, 90, 100, 80, 80, 70]
    expected += [60, 50, 40, 30, 20, 10, 0, 0]
    assert [s.index_points for s in states] == expected
    assert [s.streak_days for s in states[:6]] == [1, 2, 0, 1, 1, 2]
    assert states[5].phase is Phase.WAITING_FOR_ONSET
    assert states[6].phase is Phase.ACTIVE
    assert all(s.onset_date == date(2026, 6, 7) for s in states[6:])
    assert states[-1].day == date(2026, 6, 23)


def test_long_outage_resets_the_onset_streak() -> None:
    # Reviewer example: Jun 1 favourable, Jun 2-12 without data, Jun 13-14 favourable.
    days = [assessment(1, FAV), *(assessment(d, UNK) for d in range(2, 13))]
    days += [assessment(13, FAV), assessment(14, FAV), assessment(15, FAV)]
    states = GublerThomasModel(GublerThomasParams()).run(days)
    # Jun 2 is carried (1 <= max 1), Jun 3 resets the streak; Jun 13-15 are 3 new days.
    assert states[0].streak_days == 1
    assert states[1].streak_days == 1
    assert states[2].streak_days == 0
    assert [s.streak_days for s in states[12:14]] == [1, 2]
    assert states[13].phase is Phase.WAITING_FOR_ONSET  # no onset on Jun 14
    assert states[14].onset_date == date(2026, 6, 15)
    assert states[14].index_points == 60
    longer = GublerThomasModel(GublerThomasParams(max_undetermined_carry_days=11)).run(days)
    assert longer[13].onset_date == date(2026, 6, 14)  # carried through 11 undetermined days


def test_classes_follow_uc_ipm_limits() -> None:
    model = GublerThomasModel(GublerThomasParams())
    assert [model.classify(p) for p in (0, 30, 40, 50, 60, 100)] == [
        RiskClass.LOW,
        RiskClass.LOW,
        RiskClass.MODERATE,
        RiskClass.MODERATE,
        RiskClass.HIGH,
        RiskClass.HIGH,
    ]


def test_parameter_validation() -> None:
    with pytest.raises(ValidationError, match="band_min_temp_c"):
        GublerThomasParams(band_min_temp_c=30.0, band_max_temp_c=20.0)
    with pytest.raises(ValidationError, match="moderate_from"):
        GublerThomasParams(moderate_from_points=70, high_from_points=60)
    with pytest.raises(ValidationError, match="onset_index_points"):
        GublerThomasParams(onset_index_points=120)
    with pytest.raises(ValidationError):
        GublerThomasParams(unknown=1)  # type: ignore[call-arg]


def test_index_on_hand_built_hourly_days(make_context: ContextFactory) -> None:
    warm = (range(10, 18), 25.0)  # 8 h in the band
    days = [
        day_temps(15.0, warm),  # Jun 1 F
        day_temps(15.0, warm),  # Jun 2 F
        day_temps(15.0, warm),  # Jun 3 F -> onset, 60
        day_temps(15.0, (range(8, 16), 25.0), (range(16, 17), 36.0)),  # Jun 4 F+heat -> 70
        day_temps(15.0, (range(10, 15), 25.0)),  # Jun 5 only 5 h -> 60
        [15.0] * 12,  # Jun 6 00-11 only, coverage 0.5, no run -> undetermined, 60
        [25.0] * 10,  # Jun 7 08-17 only, coverage 0.42 but a 10 h run -> F, 80
        day_temps(15.0, (range(13, 14), 36.0)),  # Jun 8 not F + heat -> 60
        day_temps(15.0, (range(10, 16), 21.2)),  # Jun 9 exactly 6 h at 21.2 >= 21.11 -> 80
        day_temps(15.0, (range(10, 18), 29.5)),  # Jun 10 29.5 > 29.44, outside band -> 70
    ]
    hours_of_day = [range(24)] * 5 + [range(12), range(8, 18)] + [range(24)] * 3
    times = [
        f"2026-06-{n + 1:02d} {hour:02d}:00"
        for n, hours in enumerate(hours_of_day)
        for hour in hours
    ]
    temps = [t for day in days for t in day]
    ctx = make_context(times, temps, [60.0] * len(temps))
    index = PowderyMildewGublerThomas(GublerThomasParams(sampling=HOURLY, season=JUNE))
    result = index.compute(ctx)
    assert result.daily is not None
    assert list(result.daily) == [0.0, 0.0, 60.0, 70.0, 60.0, 60.0, 80.0, 60.0, 80.0, 70.0]
    assert result.daily.index[0] == date(2026, 6, 1)
    assert result.value == 80.0
    assert result.classification == "high"  # season maximum 80 >= 60
    assert result.unit == "points"
    assert result.estimated is False
    # Complete days (coverage >= 0.9): Jun 1-5 and Jun 8-10 = 8 of the 30 days of June.
    assert result.coverage == pytest.approx(8 / 30)
    assert result.complete is False
    assert dict(result.details) == {
        "current_index_points": 70,
        "phase": "active",
        "n_days": 10,
        "n_favourable_days": 6,  # Jun 1, 2, 3, 4, 7, 9
        "n_unfavourable_days": 3,  # Jun 5, 8, 10
        "n_undetermined_days": 1,  # Jun 6
        "n_heat_days": 2,  # Jun 4, 8
        "longest_run_h_max": 10.0,  # Jun 7
        "onset_date": "2026-06-03",
        "current_class": "high",  # current index 70 >= 60
    }


def test_legacy_sampling_needs_twelve_samples_for_six_hours(make_context: ContextFactory) -> None:
    # 47 samples every 1825 s from 00:00 cover 47 * 1825 / 86400 = 0.993 of the day.
    local = [str(pd.Timestamp("2026-06-01") + pd.Timedelta(seconds=n * 1825)) for n in range(47)]
    params = GublerThomasParams()
    for n_warm, favourable, run_h in ((12, True, 12 * 1825 / 3600), (11, False, 11 * 1825 / 3600)):
        temps = [15.0] * 47
        temps[20 : 20 + n_warm] = [25.0] * n_warm
        ctx = make_context(local, temps, [60.0] * 47, expected_interval_s=1825.0)
        (day,) = PowderyMildewDayAssessor(params).assess(ctx, [date(2026, 6, 1)])
        # 12 x 1825 s = 6.083 h >= 6 h; 11 x 1825 s = 5.576 h < 6 h (day covered -> False).
        assert day.favourable is favourable
        assert day.longest_run_h == pytest.approx(run_h)
        assert day.heat is False


def test_excluded_sample_breaks_the_run(make_context: ContextFactory) -> None:
    temps = day_temps(15.0, (range(10, 18), 25.0))
    qc = [0] * 24
    qc[13] = int(QcFlag.SPIKE)
    times = [f"2026-06-01 {h:02d}:00" for h in range(24)]
    ctx = make_context(times, temps, [60.0] * 24, qc=qc, min_daily_coverage=0.9)
    params = GublerThomasParams(sampling=HOURLY)
    (day,) = PowderyMildewDayAssessor(params).assess(ctx, [date(2026, 6, 1)])
    # Runs 10-12 (3 h) and 14-17 (4 h); coverage 23/24 = 0.958 -> determined, not favourable.
    assert day.longest_run_h == 4.0
    assert day.favourable is False


def test_heat_shorter_than_the_minimum_does_not_count(make_context: ContextFactory) -> None:
    temps = day_temps(15.0, (range(12, 13), 36.0))
    times = [f"2026-06-01 {h:02d}:00" for h in range(24)]
    ctx = make_context(times, temps, [60.0] * 24)
    long_heat = GublerThomasParams(sampling=HOURLY, min_heat_duration_min=90.0)
    (day,) = PowderyMildewDayAssessor(long_heat).assess(ctx, [date(2026, 6, 1)])
    assert day.heat is False  # one sample = 60 min < 90 min
    (day,) = PowderyMildewDayAssessor(GublerThomasParams(sampling=HOURLY)).assess(
        ctx, [date(2026, 6, 1)]
    )
    assert day.heat is True  # 60 min >= 15 min


def test_empty_season_gives_no_value(make_context: ContextFactory) -> None:
    times = [f"2026-06-01 {h:02d}:00" for h in range(24)]
    ctx = make_context(times, [25.0] * 24, [60.0] * 24)
    august = SeasonWindow(start_month=8, start_day=1, end_month=8, end_day=31)
    result = PowderyMildewGublerThomas(GublerThomasParams(season=august)).compute(ctx)
    assert result.value is None
    assert result.daily is None
    assert result.coverage == 0.0
    assert result.complete is False
    assert result.classification is None
    assert dict(result.details) == {}


def test_complete_season_and_registry(make_context: ContextFactory) -> None:
    times = [f"2026-06-0{d} {h:02d}:00" for d in (1, 2) for h in range(24)]
    temps = day_temps(15.0, (range(10, 13), 25.0)) * 2  # 3 h only: not favourable
    ctx = make_context(times, temps, [60.0] * 48)
    two_days = SeasonWindow(start_month=6, start_day=1, end_month=6, end_day=2)
    index = index_registry.create(
        "powdery_mildew_gt", {"season": two_days.model_dump(), "sampling": HOURLY.model_dump()}
    )
    assert isinstance(index, PowderyMildewGublerThomas)
    result = index.compute(ctx)
    assert result.coverage == 1.0
    assert result.complete is True
    assert result.value == 0.0
    assert result.classification == "low"
    assert result.details["current_class"] == "low"
    assert result.details["phase"] == "waiting_for_onset"
    assert "onset_date" not in result.details
    assert result.daily is not None
    np.testing.assert_array_equal(result.daily.to_numpy(), [0.0, 0.0])
