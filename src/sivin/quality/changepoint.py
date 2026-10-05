r"""Change points in level and variance: Gaussian likelihood ratio and binary segmentation.

Model: within a segment the samples of each variable are independent Gaussian with a
segment-specific mean and variance; variables are independent of each other. For a segment
:math:`[a, b)` with :math:`m = b - a` samples the maximised log-likelihood is, up to terms
that cancel when comparing splits,

.. math:: -2 \ln L(a, b) = C(a, b) = m \sum_v \ln\left(\hat\sigma^2_v(a, b) + \sigma^2_{v,0}\right)

with :math:`\hat\sigma^2_v` the maximum-likelihood variance and :math:`\sigma^2_{v,0}` a variance
floor (quantised indoor data can have zero variance). Splitting at :math:`\tau` gains

.. math:: G(\tau) = C(a, b) - C(a, \tau) - C(\tau, b),

the log-likelihood-ratio statistic :math:`2 \ln \Lambda` of one change in mean and variance.
Prefix sums of :math:`x` and :math:`x^2` give every :math:`C` in O(1), so one scan over all
:math:`\tau` of a segment is O(m). Binary segmentation splits greedily (largest gain first)
until the best gain is below a penalty or a maximum number of change points is reached.
"""

from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from sivin.quality.samples import FloatArray

logger = logging.getLogger(__name__)

MIN_SEGMENT_SAMPLES = 3
"""Fewest samples a segment may have; a variance needs at least two (structural minimum)."""


class GaussianSegmentCost:
    """Segment cost :math:`C(a, b)` of the module docstring, from prefix sums.

    Parameters
    ----------
    data : numpy.ndarray of float, shape (n, d)
        One row per sample, one column per variable; no ``NaN``.
    variance_floor : numpy.ndarray of float, shape (d,)
        Variance floor per variable in the squared unit of the variable (e.g. °C²).

    Raises
    ------
    ValueError
        If the shapes do not match, ``data`` contains ``NaN`` or a floor is not positive.
    """

    __slots__ = ("_n_samples", "_sum", "_sum_sq", "_variance_floor")

    def __init__(self, data: npt.NDArray[np.float64], variance_floor: FloatArray) -> None:
        values = np.asarray(data, dtype=np.float64)
        floor = np.asarray(variance_floor, dtype=np.float64)
        if values.ndim != 2 or floor.shape != (values.shape[1],):
            raise ValueError(f"Shapes {values.shape} and {floor.shape} do not match.")
        if not np.isfinite(values).all():
            raise ValueError("data must not contain NaN or infinite values.")
        if not (floor > 0).all():
            raise ValueError("variance floors must be positive.")
        centred = values - values.mean(axis=0) if values.size else values
        zeros = np.zeros((1, values.shape[1]))
        self._sum = np.vstack([zeros, np.cumsum(centred, axis=0)])
        self._sum_sq = np.vstack([zeros, np.cumsum(centred**2, axis=0)])
        self._variance_floor = floor
        self._n_samples = int(values.shape[0])

    def __len__(self) -> int:
        return self._n_samples

    @property
    def n_parameters(self) -> int:
        """Free parameters per segment: a mean and a variance per variable."""
        n_variables: int = self._variance_floor.shape[0]
        return 2 * n_variables

    def cost(self, start: int, end: int) -> float:
        """Return :math:`C(start, end)`.

        Parameters
        ----------
        start, end : int
            Half-open sample range ``[start, end)``, ``end > start``.

        Returns
        -------
        float
            The cost (dimensionless, -2 x log-likelihood up to constants).
        """
        return float(self._costs(np.array([start]), np.array([end]))[0])

    def split_gains(self, start: int, end: int, splits: npt.NDArray[np.intp]) -> FloatArray:
        """Return :math:`G(\\tau)` for every split position ``tau`` in ``splits``.

        Parameters
        ----------
        start, end : int
            The segment ``[start, end)``.
        splits : numpy.ndarray of int
            Candidate positions with ``start < tau < end``.

        Returns
        -------
        numpy.ndarray of float
            Gain per candidate (dimensionless log-likelihood-ratio statistic).
        """
        starts = np.full(splits.shape, start)
        ends = np.full(splits.shape, end)
        whole = self.cost(start, end)
        return whole - self._costs(starts, splits) - self._costs(splits, ends)

    def _costs(self, starts: npt.NDArray[np.intp], ends: npt.NDArray[np.intp]) -> FloatArray:
        n_samples = (ends - starts).astype(np.float64)[:, None]
        mean = (self._sum[ends] - self._sum[starts]) / n_samples
        variance = (self._sum_sq[ends] - self._sum_sq[starts]) / n_samples - mean**2
        variance = np.maximum(variance, 0.0) + self._variance_floor
        return np.asarray(n_samples[:, 0] * np.log(variance).sum(axis=1), dtype=np.float64)


