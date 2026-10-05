"""Find indoor stretches and their confirmed boundaries.

:class:`RegimeSegmenter` combines the building blocks:

1. change points in level and variance, found locally in epoch-anchored windows
   (:class:`~sivin.quality.windows.WindowedChangePoints`),
2. every segment between change points is checked against the absolute indoor-like rules
   (:class:`~sivin.quality.regime.RegimeClassifier`); consecutive indoor-like segments form an
   **indoor run** (a candidate office or service stay),
3. each boundary of a run is placed exactly (:class:`~sivin.quality.boundaries.BoundaryRefiner`)
   and a transport transient on its outdoor side is moved to the indoor side
   (:class:`~sivin.quality.boundaries.TransportTrimmer`),
4. each boundary is confirmed or rejected by the relative contrast between local windows on
   both sides (:class:`~sivin.quality.contrast.TransitionContrast`).

Which runs are applied is decided by :class:`IndoorRun` (see :attr:`IndoorRun.applied`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import numpy.typing as npt

from sivin.quality.boundaries import BoundaryRefiner, TransportTrimmer
from sivin.quality.contrast import ContrastVerdict, TransitionContrast
from sivin.quality.events import EventKind
from sivin.quality.regime import IndoorAssessment, RegimeClassifier
from sivin.quality.samples import FloatArray
from sivin.quality.windows import WindowedChangePoints

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Boundary:
    """One boundary of an indoor run.

    Attributes
    ----------
    position : int
        First sample of the new regime (coordinates of the segmenter's input).
    kind : EventKind
        ``RETRIEVAL`` (start of the run) or ``DEPLOYMENT`` (end of the run).
    verdict : ContrastVerdict or None
        The relative comparison; ``None`` if a local window had too few samples.
    """

    position: int
    kind: EventKind
    verdict: ContrastVerdict | None

    @property
    def confirmed(self) -> bool:
        """Whether the relative and absolute criteria hold."""
        return self.verdict is not None and self.verdict.confirmed


@dataclass(frozen=True, slots=True)
class IndoorRun:
    """A stretch of indoor-like samples and its boundaries.

    Attributes
    ----------
    start, end : int
        Half-open sample range ``[start, end)``.
    assessment : IndoorAssessment
        Absolute assessment of the whole run.
    retrieval : Boundary or None
        Boundary at ``start``; ``None`` if the run starts with the data.
    deployment : Boundary or None
        Boundary at ``end``; ``None`` if the run lasts until the end of the data.
    """

    start: int
    end: int
    assessment: IndoorAssessment
    retrieval: Boundary | None
    deployment: Boundary | None

    @property
    def applied(self) -> bool:
        """Whether the run counts as indoor (its samples become ``PRE_DEPLOYMENT``).

        A run is applied only if it ends with a confirmed deployment and, unless it starts
        with the data, begins with a confirmed retrieval. A retrieval without a later
        redeployment is never applied: it would exclude all later data on uncertain grounds.
        """
        if self.deployment is None or not self.deployment.confirmed:
            return False
        return self.retrieval is None or self.retrieval.confirmed

    @property
    def partly_confirmed(self) -> bool:
        """``True`` if some but not all boundaries needed for :attr:`applied` are confirmed."""
        boundaries = [b for b in (self.retrieval, self.deployment) if b is not None]
        return not self.applied and any(b.confirmed for b in boundaries)


@dataclass(frozen=True, slots=True)
class Segment:
    """A segment between change points and its absolute assessment.

    Attributes
    ----------
    start, end : int
        Half-open sample range.
    assessment : IndoorAssessment
        Absolute indoor-like assessment.
    """

    start: int
    end: int
    assessment: IndoorAssessment


@dataclass(frozen=True, slots=True)
class _Data:
    t_s: FloatArray
    temp_c: FloatArray
    rh_pct: FloatArray | None
    matrix: npt.NDArray[np.float64]

    @classmethod
    def of(cls, t_s: FloatArray, temp_c: FloatArray, rh_pct: FloatArray | None) -> _Data:
        columns = [temp_c] if rh_pct is None else [temp_c, rh_pct]
        return cls(t_s, temp_c, rh_pct, np.column_stack(columns))

    def index(self, t_s: float) -> int:
        return int(np.searchsorted(self.t_s, t_s))

    def rh(self, start: int, end: int) -> FloatArray | None:
        return None if self.rh_pct is None else self.rh_pct[start:end]


class RegimeSegmenter:
    """Find indoor runs and confirm their boundaries (module docstring).

    Parameters
    ----------
    change_points : WindowedChangePoints
        Local change-point search.
    classifier : RegimeClassifier
        Absolute indoor-like rules.
    contrast : TransitionContrast
        Relative confirmation (its ``window_s`` sets the local windows).
    refiner : BoundaryRefiner
        Exact boundary placement.
    trimmer : TransportTrimmer
        Transport transient handling.
    """

    __slots__ = ("_change_points", "_classifier", "_contrast", "_refiner", "_trimmer")

    def __init__(
        self,
        change_points: WindowedChangePoints,
        classifier: RegimeClassifier,
        contrast: TransitionContrast,
        refiner: BoundaryRefiner,
        trimmer: TransportTrimmer,
    ) -> None:
        self._change_points = change_points
        self._classifier = classifier
        self._contrast = contrast
        self._refiner = refiner
        self._trimmer = trimmer

    def split(
        self, t_s: FloatArray, temp_c: FloatArray, rh_pct: FloatArray | None
    ) -> tuple[list[Segment], list[IndoorRun]]:
        """Find segments and indoor runs.

        Parameters
        ----------
        t_s : numpy.ndarray of float
            Sample times in seconds since the Unix epoch, increasing.
        temp_c : numpy.ndarray of float
            Temperature in °C, no ``NaN``.
        rh_pct : numpy.ndarray of float or None
            Relative humidity in %, no ``NaN``; ``None`` to use temperature only.

        Returns
        -------
        tuple of (list of Segment, list of IndoorRun)
            All segments with their absolute assessment, and the indoor runs in time order.
        """
        if t_s.size == 0:
            return [], []
        data = _Data.of(t_s, temp_c, rh_pct)
        cuts = [0, *(c.position for c in self._change_points.find(t_s, data.matrix)), t_s.size]
        segments = [Segment(a, b, self._assess(data, a, b)) for a, b in pairwise(cuts)]
        spans = _indoor_spans(segments)
        runs = [self._run(data, spans, k) for k in range(len(spans))]
        logger.debug("%d segment(s), %d indoor run(s).", len(segments), len(runs))
        return segments, runs

    def _run(self, data: _Data, spans: list[tuple[int, int]], k: int) -> IndoorRun:
        n_samples = data.t_s.size
        start, end = spans[k]
        before = spans[k - 1][1] if k > 0 else 0
        after = spans[k + 1][0] if k + 1 < len(spans) else n_samples
        if start > 0:
            start = self._refiner.refine(data.t_s, data.matrix, start, before, end)
        if end < n_samples:
            end = self._refiner.refine(data.t_s, data.matrix, end, start, after)
        # The indoor window ends (starts) one maximum transport duration before (after) the
        # refined boundary, so a transport transient cannot distort it.
        retrieval = deployment = None
        if start > 0:
            trimmed = self._trimmer.trim(data.t_s, data.temp_c, start, end, before)
            retrieval = self._retrieval(data, start, end, before, trimmed)
        if end < n_samples:
            trimmed = self._trimmer.trim(data.t_s, data.temp_c, end, start, after)
            deployment = self._deployment(data, start, end, after, trimmed)
        return IndoorRun(start, end, self._assess(data, start, end), retrieval, deployment)

    def _deployment(self, data: _Data, start: int, end: int, after: int, trimmed: int) -> Boundary:
        window_s = self._contrast.settings.window_s
        last_indoor_s = data.t_s[end - 1]
        indoor_from = max(start, data.index(last_indoor_s - window_s))
        indoor_to = max(indoor_from, data.index(last_indoor_s - self._trimmer.guard_s))
        outdoor_to = min(after, data.index(data.t_s[trimmed] + window_s))
        verdict = self._verdict(data, (indoor_from, indoor_to), (trimmed, outdoor_to))
        return Boundary(trimmed, EventKind.DEPLOYMENT, verdict)

    def _retrieval(self, data: _Data, start: int, end: int, before: int, trimmed: int) -> Boundary:
        window_s = self._contrast.settings.window_s
        indoor_to = min(end, data.index(data.t_s[start] + window_s))
        indoor_from = min(indoor_to, data.index(data.t_s[start] + self._trimmer.guard_s))
        outdoor_from = max(before, data.index(data.t_s[trimmed - 1] - window_s))
        verdict = self._verdict(data, (indoor_from, indoor_to), (outdoor_from, trimmed))
        return Boundary(trimmed, EventKind.RETRIEVAL, verdict)

    def _verdict(
        self, data: _Data, indoor: tuple[int, int], outdoor: tuple[int, int]
    ) -> ContrastVerdict | None:
        minimum = self._contrast.settings.min_window_samples
        if min(indoor[1] - indoor[0], outdoor[1] - outdoor[0]) < minimum:
            return None
        return self._contrast.compare(self._assess(data, *indoor), self._assess(data, *outdoor))

    def _assess(self, data: _Data, start: int, end: int) -> IndoorAssessment:
        return self._classifier.assess(
            data.t_s[start:end], data.temp_c[start:end], data.rh(start, end)
        )


def _indoor_spans(segments: list[Segment]) -> list[tuple[int, int]]:
    """Merge consecutive indoor-like segments into ``(start, end)`` spans."""
    spans: list[tuple[int, int]] = []
    for segment in segments:
        if not segment.assessment.indoor_like:
            continue
        if spans and spans[-1][1] == segment.start:
            spans[-1] = (spans[-1][0], segment.end)
        else:
            spans.append((segment.start, segment.end))
    return spans
