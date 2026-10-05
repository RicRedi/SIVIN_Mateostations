"""Detection of deployments and retrievals of a sensor (MIGRATION_PLAN §2.7).

Every sensor is switched on in the office and then carried into the vineyard; it may be brought
back for service and redeployed. :class:`DeploymentDetector`

1. finds change points in level and variance of temperature (and humidity) with a Gaussian
   likelihood ratio and binary segmentation (:mod:`sivin.quality.changepoint`),
2. labels every segment indoor or outdoor (:class:`~sivin.quality.regime.RegimeClassifier`),
3. reports a ``deployment`` at each indoor → outdoor boundary and a ``retrieval`` at each
   outdoor → indoor boundary (:class:`~sivin.quality.events.DeploymentEvent`),
4. reconciles them with known deployment times (:mod:`sivin.quality.timeline`), and
5. marks every sample recorded while indoor ``PRE_DEPLOYMENT``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from sivin.core.flags import QcFlag, excluded
from sivin.core.schema import MeasurementSeries
from sivin.quality.changepoint import BinarySegmentation
from sivin.quality.checks.base import CheckOutcome
from sivin.quality.events import DeploymentEvent, EventKind, QualityEvent
from sivin.quality.regime import Regime, RegimeClassifier, RegimeSettings, RegimeVerdict
from sivin.quality.samples import S_PER_DAY, S_PER_H, SampleArrays
from sivin.quality.segmentation import RegimeSegmenter, RegimeSpan
from sivin.quality.timeline import ORIGIN, DeploymentTimeline, KnownDeploymentReconciler

logger = logging.getLogger(__name__)

DEFAULT_IGNORE_MASK = int(QcFlag.MISSING | QcFlag.OUT_OF_RANGE | QcFlag.MANUAL_EXCLUDE)
"""Samples with these flags are not used for detection (they would distort the likelihood)."""

MIN_SPREAD_FOR_RATIO_C = 0.1
"""Daily spread (°C) used instead of a smaller one when reporting spread ratios (display only)."""


class ChangePointSettings(BaseModel):
    """Settings of the change-point search (all project defaults, to be tuned on real data)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_segment_s: float = Field(
        S_PER_DAY,
        gt=0,
        description=(
            "Shortest segment in seconds; also the shortest indoor stay (service) that can be "
            "detected. Project default 1 day, so that every segment has a daily spread."
        ),
    )
    penalty_factor: float = Field(
        1.0,
        gt=0,
        description=(
            "Factor c (dimensionless) of the BIC-like penalty c·(p+1)·ln n a split must gain. "
            "1 = Schwarz/BIC weight. Project default."
        ),
    )
    max_change_points: int = Field(
        50,
        ge=1,
        description=(
            "Largest number of change points (count). Outdoor weather produces many change "
            "points that the regime classifier merges again; the cap bounds the work. Project "
            "default."
        ),
    )
    temp_variance_floor_c2: float = Field(
        0.01,
        gt=0,
        description=(
            "Variance floor of temperature in °C² (= (0.1 °C)²), so quantised indoor data "
            "do not have zero variance. Project default."
        ),
    )
    rh_variance_floor_pct2: float = Field(
        0.25,
        gt=0,
        description="Variance floor of relative humidity in %² (= (0.5 %)²). Project default.",
    )
    min_rh_fraction: float = Field(
        0.5,
        ge=0,
        le=1,
        description=(
            "Humidity is used only if at least this share (0-1, dimensionless) of the usable "
            "temperature samples also has a humidity value. Project default."
        ),
    )