@dataclass(frozen=True, slots=True, order=True)
class ChangePoint:
    """A change point: the first sample of a new segment.

    Attributes
    ----------
    position : int
        Sample position (in the coordinates of the cost's data).
    gain : float
        Log-likelihood-ratio statistic :math:`G` of the split (dimensionless).
    """

    position: int
    gain: float


@dataclass(order=True)
class _Candidate:
    """Best split of one segment, ordered for a max-heap by negative gain."""

    neg_gain: float
    start: int = field(compare=False)
    end: int = field(compare=False)
    split: int = field(compare=False)


class BinarySegmentation:
    r"""Greedy binary segmentation with a penalty, a minimum segment duration and a cap.

    A split must gain at least the BIC-like penalty
    :math:`\beta = c \, (p + 1) \ln n`, where :math:`p` is the number of parameters per
    segment (:attr:`GaussianSegmentCost.n_parameters`), the extra 1 the change-point location,
    :math:`n` the number of samples and :math:`c` the penalty factor.

    Parameters
    ----------
    penalty_factor : float
        Factor :math:`c` (dimensionless); 1 is the Schwarz/BIC weight.
    min_segment_s : float
        Shortest segment duration in seconds.
    max_change_points : int
        Largest number of change points returned.
    """

    __slots__ = ("_max_change_points", "_min_segment_s", "_penalty_factor")

    def __init__(self, penalty_factor: float, min_segment_s: float, max_change_points: int) -> None:
        self._penalty_factor = penalty_factor
        self._min_segment_s = min_segment_s
        self._max_change_points = max_change_points

    def fit(self, cost: GaussianSegmentCost, edges_s: FloatArray) -> tuple[ChangePoint, ...]:
        """Find change points.

        Parameters
        ----------
        cost : GaussianSegmentCost
            Segment cost over ``n`` samples.
        edges_s : numpy.ndarray of float, shape (n + 1,)
            Time (s) at which each sample's slot begins, plus the end of the last slot; the
            duration of segment ``[a, b)`` is ``edges_s[b] - edges_s[a]``.

        Returns
        -------
        tuple of ChangePoint
            Change points sorted by position.
        """
        if len(cost) < 2 * MIN_SEGMENT_SAMPLES:
            return ()
        penalty = self.penalty(cost)
        found: list[ChangePoint] = []
        heap: list[_Candidate] = []
        self._push_best_split(cost, edges_s, 0, len(cost), penalty, heap)
        while heap and len(found) < self._max_change_points:
            best = heapq.heappop(heap)
            found.append(ChangePoint(best.split, -best.neg_gain))
            self._push_best_split(cost, edges_s, best.start, best.split, penalty, heap)
            self._push_best_split(cost, edges_s, best.split, best.end, penalty, heap)
        logger.debug("Binary segmentation found %d change point(s).", len(found))
        return tuple(sorted(found))

    def penalty(self, cost: GaussianSegmentCost) -> float:
        """Return the penalty :math:`\\beta` for a cost over ``len(cost)`` samples.

        Parameters
        ----------
        cost : GaussianSegmentCost
            The segment cost.

        Returns
        -------
        float
            Smallest gain (dimensionless) a split must reach.
        """
        return self._penalty_factor * (cost.n_parameters + 1) * float(np.log(max(len(cost), 2)))

    def _push_best_split(
        self,
        cost: GaussianSegmentCost,
        edges_s: FloatArray,
        start: int,
        end: int,
        penalty: float,
        heap: list[_Candidate],
    ) -> None:
        splits = np.arange(start + MIN_SEGMENT_SAMPLES, end - MIN_SEGMENT_SAMPLES + 1)
        long_enough = (edges_s[splits] - edges_s[start] >= self._min_segment_s) & (
            edges_s[end] - edges_s[splits] >= self._min_segment_s
        )
        splits = splits[long_enough]
        if splits.size == 0:
            return
        gains = cost.split_gains(start, end, splits)
        best = int(np.argmax(gains))
        if gains[best] >= penalty:
            heapq.heappush(heap, _Candidate(-float(gains[best]), start, end, int(splits[best])))
