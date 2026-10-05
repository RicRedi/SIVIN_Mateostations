"""Tests of the change-point math and the regime rules. SYNTHETIC data only."""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from sivin.quality.changepoint import BinarySegmentation, ChangePoint, GaussianSegmentCost
from sivin.quality.regime import (
    Regime,
    RegimeClassifier,
    RegimeSettings,
    RegimeVerdict,
    SegmentFeatures,
)
from sivin.quality.segmentation import RegimeSegmenter


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


class TestRegimeClassifier:
    def test_hand_computed_scores(self) -> None:
        classifier = RegimeClassifier()
        # Inside the band (0 °C away), spread 4.5 °C: (4.5 - 3) / 3 = 0.5 -> 0.5; RH 50 % -> 1.
        borderline = classifier.indoor_score(SegmentFeatures(25.0, 4.5, 50.0))
        assert borderline == pytest.approx(0.5)
        # 3 °C above the band: 1 - 3 / 4 = 0.25.
        warm = classifier.indoor_score(SegmentFeatures(30.0, 1.0, 40.0))
        assert warm == pytest.approx(0.25)
        # Humid: (72.5 - 65) / 15 = 0.5 -> 0.5; without humidity only band and spread count.
        assert classifier.indoor_score(SegmentFeatures(22.0, 1.0, 72.5)) == pytest.approx(0.5)
        assert classifier.indoor_score(SegmentFeatures(22.0, 1.0, None)) == pytest.approx(1.0)

    def test_classify_indoor_and_outdoor(self) -> None:
        t_s = np.arange(0.0, 2 * 86_400.0, 1800.0)
        indoor = RegimeClassifier().classify(
            t_s, np.full(t_s.shape, 22.0), np.full(t_s.shape, 40.0)
        )
        assert (indoor.regime, indoor.indoor_score, indoor.confidence) == (Regime.INDOOR, 1.0, 1.0)
        outdoor_temp = 10.0 + 5.0 * np.sin(2 * np.pi * t_s / 86_400.0)
        outdoor = RegimeClassifier().classify(t_s, outdoor_temp, None)
        assert outdoor.regime is Regime.OUTDOOR
        assert outdoor.confidence == 1.0
        assert outdoor.features.rh_median_pct is None

    def test_daily_spread_is_median_of_window_spreads(self) -> None:
        t_s = np.arange(96, dtype=np.float64) * 1800.0  # two days of 48 samples
        temp = np.concatenate([np.arange(48) * 0.1, np.full(48, 1.0)])
        features = RegimeClassifier().features(t_s, temp, None)
        # Day 1: P95 - P5 of 0.0..4.7 = 4.465 - 0.235 = 4.23; day 2: 0. Median = 2.115.
        assert features.daily_spread_c == pytest.approx(2.115)

    def test_short_segment_uses_all_samples(self) -> None:
        t_s = np.arange(5, dtype=np.float64) * 1800.0
        features = RegimeClassifier().features(t_s, np.array([0.0, 1.0, 2.0, 3.0, 4.0]), None)
        # P95 - P5 of 0..4 = 3.8 - 0.2 = 3.6.
        assert features.daily_spread_c == pytest.approx(3.6)

    def test_settings_validation(self) -> None:
        with pytest.raises(ValidationError, match="comfort_band_low_c"):
            RegimeSettings(comfort_band_low_c=30.0, comfort_band_high_c=20.0)
        assert (
            RegimeClassifier(RegimeSettings(indoor_threshold=0.6)).settings.indoor_threshold == 0.6
        )


class _ScriptedClassifier(RegimeClassifier):
    """Returns pre-set regimes in call order (test double)."""

    def __init__(self, regimes: list[Regime]) -> None:
        super().__init__()
        self._regimes = list(regimes)

    def classify(
        self, t_s: np.ndarray, temp_c: np.ndarray, rh_pct: np.ndarray | None
    ) -> RegimeVerdict:
        regime = self._regimes.pop(0)
        score = 1.0 if regime is Regime.INDOOR else 0.0
        return RegimeVerdict(regime, score, 1.0, self.features(t_s, temp_c, rh_pct))


class TestRegimeSegmenter:
    def _segmenter(self, classifier: RegimeClassifier) -> RegimeSegmenter:
        return RegimeSegmenter(BinarySegmentation(1.0, 3.0, 5), classifier, 3.0, (0.01,))

    def test_regimes_that_agree_after_reclassification_are_merged(self) -> None:
        t_s = np.arange(40, dtype=np.float64)
        temp = np.array([0.0] * 10 + [5.0] * 10 + [0.5] * 20)
        # First pass (3 segments): indoor, outdoor, indoor -> two boundaries. Second pass on
        # the refined spans: outdoor, outdoor, outdoor -> merged into one (two re-merges).
        scripted = [Regime.INDOOR, Regime.OUTDOOR, Regime.INDOOR] + [Regime.OUTDOOR] * 5
        spans = self._segmenter(_ScriptedClassifier(scripted)).split(t_s, temp, None)
        assert [(s.start, s.end, s.verdict.regime) for s in spans] == [(0, 40, Regime.OUTDOOR)]

    def test_boundaries_are_refined_to_the_largest_gain(self) -> None:
        t_s = np.arange(40, dtype=np.float64)
        temp = np.array([0.0] * 10 + [5.0] * 10 + [0.5] * 20)
        scripted = [Regime.INDOOR, Regime.OUTDOOR, Regime.INDOOR] * 2
        spans = self._segmenter(_ScriptedClassifier(scripted)).split(t_s, temp, None)
        assert [(s.start, s.end) for s in spans] == [(0, 10), (10, 20), (20, 40)]

    def test_empty_input(self) -> None:
        empty = np.array([], dtype=np.float64)
        assert self._segmenter(RegimeClassifier()).split(empty, empty, None) == []
