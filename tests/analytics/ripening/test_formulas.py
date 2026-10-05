"""Pure formulas, thresholds and parameter models of the ripening package."""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from sivin.analytics.base import index_registry
from sivin.analytics.ripening import (
    ALDUCHOV_ESKRIDGE_1996,
    LEGACY_MAGNUS,
    CoolNightParams,
    MagnusCoefficients,
    SampleDurationParams,
    dew_point_c,
    saturation_vapour_pressure_kpa,
    vapour_pressure_deficit_kpa,
)
from sivin.analytics.ripening.psychrometry import non_positive_humidity
from sivin.analytics.ripening.thresholds import Comparison, Threshold, UpperBoundClasses
from sivin.core.season import MonthDay

RIPENING_IDS = (
    "cool_night",
    "dtr_ripening",
    "heat_hours",
    "tropical_days_nights",
    "frost",
    "winter_freeze",
    "dew_point",
    "vpd",
)


class TestDewPoint:
    def test_alduchov_eskridge_at_20c_50pct(self) -> None:
        # gamma = ln(0.5) + 17.625*20/(243.04+20) = -0.693147 + 1.340100 = 0.646953
        # Td = 243.04*0.646953 / (17.625-0.646953) = 157.2355 / 16.978047 = 9.2611 °C
        assert dew_point_c(20.0, 50.0) == pytest.approx(9.2611, abs=1e-4)

    def test_legacy_coefficients_at_20c_50pct(self) -> None:
        # gamma = -0.693147 + 17.27*20/257.7 = -0.693147 + 1.340318 = 0.647171
        # Td = 237.7*0.647171 / (17.27-0.647171) = 153.8326 / 16.622829 = 9.2543 °C
        assert dew_point_c(20.0, 50.0, LEGACY_MAGNUS) == pytest.approx(9.2543, abs=1e-4)

    @pytest.mark.parametrize("temp_c", [-10.0, 0.0, 15.0, 35.0])
    def test_saturated_air_has_dew_point_equal_to_temperature(self, temp_c: float) -> None:
        # RH = 100 %: gamma = a*T/(b+T), so Td = b*gamma/(a-gamma) = T exactly.
        assert dew_point_c(temp_c, 100.0) == pytest.approx(temp_c, abs=1e-9)

    def test_non_positive_and_missing_humidity_give_nan(self) -> None:
        result = dew_point_c([20.0, 20.0, 20.0, np.nan], [0.0, -5.0, np.nan, 50.0])
        assert np.isnan(result).all()

    def test_non_positive_humidity_flags(self) -> None:
        flags = non_positive_humidity([0.0, -1.0, 0.1, np.nan])
        assert flags.tolist() == [True, True, False, False]

    def test_coefficients_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            MagnusCoefficients(a=-1.0, b_c=243.04)
        assert (ALDUCHOV_ESKRIDGE_1996.a, ALDUCHOV_ESKRIDGE_1996.b_c) == (17.625, 243.04)


class TestVapourPressure:
    def test_saturation_vapour_pressure(self) -> None:
        # FAO-56 eq. 11: e_s(0) = 0.6108 kPa; e_s(20) = 0.6108*exp(17.27*20/257.3)
        # = 0.6108*exp(1.342402) = 0.6108*3.828228 = 2.3383 kPa (FAO-56 Annex 2: 2.338)
        assert saturation_vapour_pressure_kpa(0.0) == pytest.approx(0.6108)
        assert saturation_vapour_pressure_kpa(20.0) == pytest.approx(2.3383, abs=1e-4)

    def test_vpd(self) -> None:
        # VPD(20 °C, 50 %) = 2.3383*(1-0.5) = 1.1691 kPa
        # VPD(30 °C, 20 %) = 0.6108*exp(17.27*30/267.3)*(1-0.2) = 4.2431*0.8 = 3.3945 kPa
        result = vapour_pressure_deficit_kpa([20.0, 30.0, 20.0], [50.0, 20.0, 100.0])
        assert result == pytest.approx([1.1691, 3.3945, 0.0], abs=1e-4)

    def test_impossible_humidity_gives_nan(self) -> None:
        assert math.isnan(float(vapour_pressure_deficit_kpa(20.0, -1.0)))
        assert float(vapour_pressure_deficit_kpa(20.0, 0.0)) == pytest.approx(2.3383, abs=1e-4)


