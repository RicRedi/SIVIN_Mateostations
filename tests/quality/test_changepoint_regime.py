"""Tests of the change-point math and the regime rules. SYNTHETIC data only."""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from sivin.quality.boundaries import BoundaryRefiner, TransportSettings, TransportTrimmer
from sivin.quality.changepoint import BinarySegmentation, ChangePoint, GaussianSegmentCost
from sivin.quality.contrast import ContrastSettings, TransitionContrast
from sivin.quality.events import EventKind
from sivin.quality.regime import (
    IndoorAssessment,
    Regime,
    RegimeClassifier,
    RegimeSettings,
    WindowFeatures,
)
from sivin.quality.segmentation import Boundary, IndoorRun
from sivin.quality.windows import WindowedChangePoints


def _cost(values: list[float], floor: float = 1.0) -> GaussianSegmentCost:
    return GaussianSegmentCost(np.array(values)[:, None], np.array([floor]))


class TestGaussianSegmentCost:
    def test_hand_computed_cost_and_gain(self) -> None:
        cost = _cost([0.0, 0.0, 2.0, 2.0])
        # Whole segment: mean 1, ML variance 1, cost 4 * ln(1 + floor 1) = 4 ln 2.
        assert cost.cost(0, 4) == pytest.approx(4 * math.log(2))
        # Halves are constant: cost 2 * ln(0 + 1) = 0 each.
        assert cost.cost(0, 2) == pytest.approx(0.0)
        # Split at 1: [0] costs 0; [0, 2, 2] has mean 4/3 and variance 8/9.
        gains = cost.split_gains(0, 4, np.array([1, 2]))
        assert gains[0] == pytest.approx(4 * math.log(2) - 3 * math.log(8 / 9 + 1))
        assert gains[1] == pytest.approx(4 * math.log(2))
        assert len(cost) == 4
        assert cost.n_parameters == 2

    def test_two_variables_add_up(self) -> None:
        data = np.array([[0.0, 0.0], [0.0, 0.0], [2.0, 4.0], [2.0, 4.0]])
        cost = GaussianSegmentCost(data, np.array([1.0, 1.0]))
        # Variances 1 and 4: 4 ln 2 + 4 ln 5.
        assert cost.cost(0, 4) == pytest.approx(4 * math.log(2) + 4 * math.log(5))
        assert cost.n_parameters == 4

    @pytest.mark.parametrize(
        ("data", "floor", "message"),
        [
            (np.zeros(3), np.array([1.0]), "Shapes"),
            (np.array([[np.nan]]), np.array([1.0]), "NaN"),
            (np.zeros((3, 1)), np.array([0.0]), "positive"),
        ],
    )
    def test_invalid_input(self, data: np.ndarray, floor: np.ndarray, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            GaussianSegmentCost(data, floor)


class TestBinarySegmentation:
    EDGES = np.arange(41, dtype=np.float64)  # 1 s per sample

    def test_finds_a_level_change(self) -> None:
        cost = _cost([0.0] * 20 + [5.0] * 20, floor=0.01)
        found = BinarySegmentation(1.0, 3.0, 5).fit(cost, self.EDGES)
        assert [c.position for c in found] == [20]
        assert found[0].gain > 0

    def test_finds_a_variance_change(self) -> None:
        rng = np.random.default_rng(7)
        values = np.concatenate([rng.normal(0, 0.1, 200), rng.normal(0, 3.0, 200)])
        cost = _cost(values.tolist(), floor=0.0001)
        found = BinarySegmentation(1.0, 10.0, 1).fit(cost, np.arange(401, dtype=np.float64))
        assert abs(found[0].position - 200) <= 2

    def test_minimum_segment_duration(self) -> None:
        cost = _cost([0.0] * 2 + [5.0] * 38, floor=0.01)
        # The true change at 2 is closer than 5 s to the start; no change point may be there.
        found = BinarySegmentation(1.0, 5.0, 5).fit(cost, self.EDGES)
        assert all(c.position >= 5 for c in found)

    def test_penalty_and_cap(self) -> None:
        cost = _cost([0.0] * 10 + [5.0] * 10 + [0.5] * 20, floor=0.01)
        both = BinarySegmentation(1.0, 3.0, 5).fit(cost, self.EDGES)
        assert [c.position for c in both] == [10, 20]
        capped = BinarySegmentation(1.0, 3.0, 1).fit(cost, self.EDGES)
        assert len(capped) == 1
        assert BinarySegmentation(1e6, 3.0, 5).fit(cost, self.EDGES) == ()

    def test_penalty_formula(self) -> None:
        cost = _cost([0.0] * 40)
        # c (p + 1) ln n with p = 2 parameters and n = 40.
        assert BinarySegmentation(2.0, 1.0, 1).penalty(cost) == pytest.approx(6 * math.log(40))

    def test_too_few_samples(self) -> None:
        assert BinarySegmentation(1.0, 0.0, 5).fit(_cost([0.0, 9.0]), self.EDGES[:3]) == ()

    def test_change_points_sort_by_position(self) -> None:
        assert sorted([ChangePoint(5, 1.0), ChangePoint(2, 9.0)])[0].position == 2


def _features(
    temp_c: float, spread_c: float, rh_pct: float | None, rh_spread_pct: float | None
) -> WindowFeatures:
    return WindowFeatures(temp_c, spread_c, rh_pct, rh_spread_pct, 96)


def _assess(*args: float | None) -> IndoorAssessment:
    return RegimeClassifier().assess_features(_features(*args))  # type: ignore[arg-type]


class TestRegimeClassifier:
    def test_office_is_indoor_like(self) -> None:
        assessment = _assess(22.0, 2.0, 40.0, 5.0)
        assert assessment.indoor_like
        assert assessment.regime is Regime.INDOOR
        assert set(assessment.criteria) == {
            "room_temperature",
            "small_daily_spread",
            "moderate_humidity",
            "steady_humidity",
        }

    def test_outdoor_situations_are_not_indoor_like(self) -> None:
        # Overcast winter: too cold for a room and too humid.
        winter = _assess(-1.0, 2.0, 90.0, 6.0)
        assert not winter.criteria["room_temperature"]
        assert not winter.criteria["moderate_humidity"]
        # Cloudy summer day: room-like temperature and spread, but humidity follows the day.
        cloudy = _assess(20.0, 3.8, 72.0, 13.0)
        assert dict(cloudy.criteria) == {
            "room_temperature": True,
            "small_daily_spread": True,
            "moderate_humidity": True,
            "steady_humidity": False,
        }
        # Fog: saturated.
        assert not _assess(2.0, 1.0, 99.0, 2.0).indoor_like
        assert _assess(2.0, 1.0, 99.0, 2.0).regime is Regime.OUTDOOR

    def test_temperature_only(self) -> None:
        assessment = _assess(12.0, 1.0, None, None)
        assert set(assessment.criteria) == {"room_temperature", "small_daily_spread"}
        assert assessment.indoor_like

    def test_daily_spread_is_median_of_window_spreads(self) -> None:
        t_s = np.arange(96, dtype=np.float64) * 1800.0  # two days of 48 samples
        temp = np.concatenate([np.arange(48) * 0.1, np.full(48, 1.0)])
        features = RegimeClassifier().features(t_s, temp, temp * 10)
        # Day 1: P95 - P5 of 0.0..4.7 = 4.465 - 0.235 = 4.23; day 2: 0. Median = 2.115.
        assert features.daily_spread_c == pytest.approx(2.115)
        assert features.rh_daily_spread_pct == pytest.approx(21.15)
        assert features.n_samples == 96

    def test_short_stretch_uses_all_samples(self) -> None:
        t_s = np.arange(5, dtype=np.float64) * 1800.0
        features = RegimeClassifier().features(t_s, np.array([0.0, 1.0, 2.0, 3.0, 4.0]), None)
        # P95 - P5 of 0..4 = 3.8 - 0.2 = 3.6.
        assert features.daily_spread_c == pytest.approx(3.6)
        assert features.rh_median_pct is None

    def test_settings_validation(self) -> None:
        with pytest.raises(ValidationError, match="room_min_c"):
            RegimeSettings(room_min_c=30.0, room_max_c=20.0)
        classifier = RegimeClassifier(RegimeSettings(room_max_c=40.0))
        assert classifier.settings.room_max_c == 40.0


class TestTransitionContrast:
    OFFICE = (22.0, 1.5, 40.0, 5.0)

    def test_clear_contrast(self) -> None:
        verdict = TransitionContrast().compare(
            _assess(*self.OFFICE), _assess(10.0, 9.0, 80.0, 25.0)
        )
        assert verdict.confirmed
        assert verdict.score == 1.0
        assert verdict.describe(outdoor_first=False) == (
            "indoor → outdoor: level -12.0 °C, daily spread x6.0, humidity +40 %, votes 4/4"
        )
        assert verdict.describe(outdoor_first=True).startswith(
            "outdoor → indoor: level +12.0 °C, daily spread x0.2, humidity -40 %"
        )

    def test_overcast_winter_needs_two_votes(self) -> None:
        # Spread 2.0 < 2 x 1.5; level 23 °C >= 5; humidity +50 % >= 15; RH spread 6 < 2 x 5.
        verdict = TransitionContrast().compare(_assess(*self.OFFICE), _assess(-1.0, 2.0, 90.0, 6.0))
        assert dict(verdict.votes) == {
            "spread_ratio": False,
            "level_difference": True,
            "humidity_excess": True,
            "humidity_spread_ratio": False,
        }
        assert verdict.confirmed
        assert verdict.score == 0.5
        strict = TransitionContrast(ContrastSettings(min_votes=3))
        assert not strict.compare(_assess(*self.OFFICE), _assess(-1.0, 2.0, 90.0, 6.0)).confirmed

    def test_absolute_rules_are_required(self) -> None:
        contrast = TransitionContrast()
        cloudy_day = _assess(20.0, 3.8, 72.0, 13.0)
        clear_days = _assess(22.0, 12.0, 60.0, 35.0)
        assert not contrast.compare(cloudy_day, clear_days).confirmed
        # An outdoor side that itself looks indoor-like cannot confirm a transition.
        assert not contrast.compare(_assess(*self.OFFICE), _assess(10.0, 1.0, 40.0, 4.0)).confirmed

    def test_temperature_only_needs_both_temperature_votes(self) -> None:
        contrast = TransitionContrast()
        office = _assess(22.0, 1.5, None, None)
        assert not contrast.compare(office, _assess(20.0, 9.0, None, None)).confirmed
        verdict = contrast.compare(office, _assess(10.0, 9.0, None, None))
        assert verdict.confirmed
        assert "humidity" not in verdict.describe(outdoor_first=False)
        assert contrast.settings.min_votes == 2


class TestWindowedChangePoints:
    def _search(self) -> WindowedChangePoints:
        return WindowedChangePoints(BinarySegmentation(1.0, 3.0, 5), 40.0, 20.0, 3.0, (0.01,))

    def test_pooled_change_point_is_reported_once(self) -> None:
        t_s = np.arange(100, dtype=np.float64)
        data = np.where(t_s < 50, 0.0, 5.0)[:, None]
        found = self._search().find(t_s, data)
        assert [c.position for c in found] == [50]

    def test_result_does_not_depend_on_where_the_series_starts(self) -> None:
        rng = np.random.default_rng(3)
        t_s = np.arange(400, dtype=np.float64)
        data = (np.where(t_s < 330, 0.0, 4.0) + rng.normal(0, 0.3, 400))[:, None]
        full = {int(t_s[c.position]) for c in self._search().find(t_s, data)}
        tail = {int(t_s[200 + c.position]) for c in self._search().find(t_s[200:], data[200:])}
        assert 330 in full
        assert {t for t in full if t >= 260} == {t for t in tail if t >= 260}

    def test_too_few_samples(self) -> None:
        assert self._search().find(np.arange(4.0), np.zeros((4, 1))) == ()


class TestBoundaries:
    def test_refiner_moves_to_the_largest_gain(self) -> None:
        t_s = np.arange(40, dtype=np.float64)
        data = np.where(t_s < 20, 0.0, 5.0)[:, None]
        refiner = BoundaryRefiner(10.0, (0.01,))
        assert refiner.refine(t_s, data, 24, 0, 40) == 20
        # No room to search: the first estimate is kept.
        assert refiner.refine(t_s, data, 24, 22, 27) == 24

    def _car_trace(self) -> tuple[np.ndarray, np.ndarray]:
        t_s = np.arange(0.0, 200 * 1800.0, 1800.0)
        temp = np.full(200, 22.0)
        temp[100:103] = 35.0  # car
        temp[103:] = 10.0 + 4.0 * np.sin(np.arange(97) * 2 * np.pi / 48)
        return t_s, temp

    def test_transport_after_the_office_becomes_indoor(self) -> None:
        t_s, temp = self._car_trace()
        trimmer = TransportTrimmer(TransportSettings(enabled=True))
        assert trimmer.trim(t_s, temp, 100, 0, 200) == 103
        assert trimmer.guard_s == 3 * 3600.0
        disabled = TransportTrimmer(TransportSettings(enabled=True, max_duration_s=0.0))
        assert disabled.trim(t_s, temp, 100, 0, 200) == 100
        assert TransportTrimmer().trim(t_s, temp, 100, 0, 200) == 100  # off by default
        # Too little outdoor reference data: unchanged.
        assert trimmer.trim(t_s, temp, 100, 0, 110) == 100

    def test_transport_before_the_office_becomes_indoor(self) -> None:
        t_s, temp = self._car_trace()
        reversed_temp = temp[::-1].copy()  # outdoor, car at 97..99, office from 100
        trimmer = TransportTrimmer(TransportSettings(enabled=True))
        assert trimmer.trim(t_s, reversed_temp, 100, 200, 0) == 97

    def test_values_inside_the_reference_ranges_stay(self) -> None:
        t_s, temp = self._car_trace()
        temp[100:103] = 12.0  # an ordinary first outdoor value
        assert TransportTrimmer(TransportSettings(enabled=True)).trim(t_s, temp, 100, 0, 200) == 100


class TestIndoorRun:
    def _boundary(self, kind: EventKind, confirmed: bool) -> Boundary:
        office, outdoor = _assess(22.0, 1.5, 40.0, 5.0), _assess(10.0, 9.0, 80.0, 25.0)
        verdict = TransitionContrast().compare(office, outdoor if confirmed else office)
        return Boundary(0, kind, verdict)

    def test_applied_needs_a_confirmed_redeployment(self) -> None:
        office = _assess(22.0, 1.5, 40.0, 5.0)
        retrieval = self._boundary(EventKind.RETRIEVAL, True)
        deployment = self._boundary(EventKind.DEPLOYMENT, True)
        weak = self._boundary(EventKind.DEPLOYMENT, False)
        assert IndoorRun(0, 1, office, None, deployment).applied
        assert IndoorRun(0, 1, office, retrieval, deployment).applied
        final = IndoorRun(0, 1, office, retrieval, None)
        assert not final.applied
        assert final.partly_confirmed
        half = IndoorRun(0, 1, office, retrieval, weak)
        assert (half.applied, half.partly_confirmed) == (False, True)
        nothing = IndoorRun(0, 1, office, None, weak)
        assert (nothing.applied, nothing.partly_confirmed) == (False, False)
        assert not Boundary(0, EventKind.DEPLOYMENT, None).confirmed
