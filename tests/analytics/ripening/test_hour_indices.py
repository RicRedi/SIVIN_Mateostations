"""Indices built on sample durations or humidity: heat_hours, frost, dew_point, vpd.

All data are synthetic, chosen so that the results can be computed by hand.
"""

from __future__ import annotations

import json
import math
from datetime import date

import numpy as np
import pytest
from pydantic import ValidationError

from sivin.analytics.base import index_registry
from sivin.analytics.ripening import (
    DewPointIndex,
    DewPointParams,
    FrostIndex,
    FrostParams,
    HeatHoursIndex,
    HeatHoursParams,
    VpdIndex,
    VpdParams,
)
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries

from .conftest import ContextFactory, DaySeriesFactory, local_stamps

NAN = float("nan")


class TestHeatHours:
    def test_hand_computed_bands(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # Jul 1, hourly: 10 h at 15, 4 h at 32, 2 h at 36, 1 h at exactly 30, 7 h at 25 °C.
        # Optimum 20 <= T <= 30: 1 + 7 = 8 h; heat stress T > 30: 4 + 2 = 6 h; T > 35: 2 h.
        # The trailing sample on Jul 2 00:00 lets 23:00 stand for a full hour.
        temps = [15.0] * 10 + [32.0] * 4 + [36.0] * 2 + [30.0] + [25.0] * 7
        series = hourly_days({date(2026, 7, 1): temps}, trailing_sample=True)
        result = HeatHoursIndex().compute(make_context(series, 2026))
        assert result.value == pytest.approx(6.0)
        assert result.unit == "h"
        assert result.details["optimum_h"] == pytest.approx(8.0)
        assert result.details["heat_stress_h"] == pytest.approx(6.0)
        assert result.details["extreme_heat_h"] == pytest.approx(2.0)
        assert result.details["observed_h"] == pytest.approx(24.0)
        assert result.coverage == pytest.approx(1 / 214)  # Apr 1 - Oct 31 = 214 days
        assert result.daily is not None
        assert result.daily.to_dict() == {date(2026, 7, 1): pytest.approx(6.0)}

    def test_threshold_order_validated(self) -> None:
        with pytest.raises(ValidationError, match="optimum_min_c"):
            HeatHoursParams(optimum_min_c=30.0, optimum_max_c=20.0)
        with pytest.raises(ValidationError, match="extreme_heat_c"):
            HeatHoursParams(heat_stress_c=35.0, extreme_heat_c=30.0)


class TestFrost:
    @pytest.fixture
    def series(self, hourly_days: DaySeriesFactory) -> MeasurementSeries:
        # Apr 10: 2 h at -3, 4 h at -1, 18 h at 4 °C -> frost (<= 0) 6 h, hard (<= -2) 2 h.
        # Apr 20: 2 h at 0.0 (frost hours count T <= 0), 22 h at 6 °C -> frost 2 h, min 0.0,
        # but no frost night (T_min < 0, as the ČHMÚ frost day). Apr 25: no frost, min 5.
        # Apr 10 23:00 is followed by a gap until Apr 20: it counts only 1825 s (4 °C).
        return hourly_days(
            {
                date(2026, 4, 10): [-3.0] * 2 + [-1.0] * 4 + [4.0] * 18,
                date(2026, 4, 20): [0.0] * 2 + [6.0] * 22,
                date(2026, 4, 25): [5.0] * 24,
            },
            trailing_sample=True,
        )

    def test_hand_computed_hours_nights_and_minimum(
        self, series: MeasurementSeries, make_context: ContextFactory
    ) -> None:
        result = FrostIndex().compute(make_context(series, 2026))
        assert result.value == pytest.approx(8.0)
        assert result.details["frost_h"] == pytest.approx(8.0)
        assert result.details["hard_frost_h"] == pytest.approx(2.0)
        assert result.details["frost_nights"] == 1
        assert result.details["min_temp_c"] == -3.0
        assert "after_date" not in result.details
        assert result.daily is not None
        assert result.daily.tolist() == pytest.approx([6.0, 2.0, 0.0])

    def test_critical_frost_after_budburst(
        self, series: MeasurementSeries, make_context: ContextFactory
    ) -> None:
        params = FrostParams(after_date=date(2026, 4, 15))
        result = FrostIndex(params).compute(make_context(series, 2026))
        assert result.value == pytest.approx(8.0)
        assert result.details["after_date"] == "2026-04-15"
        assert result.details["critical_frost_h"] == pytest.approx(2.0)
        assert result.details["critical_hard_frost_h"] == pytest.approx(0.0)
        assert result.details["critical_frost_nights"] == 0
        assert result.details["critical_min_temp_c"] == 0.0

    def test_after_date_must_lie_in_season_year(
        self, series: MeasurementSeries, make_context: ContextFactory
    ) -> None:
        params = FrostParams(after_date=date(2025, 4, 15))
        with pytest.raises(ValueError, match="season year 2026"):
            FrostIndex(params).compute(make_context(series, 2026))

    def test_critical_period_without_days(
        self, series: MeasurementSeries, make_context: ContextFactory
    ) -> None:
        params = FrostParams(after_date=date(2026, 10, 1))
        result = FrostIndex(params).compute(make_context(series, 2026))
        assert result.details["critical_frost_h"] == 0.0
        assert "critical_min_temp_c" not in result.details

    def test_returns_hours_not_rows(
        self, sensor_id: SensorId, make_context: ContextFactory
    ) -> None:
        # 48 half-hourly samples, 12 of them <= 0 °C: 12 rows (legacy count) but 6 hours.
        day = date(2026, 5, 3)
        hours = [h / 2 for h in range(48)]
        temps = [-1.0 if h < 6 else 3.0 for h in hours]
        series = MeasurementSeries.from_records(
            sensor_id, local_stamps(day, hours), temps, [80.0] * 48
        )
        result = FrostIndex().compute(make_context(series, 2026, expected_interval_s=1800.0))
        assert sum(t <= 0 for t in temps) == 12
        assert result.value == pytest.approx(6.0)

    def test_irregular_sampling_does_not_change_the_result(
        self, sensor_id: SensorId, make_context: ContextFactory
    ) -> None:
        # The same 3 h frost (01:00-04:00) on May 3, once every 30 min, once at irregular
        # steps (all shorter than the 4562.5 s cap). Both must give 3 h.
        day = date(2026, 5, 3)
        values = []
        for hours in (
            [h / 2 for h in range(49)],
            [
                0,
                0.4,
                1,
                1.2,
                2.05,
                2.6,
                3.5,
                3.99,
                4,
                5,
                5.9,
                7,
                8,
                9.5,
                10.2,
                11,
                12,
                13,
                14,
                15,
                16,
                17,
                18,
                19,
                20,
                21,
                22,
                23,
                24,
            ],
        ):
            temps = [-0.5 if 1 <= h < 4 else 2.0 for h in hours]
            series = MeasurementSeries.from_records(
                sensor_id, local_stamps(day, hours), temps, [80.0] * len(hours)
            )
            context = make_context(series, 2026, min_daily_coverage=0.0)
            values.append(FrostIndex().compute(context).details["frost_h"])
        assert values == pytest.approx([3.0, 3.0])

    def test_threshold_order_validated(self) -> None:
        with pytest.raises(ValidationError, match="hard_frost_c"):
            FrostParams(frost_c=-2.0, hard_frost_c=0.0)


class TestDewPoint:
    def test_hand_computed_means(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # Jun 1: 20 °C, 50 % all day -> Td = 9.2611 °C, depression 10.7389 °C.
        # Jun 2: 10 °C, 100 % all day -> Td = 10.0 °C, depression 0.
        # Mean of daily means: Td (9.2611 + 10) / 2 = 9.6306; depression 10.7389 / 2 = 5.3694.
        series = hourly_days(
            {date(2026, 6, 1): [20.0] * 24, date(2026, 6, 2): [10.0] * 24},
            rh={date(2026, 6, 1): [50.0] * 24, date(2026, 6, 2): [100.0] * 24},
        )
        result = DewPointIndex().compute(make_context(series, 2026))
        assert result.value == pytest.approx(9.6306, abs=1e-4)
        assert result.details["mean_depression_c"] == pytest.approx(5.3694, abs=1e-4)
        assert result.details["n_rh_non_positive"] == 0
        assert result.daily is not None
        assert result.daily.tolist() == pytest.approx([9.2611, 10.0], abs=1e-4)

    def test_non_positive_humidity_is_flagged_not_replaced(
        self,
        hourly_days: DaySeriesFactory,
        make_context: ContextFactory,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # One sample with RH = 0 % gets no dew point (legacy replaced it by 0.0001 %); the
        # remaining 23 samples (20 °C, 50 %) still give Td = 9.2611 °C.
        series = hourly_days(
            {date(2026, 6, 1): [20.0] * 24}, rh={date(2026, 6, 1): [0.0] + [50.0] * 23}
        )
        result = DewPointIndex().compute(make_context(series, 2026))
        assert result.details["n_rh_non_positive"] == 1
        assert result.value == pytest.approx(9.2611, abs=1e-4)
        assert "RH <= 0" in caplog.text

    def test_day_without_humidity_is_not_used(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # Jun 2 has complete temperature but no humidity at all: it must not count, and the
        # coverage drops to 1 of 214 days although two days have complete temperature.
        series = hourly_days(
            {date(2026, 6, 1): [20.0] * 24, date(2026, 6, 2): [10.0] * 24},
            rh={date(2026, 6, 1): [50.0] * 24, date(2026, 6, 2): [NAN] * 24},
        )
        result = DewPointIndex().compute(make_context(series, 2026))
        assert result.details["n_days"] == 1
        assert result.coverage == pytest.approx(1 / 214)
        assert result.value == pytest.approx(9.2611, abs=1e-4)

    def test_legacy_coefficients(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        series = hourly_days({date(2026, 6, 1): [20.0] * 24}, rh={date(2026, 6, 1): [50.0] * 24})
        params = DewPointParams(magnus_a=17.27, magnus_b_c=237.7)
        result = DewPointIndex(params).compute(make_context(series, 2026))
        assert result.value == pytest.approx(9.2543, abs=1e-4)

    def test_all_humidity_non_positive_gives_no_value(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        series = hourly_days({date(2026, 6, 1): [20.0] * 24}, rh={date(2026, 6, 1): [0.0] * 24})
        result = DewPointIndex().compute(make_context(series, 2026))
        assert result.value is None
        assert result.details["n_rh_non_positive"] == 24
        assert "mean_depression_c" not in result.details


class TestVpd:
    @pytest.fixture
    def series(self, hourly_days: DaySeriesFactory) -> MeasurementSeries:
        # Jun 1: 20 °C / 50 % (VPD 1.1691 kPa) except 12:00 and 13:00 at 30 °C / 20 %
        # (VPD 3.3945 kPa). Trailing sample so that 23:00 stands for a full hour.
        temps = [20.0] * 12 + [30.0] * 2 + [20.0] * 10
        rh = [50.0] * 12 + [20.0] * 2 + [50.0] * 10
        return hourly_days(
            {date(2026, 6, 1): temps}, rh={date(2026, 6, 1): rh}, trailing_sample=True
        )

    def test_hand_computed_daily_max_and_hours(
        self, series: MeasurementSeries, make_context: ContextFactory
    ) -> None:
        result = VpdIndex().compute(make_context(series, 2026))
        assert result.value == pytest.approx(3.3945, abs=1e-4)
        assert result.unit == "kPa"
        assert result.details["hours_above_threshold_h"] == pytest.approx(2.0)
        assert result.details["max_vpd_kpa"] == pytest.approx(3.3945, abs=1e-4)
        assert "mean_daytime_vpd_kpa" not in result.details

    def test_daytime_mean(self, series: MeasurementSeries, make_context: ContextFactory) -> None:
        # 10:00-18:00 = 8 samples: (6 * 1.1691 + 2 * 3.3945) / 8 = 1.7255 kPa.
        params = VpdParams(daytime_start_hour=10, daytime_end_hour=18)
        result = VpdIndex(params).compute(make_context(series, 2026))
        assert result.details["mean_daytime_vpd_kpa"] == pytest.approx(1.7255, abs=1e-4)

    def test_day_without_humidity_is_not_used(
        self, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        series = hourly_days(
            {date(2026, 6, 1): [20.0] * 24, date(2026, 6, 2): [35.0] * 24},
            rh={date(2026, 6, 1): [50.0] * 24, date(2026, 6, 2): [NAN] * 24},
        )
        result = VpdIndex().compute(make_context(series, 2026))
        assert result.details["n_days"] == 1
        assert result.value == pytest.approx(1.1691, abs=1e-4)

    def test_non_positive_humidity_is_invalid(
        self,
        hourly_days: DaySeriesFactory,
        make_context: ContextFactory,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Two samples at RH = 0 % (30 °C) would give VPD = e_s(30) = 4.24 kPa; they are
        # invalid, so the daily maximum is VPD(20 °C, 50 %) = 1.1691 kPa and no hour is above
        # the 2 kPa threshold.
        temps = [30.0] * 2 + [20.0] * 22
        rh = [0.0] * 2 + [50.0] * 22
        series = hourly_days({date(2026, 6, 1): temps}, rh={date(2026, 6, 1): rh})
        result = VpdIndex().compute(make_context(series, 2026))
        assert result.details["n_rh_non_positive"] == 2
        assert result.value == pytest.approx(1.1691, abs=1e-4)
        assert result.details["hours_above_threshold_h"] == 0.0
        assert "VPD" in caplog.text

    def test_daytime_mean_is_duration_weighted(
        self, sensor_id: SensorId, make_context: ContextFactory
    ) -> None:
        # Daytime 10-12 h: 10:00 at 20 °C / 50 % (1.1691 kPa) lasts 1 h; 11:00 and 11:30 at
        # 30 °C / 20 % (3.3945 kPa) last 1800 s each (11:30 -> 12:00). Weighted mean =
        # (1.1691*3600 + 3.3945*3600) / 7200 = 2.2818 kPa; the sample mean would be 2.6527.
        day = date(2026, 6, 1)
        hours = [h for h in range(24) if h != 11] + [11, 11.5]
        hours.sort()
        temps = [30.0 if 11 <= h < 12 else 20.0 for h in hours]
        rh = [20.0 if 11 <= h < 12 else 50.0 for h in hours]
        series = MeasurementSeries.from_records(sensor_id, local_stamps(day, hours), temps, rh)
        params = VpdParams(daytime_start_hour=10, daytime_end_hour=12)
        result = VpdIndex(params).compute(make_context(series, 2026))
        assert result.details["mean_daytime_vpd_kpa"] == pytest.approx(2.2818, abs=1e-4)

    @pytest.mark.parametrize(
        "values",
        [{"daytime_start_hour": 10}, {"daytime_start_hour": 18, "daytime_end_hour": 10}],
    )
    def test_daytime_window_validated(self, values: dict[str, int]) -> None:
        with pytest.raises(ValidationError, match="daytime"):
            VpdParams.model_validate(values)


@pytest.mark.parametrize(
    "index_id",
    [
        "cool_night",
        "dtr_ripening",
        "heat_hours",
        "tropical_days_nights",
        "frost",
        "winter_freeze",
        "dew_point",
        "vpd",
    ],
)
class TestEmptyAndOutOfSeason:
    def test_empty_series(
        self, index_id: str, sensor_id: SensorId, make_context: ContextFactory
    ) -> None:
        result = index_registry.create(index_id).compute(
            make_context(MeasurementSeries.empty(sensor_id), 2026)
        )
        assert result.value is None
        assert result.coverage == 0.0
        assert result.complete is False
        assert result.index_id == index_id

    def test_data_outside_the_period(
        self, index_id: str, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # Data from 2024 only: no index period of season 2026 contains them.
        series = hourly_days({date(2024, 7, 1): [20.0] * 24})
        result = index_registry.create(index_id).compute(make_context(series, 2026))
        assert result.value is None
        assert result.coverage == 0.0
        assert not np.isnan(result.coverage)

    def test_details_are_finite_json(
        self, index_id: str, hourly_days: DaySeriesFactory, make_context: ContextFactory
    ) -> None:
        # Pathological but valid input: humidity 0 % everywhere (no dew point, no VPD), a
        # winter without its autumn, frost on every day; no detail may be NaN or infinite.
        days = [date(2026, 1, 10), date(2026, 4, 10), date(2026, 8, 10), date(2026, 9, 10)]
        series = hourly_days(
            {day: [-25.0] * 6 + [35.0] * 18 for day in days},
            rh={day: [0.0] * 24 for day in days},
        )
        params = {"after_date": "2026-04-01"} if index_id == "frost" else {}
        result = index_registry.create(index_id, params).compute(make_context(series, 2026))
        for key, detail in result.details.items():
            assert isinstance(detail, str) or math.isfinite(detail), key
        assert result.value is None or math.isfinite(result.value)
        json.dumps(dict(result.details), allow_nan=False)
