"""Detection of deployments and retrievals of a sensor (MIGRATION_PLAN §2.7).

Every sensor is switched on in the office and then carried into the vineyard; it may be brought
back for service and redeployed. :class:`DeploymentDetector`

1. finds change points in level and variance of temperature (and humidity) with a Gaussian
   likelihood ratio and binary segmentation, locally in fixed windows
   (:mod:`sivin.quality.changepoint`, :mod:`sivin.quality.windows`),
2. groups indoor-like segments into candidate indoor runs (absolute rules,
   :mod:`sivin.quality.regime`), places their boundaries exactly and moves a transport
   transient to the indoor side (:mod:`sivin.quality.boundaries`),
3. confirms each boundary by the relative contrast between local windows on both sides
   (:mod:`sivin.quality.contrast`); a run counts as indoor only if all its boundaries are
   confirmed and it ends with a redeployment (:mod:`sivin.quality.segmentation`),
4. reconciles the indoor intervals with known deployment times (:mod:`sivin.quality.timeline`),
5. marks every sample recorded while indoors ``PRE_DEPLOYMENT``.

Guiding principle: when the evidence is not clear, the detector warns and does not exclude data.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from sivin.core.flags import QcFlag, excluded
from sivin.core.schema import MeasurementSeries
from sivin.quality.boundaries import BoundaryRefiner, TransportSettings, TransportTrimmer
from sivin.quality.changepoint import BinarySegmentation
from sivin.quality.checks.base import CheckOutcome
from sivin.quality.contrast import ContrastSettings, TransitionContrast
from sivin.quality.events import DeploymentEvent, EventKind, QualityEvent, Severity
from sivin.quality.regime import IndoorAssessment, Regime, RegimeClassifier, RegimeSettings
from sivin.quality.samples import S_PER_DAY, S_PER_H, SampleArrays
from sivin.quality.segmentation import Boundary, IndoorRun, RegimeSegmenter
from sivin.quality.timeline import (
    ORIGIN,
    IndoorInterval,
    KnownDeploymentReconciler,
    indoor_mask,
)
from sivin.quality.windows import WindowedChangePoints

logger = logging.getLogger(__name__)

DEFAULT_IGNORE_MASK = int(QcFlag.MISSING | QcFlag.OUT_OF_RANGE | QcFlag.MANUAL_EXCLUDE)
"""Samples with these flags are not used for detection (they would distort the likelihood)."""


class ChangePointSettings(BaseModel):
    """Settings of the change-point search (all project defaults, to be tuned on real data)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_segment_s: float = Field(
        S_PER_DAY,
        gt=0,
        description=(
            "Shortest segment in seconds; also the shortest indoor stay (service) that can be "
            "detected, the minimum separation of change points and the refinement radius. "
            "Project default 1 day, so that every segment has a daily spread."
        ),
    )
    window_s: float = Field(
        30 * S_PER_DAY,
        gt=0,
        description=(
            "Length (s) of the windows the search runs in; the result does not depend on the "
            "series length. Project default 30 days."
        ),
    )
    stride_s: float = Field(
        15 * S_PER_DAY,
        gt=0,
        description="Spacing (s) of the window starts (epoch-anchored). Project default 15 days.",
    )
    penalty_factor: float = Field(
        1.0,
        gt=0,
        description=(
            "Factor c (dimensionless) of the BIC-like penalty c·(p+1)·ln n a split must gain "
            "(n = samples in the window). 1 = Schwarz/BIC weight. Project default."
        ),
    )
    max_change_points: int = Field(
        30,
        ge=1,
        description=(
            "Largest number of change points (count) per window; with 1-day minimum segments "
            "a 30-day window cannot hold more. Project default."
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

    @property
    def variance_floors(self) -> tuple[float, float]:
        """Variance floors of temperature (°C²) and humidity (%²)."""
        return (self.temp_variance_floor_c2, self.rh_variance_floor_pct2)


class DeploymentSettings(BaseModel):
    """Settings of :class:`DeploymentDetector`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    change_points: ChangePointSettings = Field(
        default_factory=ChangePointSettings, description="Change-point search."
    )
    regime: RegimeSettings = Field(
        default_factory=RegimeSettings, description="Absolute indoor-like rules."
    )
    contrast: ContrastSettings = Field(
        default_factory=ContrastSettings, description="Relative confirmation of transitions."
    )
    transport: TransportSettings = Field(
        default_factory=TransportSettings, description="Transport transient handling."
    )
    known_tolerance_s: float = Field(
        6 * S_PER_H,
        ge=0,
        description=(
            "Largest distance in seconds between a detected and a known deployment that still "
            "counts as agreement. Project default 6 h [to be tuned with Q3]."
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
    """One segment between change points and its absolute assessment.

    Attributes
    ----------
    start_utc, end_utc : pandas.Timestamp
        Times of the first and the last usable sample of the segment (UTC).
    n_samples : int
        Number of usable samples.
    assessment : IndoorAssessment
        Features and absolute indoor-like criteria.
    """

    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
    n_samples: int
    assessment: IndoorAssessment

    @property
    def regime(self) -> Regime:
        """``INDOOR`` if the segment is indoor-like (absolute rules only), else ``OUTDOOR``."""
        return self.assessment.regime


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
        The segments between change points, for inspection.
    """

    events: tuple[QualityEvent, ...]
    pre_deployment: npt.NDArray[np.bool_]
    segments: tuple[SegmentRecord, ...]

    @property
    def transitions(self) -> tuple[DeploymentEvent, ...]:
        """The applied deployments and retrievals."""
        return tuple(e for e in self.events if isinstance(e, DeploymentEvent))

    @property
    def warnings(self) -> tuple[QualityEvent, ...]:
        """The warnings."""
        return tuple(e for e in self.events if e.severity is Severity.WARNING)

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
        Indoor-run search; built from ``settings`` when omitted.
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
        search = WindowedChangePoints(
            BinarySegmentation(cp.penalty_factor, cp.min_segment_s, cp.max_change_points),
            cp.window_s,
            cp.stride_s,
            cp.min_segment_s,
            cp.variance_floors,
        )
        return RegimeSegmenter(
            search,
            RegimeClassifier(settings.regime),
            TransitionContrast(settings.contrast),
            BoundaryRefiner(cp.min_segment_s, cp.variance_floors),
            TransportTrimmer(settings.transport),
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
            without temperature are not used for detection, but are marked by their time.
        known_deployments : sequence of datetime, optional
            Known deployment times (timezone-aware, e.g. ``placement.from`` of the registry);
            they override detection near themselves (see :mod:`sivin.quality.timeline`).

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
        segments, runs = self._segmenter.split(
            samples.t_s[usable],
            samples.temp_c[usable],
            samples.rh_pct[usable] if rh_used else None,
        )
        intervals = [_interval(samples, usable, run) for run in runs if run.applied]
        unapplied = [_unapplied_warning(samples, usable, run) for run in runs]
        first_t = samples.timestamp(0) if len(samples) else None
        reconciled = KnownDeploymentReconciler(self._settings.known_tolerance_s).reconcile(
            intervals, known, first_t
        )
        indoor = indoor_mask(reconciled.intervals, samples.t_ns)
        indoor.setflags(write=False)
        events = sorted(
            (*reconciled.transitions, *reconciled.warnings, *(w for w in unapplied if w)),
            key=lambda event: event.t_utc,
        )
        logger.info(
            "Sensor %s: %d transition(s), %d warning(s), %d pre-deployment sample(s).",
            series.sensor_id,
            len(reconciled.transitions),
            len(events) - len(reconciled.transitions),
            int(indoor.sum()),
        )
        records = tuple(
            SegmentRecord(
                samples.timestamp(int(usable[s.start])),
                samples.timestamp(int(usable[s.end - 1])),
                s.end - s.start,
                s.assessment,
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


def _event(
    samples: SampleArrays, usable: npt.NDArray[np.intp], boundary: Boundary
) -> DeploymentEvent:
    verdict = boundary.verdict
    assert verdict is not None  # only confirmed boundaries become events
    return DeploymentEvent(
        kind=boundary.kind,
        t_utc=samples.timestamp(int(usable[boundary.position])),
        detail=verdict.describe(outdoor_first=boundary.kind is EventKind.RETRIEVAL),
        confidence=verdict.score,
        origin=ORIGIN,
    )


def _interval(
    samples: SampleArrays, usable: npt.NDArray[np.intp], run: IndoorRun
) -> IndoorInterval:
    assert run.deployment is not None  # applied runs always end with a deployment
    retrieval = None if run.retrieval is None else _event(samples, usable, run.retrieval)
    deployment = _event(samples, usable, run.deployment)
    start = None if retrieval is None else retrieval.t_utc
    return IndoorInterval(start, deployment.t_utc, retrieval, deployment)


def _unapplied_warning(
    samples: SampleArrays, usable: npt.NDArray[np.intp], run: IndoorRun
) -> QualityEvent | None:
    """A warning for a run with a confirmed boundary that is not applied, else ``None``."""
    if not run.partly_confirmed:
        return None
    confirmed = [b for b in (run.retrieval, run.deployment) if b is not None and b.confirmed]
    boundary = confirmed[0]
    if run.deployment is None:
        reason = "retrieval without a later redeployment; not applied"
    else:
        reason = f"only the {boundary.kind.value} of a possible indoor period is confirmed"
    verdict = boundary.verdict
    detail = (
        reason
        if verdict is None
        else f"{reason}: {verdict.describe(boundary.kind is EventKind.RETRIEVAL)}"
    )
    return QualityEvent(
        kind=EventKind.UNCONFIRMED_TRANSITION,
        t_utc=samples.timestamp(int(usable[boundary.position])),
        detail=detail,
        severity=Severity.WARNING,
        confidence=None if verdict is None else verdict.score,
        origin=ORIGIN,
    )


def _aware_utc(value: datetime | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tz is None:
        raise ValueError(f"Known deployment times must be timezone-aware, got {value!r}.")
    return timestamp.tz_convert("UTC")