class DeploymentSettings(BaseModel):
    """Settings of :class:`DeploymentDetector`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    change_points: ChangePointSettings = Field(
        default_factory=ChangePointSettings, description="Change-point search."
    )
    regime: RegimeSettings = Field(
        default_factory=RegimeSettings, description="Indoor/outdoor rules."
    )
    known_tolerance_s: float = Field(
        6 * S_PER_H,
        ge=0,
        description=(
            "Largest distance in seconds between a detected and a known deployment that still "
            "counts as agreement; a larger one produces a warning. Project default 6 h."
        ),
    )
    ignore_mask: StrictInt = Field(
        DEFAULT_IGNORE_MASK,
        ge=0,
        description=(
            "QcFlag bits (integer bit mask, dimensionless) of samples not used for detection. "
            "Default MISSING|OUT_OF_RANGE|MANUAL_EXCLUDE = 259."
        ),
    )

    @field_validator("ignore_mask")
    @classmethod
    def _known_flags(cls, value: int) -> int:
        unknown = value & ~QcFlag.all_bits()
        if unknown:
            raise ValueError(f"bits {unknown} are not QcFlag values")
        return value


@dataclass(frozen=True, slots=True)
class SegmentRecord:
    """One segment between change points and its regime.

    Attributes
    ----------
    start_utc, end_utc : pandas.Timestamp
        Times of the first and the last usable sample of the segment (UTC).
    n_samples : int
        Number of usable samples.
    verdict : RegimeVerdict
        Regime, score, confidence and features.
    """

    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
    n_samples: int
    verdict: RegimeVerdict

    @property
    def regime(self) -> Regime:
        """The regime of the segment."""
        return self.verdict.regime


@dataclass(frozen=True, slots=True)
class DeploymentResult:
    """Outcome of :meth:`DeploymentDetector.detect`.

    Attributes
    ----------
    events : tuple of QualityEvent
        Applied transitions (:class:`DeploymentEvent`) and ``deployment_mismatch`` warnings,
        in time order.
    pre_deployment : numpy.ndarray of bool
        ``True`` for each row recorded while the sensor was indoors (read-only).
    segments : tuple of SegmentRecord
        The segments and their regimes, for inspection.
    """

    events: tuple[QualityEvent, ...]
    pre_deployment: npt.NDArray[np.bool_]
    segments: tuple[SegmentRecord, ...]

    @property
    def transitions(self) -> tuple[DeploymentEvent, ...]:
        """The applied deployments and retrievals."""
        return tuple(e for e in self.events if isinstance(e, DeploymentEvent))

    def outcome(self) -> CheckOutcome:
        """Return the result as flags and events.

        Returns
        -------
        CheckOutcome
            ``PRE_DEPLOYMENT`` on indoor rows and all events.
        """
        return CheckOutcome.from_mask(self.pre_deployment, QcFlag.PRE_DEPLOYMENT, self.events)

    def deployed_ranges(self) -> tuple[tuple[int, int], ...]:
        """Return the row ranges recorded in the vineyard.

        Returns
        -------
        tuple of (int, int)
            Half-open row ranges ``[start, stop)`` of consecutive outdoor rows.
        """
        outdoor = np.concatenate(([False], ~self.pre_deployment, [False])).astype(np.int8)
        edges = np.flatnonzero(np.diff(outdoor))
        return tuple((int(a), int(b)) for a, b in zip(edges[::2], edges[1::2], strict=True))


class DeploymentDetector:
    """Detect deployments and retrievals and mark indoor samples (see the module docstring).

    Parameters
    ----------
    settings : DeploymentSettings, optional
        Settings; defaults when omitted.
    segmenter : RegimeSegmenter, optional
        Change-point search and regime labelling; built from ``settings`` when omitted.
    """

    __slots__ = ("_segmenter", "_settings")

    def __init__(
        self,
        settings: DeploymentSettings | None = None,
        segmenter: RegimeSegmenter | None = None,
    ) -> None:
        self._settings = settings or DeploymentSettings()
        self._segmenter = segmenter or self._default_segmenter(self._settings)

    @staticmethod
    def _default_segmenter(settings: DeploymentSettings) -> RegimeSegmenter:
        cp = settings.change_points
        return RegimeSegmenter(
            BinarySegmentation(cp.penalty_factor, cp.min_segment_s, cp.max_change_points),
            RegimeClassifier(settings.regime),
            cp.min_segment_s,
            (cp.temp_variance_floor_c2, cp.rh_variance_floor_pct2),
        )

    @property
    def settings(self) -> DeploymentSettings:
        """The settings."""
        return self._settings

    def detect(
        self,
        series: MeasurementSeries,
        known_deployments: Sequence[datetime | pd.Timestamp] = (),
    ) -> DeploymentResult:
        """Detect transitions in one series.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements; rows flagged with :attr:`DeploymentSettings.ignore_mask` and rows
            without temperature are not used for detection, but are marked like their
            neighbours in time.
        known_deployments : sequence of datetime, optional
            Known deployment times (timezone-aware, e.g. ``placement.from`` of the registry);
            they override detection (see :mod:`sivin.quality.timeline`).

        Returns
        -------
        DeploymentResult
            Events, ``PRE_DEPLOYMENT`` mask and segments.

        Raises
        ------
        ValueError
            If a known deployment time is not timezone-aware.
        """
        known = [_aware_utc(k) for k in known_deployments]
        samples = SampleArrays.of(series)
        usable, rh_used = self._usable(samples)
        segments = self._regimes(samples, usable, rh_used)
        detected = self._transitions(samples, usable, segments)
        reconciled = KnownDeploymentReconciler(self._settings.known_tolerance_s).reconcile(
            detected, known
        )
        starts_indoor = bool(known) or (
            bool(segments) and segments[0].verdict.regime is Regime.INDOOR
        )
        indoor = DeploymentTimeline(reconciled.transitions, starts_indoor).indoor_mask(samples.t_ns)
        indoor.setflags(write=False)
        events = sorted((*reconciled.transitions, *reconciled.warnings), key=lambda e: e.t_utc)
        logger.info(
            "Sensor %s: %d transition(s), %d warning(s), %d pre-deployment sample(s).",
            series.sensor_id,
            len(reconciled.transitions),
            len(reconciled.warnings),
            int(indoor.sum()),
        )
        records = tuple(
            SegmentRecord(
                samples.timestamp(int(usable[s.start])),
                samples.timestamp(int(usable[s.end - 1])),
                s.end - s.start,
                s.verdict,
            )
            for s in segments
        )
        return DeploymentResult(tuple(events), indoor, records)

    def _usable(self, samples: SampleArrays) -> tuple[npt.NDArray[np.intp], bool]:
        """Return the row positions used for detection and whether humidity is used."""
        base = np.isfinite(samples.temp_c) & ~excluded(samples.qc, self._settings.ignore_mask)
        with_rh = base & np.isfinite(samples.rh_pct)
        n_base = int(base.sum())
        min_rh_fraction = self._settings.change_points.min_rh_fraction
        rh_used = n_base > 0 and int(with_rh.sum()) >= min_rh_fraction * n_base
        return np.flatnonzero(with_rh if rh_used else base), rh_used

    def _regimes(
        self, samples: SampleArrays, usable: npt.NDArray[np.intp], rh_used: bool
    ) -> list[RegimeSpan]:
        return self._segmenter.split(
            samples.t_s[usable],
            samples.temp_c[usable],
            samples.rh_pct[usable] if rh_used else None,
        )

    def _transitions(
        self, samples: SampleArrays, usable: npt.NDArray[np.intp], segments: list[RegimeSpan]
    ) -> list[DeploymentEvent]:
        # Adjacent regimes always differ (RegimeSegmenter merges equal neighbours), so every
        # boundary is a transition.
        events: list[DeploymentEvent] = []
        for left, right in pairwise(segments):
            kind = (
                EventKind.DEPLOYMENT
                if right.verdict.regime is Regime.OUTDOOR
                else EventKind.RETRIEVAL
            )
            events.append(
                DeploymentEvent(
                    kind=kind,
                    t_utc=samples.timestamp(int(usable[right.start])),
                    detail=_describe(left.verdict, right.verdict),
                    confidence=min(left.verdict.confidence, right.verdict.confidence),
                    origin=ORIGIN,
                )
            )
        return events


def _describe(before: RegimeVerdict, after: RegimeVerdict) -> str:
    shift_c = after.features.temp_median_c - before.features.temp_median_c
    ratio = max(after.features.daily_spread_c, MIN_SPREAD_FOR_RATIO_C) / max(
        before.features.daily_spread_c, MIN_SPREAD_FOR_RATIO_C
    )
    text = f"{before.regime.value} → {after.regime.value}: step {shift_c:+.1f} °C, "
    text += f"daily spread x{ratio:.1f}"
    if before.features.rh_median_pct is not None and after.features.rh_median_pct is not None:
        text += f", humidity {after.features.rh_median_pct - before.features.rh_median_pct:+.0f} %"
    return text


def _aware_utc(value: datetime | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tz is None:
        raise ValueError(f"Known deployment times must be timezone-aware, got {value!r}.")
    return timestamp.tz_convert("UTC")
