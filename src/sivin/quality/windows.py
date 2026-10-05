r"""Local change-point search in overlapping windows of fixed length.

Binary segmentation over a whole multi-year series would depend on the series length (penalty
:math:`\ln n`, cap on the number of change points). :class:`WindowedChangePoints` therefore
runs it in windows of fixed duration :math:`W` that start every :math:`S` seconds **on a grid
anchored at the Unix epoch** (window :math:`k` covers :math:`[kS, kS + W)`). A window sees the
same data whatever the series length, so a transition is found identically in a 1-year and in
a 5-year series. The change points of all windows are pooled; of two change points closer
than the minimum separation the one with the larger gain is kept.
"""

from __future__ import annotations

import bisect
import logging
import math

import numpy as np
import numpy.typing as npt

from sivin.quality.changepoint import (
    MIN_SEGMENT_SAMPLES,
    BinarySegmentation,
    ChangePoint,
    GaussianSegmentCost,
)
from sivin.quality.samples import FloatArray

logger = logging.getLogger(__name__)


class WindowedChangePoints:
    """Binary segmentation in epoch-anchored overlapping windows (module docstring).

    Parameters
    ----------
    segmentation : BinarySegmentation
        The search run inside each window (its cap applies per window).
    window_s : float
        Window length W in seconds.
    stride_s : float
        Window start spacing S in seconds (``stride_s < window_s`` for overlap).
    min_separation_s : float
        Change points closer than this (s) are merged, keeping the larger gain.
    variance_floors : tuple of float
        Variance floor per data column (°C², %²).
    """

    __slots__ = (
        "_min_separation_s",
        "_segmentation",
        "_stride_s",
        "_variance_floors",
        "_window_s",
    )

    def __init__(
        self,
        segmentation: BinarySegmentation,
        window_s: float,
        stride_s: float,
        min_separation_s: float,
        variance_floors: tuple[float, ...],
    ) -> None:
        self._segmentation = segmentation
        self._window_s = window_s
        self._stride_s = stride_s
        self._min_separation_s = min_separation_s
        self._variance_floors = variance_floors

    def find(self, t_s: FloatArray, data: npt.NDArray[np.float64]) -> tuple[ChangePoint, ...]:
        """Find change points.

        Parameters
        ----------
        t_s : numpy.ndarray of float
            Sample times in seconds since the Unix epoch, increasing.
        data : numpy.ndarray of float, shape (n, d)
            Values per sample and variable, no ``NaN``.

        Returns
        -------
        tuple of ChangePoint
            Change points (positions in ``t_s``) sorted by position.
        """
        if t_s.size < 2 * MIN_SEGMENT_SAMPLES:
            return ()
        floors = np.array(self._variance_floors[: data.shape[1]])
        pooled: list[ChangePoint] = []
        first = math.floor((t_s[0] - self._window_s) / self._stride_s) + 1
        last = math.floor(t_s[-1] / self._stride_s)
        for k in range(first, last + 1):
            start = int(np.searchsorted(t_s, k * self._stride_s, side="left"))
            end = int(np.searchsorted(t_s, k * self._stride_s + self._window_s, side="left"))
            if end - start < 2 * MIN_SEGMENT_SAMPLES:
                continue
            cost = GaussianSegmentCost(data[start:end], floors)
            window_t = t_s[start:end]
            step_s = float(np.median(np.diff(window_t)))
            edges = np.append(window_t, window_t[-1] + step_s)
            pooled += [
                ChangePoint(c.position + start, c.gain) for c in self._segmentation.fit(cost, edges)
            ]
        return self._merged(pooled, t_s)

    def _merged(self, pooled: list[ChangePoint], t_s: FloatArray) -> tuple[ChangePoint, ...]:
        kept: list[ChangePoint] = []
        kept_t: list[float] = []
        for candidate in sorted(pooled, key=lambda c: (-c.gain, c.position)):
            t_candidate = float(t_s[candidate.position])
            i = bisect.bisect_left(kept_t, t_candidate)
            neighbours = kept_t[max(i - 1, 0) : i + 1]
            if all(abs(t_candidate - t) >= self._min_separation_s for t in neighbours):
                kept_t.insert(i, t_candidate)
                kept.append(candidate)
        logger.debug("%d change point(s) from %d window result(s).", len(kept), len(pooled))
        return tuple(sorted(kept))
