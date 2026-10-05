"""Pure formulas of the thermal indices against hand-computed numbers (synthetic inputs)."""

from __future__ import annotations

import pandas as pd
import pytest

from sivin.analytics.thermal.formulas import (
    bedd_daily,
    bedd_daily_cap_before_adjustment,
    degree_days,
    dtr_adjustment,
    fahrenheit_to_celsius_degree_days,
    huglin_daily,
)


def test_degree_days_clips_at_zero() -> None:
    mean_c = pd.Series([5.0, 10.0, 12.5, 20.0])
    # max(0, 5-10)=0, max(0, 0)=0, 2.5, 10
    assert degree_days(mean_c, 10.0).tolist() == [0.0, 0.0, 2.5, 10.0]
    # base 0 °C (GFV/GSR): negative means do not subtract
    assert degree_days(pd.Series([-3.0, 4.0]), 0.0).tolist() == [0.0, 4.0]


def test_huglin_daily() -> None:
    mean_c = pd.Series([18.0, 8.0, 9.0])
    max_c = pd.Series([24.0, 11.0, 10.0])
    # day 1: ((18-10) + (24-10)) / 2 = 11 -> * 1.06 = 11.66
    # day 2: ((8-10) + (11-10)) / 2 = -0.5 -> 0
    # day 3: ((9-10) + (10-10)) / 2 = -0.5 -> 0
    assert huglin_daily(mean_c, max_c, 10.0, 1.06).tolist() == pytest.approx([11.66, 0.0, 0.0])


def test_dtr_adjustment_three_regimes() -> None:
    dtr_c = pd.Series([8.0, 10.0, 11.5, 13.0, 15.0])
    # below 10: 0.25 * (8 - 10) = -0.5; within 10-13: 0; above 13: 0.25 * (15 - 13) = 0.5
    assert dtr_adjustment(dtr_c, 10.0, 13.0, 0.25).tolist() == [-0.5, 0.0, 0.0, 0.0, 0.5]


def test_bedd_daily_cap_adjustment_and_floor() -> None:
    mean_c = pd.Series([15.0, 15.0, 25.0, 9.0, 10.5, 15.0])
    dtr_c = pd.Series([12.0, 17.0, 12.0, 6.0, 6.0, 12.0])
    result = bedd_daily(
        mean_c,
        dtr_c,
        base_temp_c=10.0,
        cap_c_d=9.0,
        day_length_coefficient=1.0,
        dtr_lower_c=10.0,
        dtr_upper_c=13.0,
        dtr_factor=0.25,
    )
    # 1: 5 + 0 = 5
    # 2: 5 + 0.25 * (17 - 13) = 6
    # 3: min(9, 15 + 0) = 9 (cap)
    # 4: max(0, 0 + 0.25 * (6 - 10)) = max(0, -1) = 0 (floor)
    # 5: 0.5 - 1 = -0.5 -> 0 (floor)
    # 6: 5 (same as 1, checks independence of rows)
    assert result.tolist() == [5.0, 6.0, 9.0, 0.0, 0.0, 5.0]


def test_bedd_daily_day_length_coefficient() -> None:
    result = bedd_daily(
        pd.Series([15.0]),
        pd.Series([12.0]),
        base_temp_c=10.0,
        cap_c_d=9.0,
        day_length_coefficient=1.04,
        dtr_lower_c=10.0,
        dtr_upper_c=13.0,
        dtr_factor=0.25,
    )
    assert result.tolist() == pytest.approx([5.2])  # 1.04 * 5


def test_fahrenheit_to_celsius_degree_days_winkler_bounds() -> None:
    # 2500 * 5/9 = 1388.888..., 3000 * 5/9 = 1666.666..., 3500 * 5/9 = 1944.444...,
    # 4000 * 5/9 = 2222.222...  (rounded: 1389, 1667, 1944, 2222 °C·d)
    converted = [fahrenheit_to_celsius_degree_days(v) for v in (2500.0, 3000.0, 3500.0, 4000.0)]
    assert [round(v) for v in converted] == [1389, 1667, 1944, 2222]
    assert converted[0] == pytest.approx(12500.0 / 9.0)


def test_bedd_daily_cap_before_adjustment() -> None:
    mean_c = pd.Series([25.0, 9.0, 15.0])
    dtr_c = pd.Series([20.0, 15.0, 6.0])
    result = bedd_daily_cap_before_adjustment(
        mean_c,
        dtr_c,
        base_temp_c=10.0,
        cap_c_d=9.0,
        day_length_coefficient=1.0,
        dtr_lower_c=10.0,
        dtr_upper_c=13.0,
        dtr_factor=0.25,
    )
    # 1: min(9, 15) + 0.25 * (20 - 13) = 9 + 1.75 = 10.75 (may exceed the cap)
    # 2: min(9, 0) + 0.25 * (15 - 13) = 0.5 (same as the cap-after form)
    # 3: 5 + 0.25 * (6 - 10) = 4
    assert result.tolist() == [10.75, 0.5, 4.0]
