"""Split a series into indoor and outdoor regimes.

:class:`RegimeSegmenter` combines the change-point search and the regime rules:

1. binary segmentation on the Gaussian level-and-variance cost
   (:mod:`sivin.quality.changepoint`) cuts the series into segments of at least the minimum
   duration,
2. every segment is labelled indoor or outdoor (:class:`~sivin.quality.regime.RegimeClassifier`),
3. adjacent segments with the same label are merged into one regime,
4. every regime boundary is **refined**: within the two regimes it separates, and at most the
   minimum segment duration away from the first estimate, the position with the largest
   likelihood-ratio gain wins. The minimum duration constrains the search, not the final
   boundary; without this step a boundary close to an earlier change point could not be
   placed exactly.
5. the merged regimes are classified again on their final extent (features, score and
   confidence of the reported events); adjacent regimes that now share a label are merged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from sivin.quality.changepoint import MIN_SEGMENT_SAMPLES, BinarySegmentation, GaussianSegmentCost
from sivin.quality.regime import RegimeClassifier, RegimeVerdict
from sivin.quality.samples import FloatArray

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RegimeSpan:
    """A run of samples in one regime.

    Attributes
    ----------
    start, end : int
        Half-open sample range ``[start, end)`` in the coordinates of the segmenter's input.
    verdict : RegimeVerdict
        Regime, score, confidence and features of the run.
    """

    start: int
    end: int
    verdict: RegimeVerdict


class RegimeSegmenter:
    """Cut samples into indoor/outdoor regimes (steps in the module docstring).

    Parameters
    ----------
    segmentation : BinarySegmentation
        The change-point search.
    classifier : RegimeClassifier
        The regime rules.
    min_segment_s : float
        Minimum segment duration in seconds; also the refinement radius.
    variance_floors : tuple of float
        Variance floor per variable (°C², %²), in the column order of the data.
    """

    __slots__ = ("_classifier", "_min_segment_s", "_segmentation", "_variance_floors")

    def __init__(
        self,
        segmentation: BinarySegmentation,
        classifier: RegimeClassifier,
        min_segment_s: float,
        variance_floors: tuple[float, ...],
    ) -> None:
        self._segmentation = segmentation
        self._classifier = classifier
        self._min_segment_s = min_segment_s
        self._variance_floors = variance_floors

    def split(
        self, t_s: FloatArray, temp_c: FloatArray, rh_pct: FloatArray | None
    ) -> list[RegimeSpan]:
        """Split samples into regimes.

        Parameters
        ----------
        t_s : numpy.ndarray of float
            Sample times in seconds, increasing.
        temp_c : numpy.ndarray of float
            Temperature in °C, no ``NaN``.
        rh_pct : numpy.ndarray of float or None
            Relative humidity in %, no ``NaN``; ``None`` to use temperature only.

        Returns
        -------
        list of RegimeSpan
            Consecutive regimes covering all samples; adjacent regimes differ in label.
        """
        if t_s.size == 0:
            return []
        columns = [temp_c] if rh_pct is None else [temp_c, rh_pct]
        floors = np.array(self._variance_floors[: len(columns)])
        cost = GaussianSegmentCost(np.column_stack(columns), floors)
        step_s = float(np.median(np.diff(t_s))) if t_s.size > 1 else 0.0
        edges_s = np.append(t_s, t_s[-1] + step_s)
        cuts = [0, *(c.position for c in self._segmentation.fit(cost, edges_s)), t_s.size]
        labels = [self._classify(t_s, temp_c, rh_pct, a, b).regime for a, b in pairwise(cuts)]
        bounds = [0] + [cuts[i + 1] for i in range(len(labels) - 1) if labels[i] != labels[i + 1]]
        bounds.append(t_s.size)
        bounds = self._refined(bounds, cost, edges_s)
        spans = [
            RegimeSpan(a, b, self._classify(t_s, temp_c, rh_pct, a, b)) for a, b in pairwise(bounds)
        ]
        return self._merged(spans, t_s, temp_c, rh_pct)

    def _refined(
        self, bounds: list[int], cost: GaussianSegmentCost, edges_s: FloatArray
    ) -> list[int]:
        refined = list(bounds)
        for k in range(1, len(refined) - 1):
            start, end = refined[k - 1], bounds[k + 1]
            first = edges_s[refined[k]]
            candidates = np.arange(start + MIN_SEGMENT_SAMPLES, end - MIN_SEGMENT_SAMPLES + 1)
            near = np.abs(edges_s[candidates] - first) <= self._min_segment_s
            candidates = candidates[near]
            if candidates.size:
                gains = cost.split_gains(start, end, candidates)
                refined[k] = int(candidates[int(np.argmax(gains))])
        return refined

    def _merged(
        self,
        spans: list[RegimeSpan],
        t_s: FloatArray,
        temp_c: FloatArray,
        rh_pct: FloatArray | None,
    ) -> list[RegimeSpan]:
        merged: list[RegimeSpan] = []
        for span in spans:
            current = span
            while merged and merged[-1].verdict.regime is current.verdict.regime:
                start = merged.pop().start
                verdict = self._classify(t_s, temp_c, rh_pct, start, current.end)
                current = RegimeSpan(start, current.end, verdict)
            merged.append(current)
        logger.debug("%d regime(s) after merging.", len(merged))
        return merged

    def _classify(
        self, t_s: FloatArray, temp_c: FloatArray, rh_pct: FloatArray | None, start: int, end: int
    ) -> RegimeVerdict:
        return self._classifier.classify(
            t_s[start:end], temp_c[start:end], None if rh_pct is None else rh_pct[start:end]
        )