class TestThresholds:
    def test_comparisons(self) -> None:
        values = [-1.0, 0.0, 1.0, np.nan]
        assert Comparison.LT.holds(values, 0.0).tolist() == [True, False, False, False]
        assert Comparison.LE.holds(values, 0.0).tolist() == [True, True, False, False]
        assert Comparison.GT.holds(values, 0.0).tolist() == [False, False, True, False]
        assert Comparison.GE.holds(values, 0.0).tolist() == [False, True, True, False]

    def test_threshold_str(self) -> None:
        assert str(Threshold(Comparison.GE, 30.0)) == ">= 30"

    @pytest.mark.parametrize(
        ("value", "label"),
        [(11.0, "low"), (12.0, "low"), (12.01, "mid"), (14.0, "mid"), (14.5, "high")],
    )
    def test_upper_bound_classes(self, value: float, label: str) -> None:
        classes = UpperBoundClasses(bounds=((12.0, "low"), (14.0, "mid")), top_label="high")
        assert classes.classify(value) == label

    @pytest.mark.parametrize("bounds", [(), ((14.0, "a"), (12.0, "b")), ((1.0, "a"), (1.0, "b"))])
    def test_invalid_bounds(self, bounds: tuple[tuple[float, str], ...]) -> None:
        with pytest.raises(ValueError, match="increasing"):
            UpperBoundClasses(bounds=bounds, top_label="x")


class TestParams:
    def test_month_day_from_string_and_back(self) -> None:
        params = CoolNightParams.model_validate({"period_start": "09-05", "period_end": "9-20"})
        assert params.period_start == MonthDay(9, 5)
        assert params.period_end == MonthDay(9, 20)
        assert params.model_dump()["period_start"] == "09-05"

    def test_month_day_from_mapping(self) -> None:
        params = CoolNightParams.model_validate({"period_start": {"month": 9, "day": 2}})
        assert params.period_start == MonthDay(9, 2)

    @pytest.mark.parametrize("text", ["09/01", "Sept-1", "13-01", "02-30"])
    def test_invalid_month_day(self, text: str) -> None:
        with pytest.raises(ValidationError):
            CoolNightParams.model_validate({"period_start": text})

    def test_period_must_not_cross_new_year(self) -> None:
        with pytest.raises(ValidationError, match="crosses New Year"):
            CoolNightParams.model_validate({"period_start": "10-01", "period_end": "03-01"})

    def test_unknown_keys_rejected_and_frozen(self) -> None:
        with pytest.raises(ValidationError):
            CoolNightParams.model_validate({"period_begin": "09-01"})
        params = CoolNightParams()
        with pytest.raises(ValidationError):
            params.period_start = MonthDay(9, 2)  # type: ignore[misc]

    def test_sample_duration_bounds(self) -> None:
        assert SampleDurationParams().max_sample_duration_s == 3650.0
        with pytest.raises(ValidationError):
            SampleDurationParams(max_sample_duration_s=7 * 3600.0)
        with pytest.raises(ValidationError):
            SampleDurationParams(last_sample_duration_s=0.0)


class TestRegistry:
    def test_all_ripening_indices_are_registered(self) -> None:
        for index_id in RIPENING_IDS:
            assert index_id in index_registry
            assert index_registry.get(index_id).index_id == index_id

    def test_create_from_configuration_mapping(self) -> None:
        frost = index_registry.create(
            "frost",
            {
                "after_date": "2026-04-20",
                "hard_frost_c": -2.5,
                "sampling": {"max_sample_duration_s": 3600},
            },
        )
        assert frost.params.after_date.isoformat() == "2026-04-20"
        assert frost.params.sampling.max_sample_duration_s == 3600.0
