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
5. hands the result to the policy of its :class:`DetectorMode`:

   * ``advisory`` (default since the owner decision of 2026-10-05): the off-site log
     (MIGRATION_PLAN §2.8) is the source of truth for ``PRE_DEPLOYMENT``. The detector sets
     **no flags** and reports every detected indoor period that the log does not cover as an
     ``unlogged_off_site`` warning ("possible unlogged off-site period");
   * ``enforce`` (the WP-1.5 behaviour): every sample recorded while indoors gets
     ``PRE_DEPLOYMENT`` and the transitions are reported as events.

Guiding principle: when the evidence is not clear, the detector warns and does not exclude data.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Final

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
from sivin.quality.events import DeploymentEvent, EventKind, EventSource, QualityEvent, Severity
from sivin.quality.regime import IndoorAssessment, Regime, RegimeClassifier, RegimeSettings
from sivin.quality.samples import S_PER_DAY, S_PER_H, SampleArrays
from sivin.quality.segmentation import Boundary, IndoorRun, RegimeSegmenter
from sivin.quality.timeline import (
    ORIGIN,
    IndoorInterval,
    KnownDeploymentReconciler,
    Reconciliation,
    indoor_mask,
)
from sivin.quality.windows import WindowedChangePoints
from sivin.registry.offsite import OffSitePeriod

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


class DetectorMode(StrEnum):
    """What :class:`DeploymentDetector` does with what it finds."""

    ADVISORY = "advisory"
    """Warn about detected indoor periods the off-site log does not cover; set no flags."""
    ENFORCE = "enforce"
    """Mark detected indoor samples ``PRE_DEPLOYMENT`` and report the transitions (WP-1.5)."""


class DeploymentSettings(BaseModel):
    """Settings of :class:`DeploymentDetector`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: DetectorMode = Field(
        DetectorMode.ADVISORY,
        description=(
            "'advisory' (default, owner decision 2026-10-05): only warnings, no flags; the "
            "off-site log is the source of truth for PRE_DEPLOYMENT. 'enforce': detected "
            "indoor samples get PRE_DEPLOYMENT (behaviour of WP-1.5). No unit."
        ),
    )
    log_tolerance_s: float = Field(
        6 * S_PER_H,
        ge=0,
        description=(
            "Advisory mode: a detected indoor period counts as covered by the off-site log if "
            "a logged period (touching periods merged) contains it after widening by this many "
            "seconds on both sides. Project default 6 h, the same as known_tolerance_s "
            "[to be tuned on real data]."
        ),
    )

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
        ``enforce`` mode: applied transitions (:class:`DeploymentEvent`) and
        ``deployment_mismatch`` / ``unconfirmed_transition`` warnings. ``advisory`` mode:
        ``unlogged_off_site`` and ``unconfirmed_transition`` warnings not covered by the
        off-site log. In time order.
    pre_deployment : numpy.ndarray of bool
        ``True`` for each row recorded while the sensor was indoors (read-only); all ``False``
        in ``advisory`` mode.
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
        return true_ranges(~self.pre_deployment)


def true_ranges(mask: npt.NDArray[np.bool_]) -> tuple[tuple[int, int], ...]:
    """Return the runs of consecutive ``True`` values of a mask.

    Parameters
    ----------
    mask : numpy.ndarray of bool
        One value per row.

    Returns
    -------
    tuple of (int, int)
        Half-open row ranges ``[start, stop)``, in order.
    """
    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    return tuple((int(a), int(b)) for a, b in zip(edges[::2], edges[1::2], strict=True))


@dataclass(frozen=True, slots=True)
class Detection:
    """What detection found, before the :class:`DetectorMode` policy decides what to report.

    Attributes
    ----------
    reconciliation : Reconciliation
        Indoor intervals, transitions and warnings after applying known deployments.
    unapplied : tuple of QualityEvent
        ``unconfirmed_transition`` warnings of runs that were not applied.
    indoor : numpy.ndarray of bool
        ``True`` for each row inside an applied indoor interval.
    first_t_utc : pandas.Timestamp or None
        Time of the first row; ``None`` for an empty series.
    """

    reconciliation: Reconciliation
    unapplied: tuple[QualityEvent, ...]
    indoor: npt.NDArray[np.bool_]
    first_t_utc: pd.Timestamp | None


class DetectionPolicy(ABC):
    """Turn a :class:`Detection` into reported events and the ``PRE_DEPLOYMENT`` mask.

    One subclass per :class:`DetectorMode`, registered with :func:`register_policy`.

    Parameters
    ----------
    settings : DeploymentSettings
        Detector settings.
    """

    mode: ClassVar[DetectorMode]

    def __init__(self, settings: DeploymentSettings) -> None:
        self._settings = settings

    @abstractmethod
    def resolve(
        self, detection: Detection, logged: Sequence[OffSitePeriod]
    ) -> tuple[tuple[QualityEvent, ...], npt.NDArray[np.bool_]]:
        """Decide what to report.

        Parameters
        ----------
        detection : Detection
            What detection found.
        logged : sequence of OffSitePeriod
            The sensor's periods from the off-site log.

        Returns
        -------
        tuple
            ``(events, pre_deployment)``: the events in any order and one bool per row.
        """


_POLICIES: Final[dict[DetectorMode, type[DetectionPolicy]]] = {}
"""Policy class per mode; filled by :func:`register_policy` when this module is imported."""


def register_policy[P: type[DetectionPolicy]](cls: P) -> P:
    """Register a :class:`DetectionPolicy` for its ``mode``; use as a class decorator.

    Parameters
    ----------
    cls : type[DetectionPolicy]
        The policy class.

    Returns
    -------
    type[DetectionPolicy]
        The class unchanged.

    Raises
    ------
    ValueError
        If a policy for the mode is already registered.
    """
    if cls.mode in _POLICIES:
        raise ValueError(f"A detection policy for mode {cls.mode!r} is already registered.")
    _POLICIES[cls.mode] = cls
    return cls


@register_policy
class EnforcePolicy(DetectionPolicy):
    """Mark indoor rows ``PRE_DEPLOYMENT``; report transitions and all warnings (WP-1.5)."""

    mode = DetectorMode.ENFORCE

    def resolve(
        self, detection: Detection, logged: Sequence[OffSitePeriod]
    ) -> tuple[tuple[QualityEvent, ...], npt.NDArray[np.bool_]]:
        """Report everything and flag every detected indoor row (see :class:`DetectionPolicy`).

        The off-site log is not consulted.
        """
        reconciled = detection.reconciliation
        events = (*reconciled.transitions, *reconciled.warnings, *detection.unapplied)
        return events, detection.indoor


@register_policy
class AdvisoryPolicy(DetectionPolicy):
    """Warn about indoor periods the off-site log does not cover; flag nothing.

    Every applied indoor interval not covered by the log becomes an ``unlogged_off_site``
    warning; ``unconfirmed_transition`` warnings are kept unless their time is covered.
    Transitions and ``deployment_mismatch`` warnings are not reported: they describe flags
    that this mode does not set.
    """

    mode = DetectorMode.ADVISORY

    def resolve(
        self, detection: Detection, logged: Sequence[OffSitePeriod]
    ) -> tuple[tuple[QualityEvent, ...], npt.NDArray[np.bool_]]:
        """Report uncovered indoor periods as warnings (see :class:`DetectionPolicy`)."""
        coverage = LoggedCoverage(logged, self._settings.log_tolerance_s)
        warnings: list[QualityEvent] = []
        for interval in detection.reconciliation.intervals:
            start = interval.start_utc if interval.start_utc is not None else detection.first_t_utc
            if start is None or coverage.covers(start, interval.end_utc):
                continue
            warnings.append(_unlogged_warning(interval, start))
        warnings += [
            event for event in detection.unapplied if not coverage.covers(event.t_utc, event.t_utc)
        ]
        return tuple(warnings), np.zeros_like(detection.indoor)


class LoggedCoverage:
    """Time spans covered by logged off-site periods, widened by a tolerance.

    Periods that touch or overlap after widening are merged, so a stay logged as two
    consecutive entries (e.g. transport, then office) covers a detection spanning both.

    Parameters
    ----------
    periods : sequence of OffSitePeriod
        The logged periods of one sensor.
    tolerance_s : float
        Widening on both sides in seconds.
    """

    __slots__ = ("_spans",)

    def __init__(self, periods: Sequence[OffSitePeriod], tolerance_s: float) -> None:
        tolerance = pd.Timedelta(seconds=tolerance_s)
        spans: list[tuple[pd.Timestamp, pd.Timestamp | None]] = []
        for period in sorted(periods, key=lambda p: p.from_utc):
            start = period.start_ts - tolerance
            end = None if period.end_ts is None else period.end_ts + tolerance
            if spans and (spans[-1][1] is None or start <= spans[-1][1]):
                previous_end = spans[-1][1]
                merged = None if end is None or previous_end is None else max(previous_end, end)
                spans[-1] = (spans[-1][0], merged)
            else:
                spans.append((start, end))
        self._spans = tuple(spans)

    def covers(self, start: pd.Timestamp, end: pd.Timestamp) -> bool:
        """Tell whether one widened span contains ``[start, end]``.

        Parameters
        ----------
        start, end : pandas.Timestamp
            Timezone-aware bounds.

        Returns
        -------
        bool
            ``True`` if covered.
        """
        return any(low <= start and (high is None or end <= high) for low, high in self._spans)


def _unlogged_warning(interval: IndoorInterval, start: pd.Timestamp) -> QualityEvent:
    """The advisory warning for one detected indoor interval missing in the log."""
    deployment = interval.deployment
    return QualityEvent(
        kind=EventKind.UNLOGGED_OFF_SITE,
        t_utc=start,
        end_utc=interval.end_utc,
        detail=(
            f"possible unlogged off-site period {_minutes(start)} - "
            f"{_minutes(interval.end_utc)} UTC ({deployment.detail}); if the sensor was not "
            "in the vineyard, add the period to sensors/offsite_log.yaml"
        ),
        severity=Severity.WARNING,
        source=EventSource.DETECTED,
        confidence=deployment.confidence,
        origin=ORIGIN,
    )


def _minutes(t_utc: pd.Timestamp) -> str:
    """Format a UTC time as ``YYYY-MM-DD HH:MM``."""
    return str(t_utc.tz_convert("UTC").strftime("%Y-%m-%d %H:%M"))


class DeploymentDetector:
    """Detect deployments and retrievals and report them per its mode (module docstring).

    Parameters
    ----------
    settings : DeploymentSettings, optional
        Settings; defaults when omitted (``advisory`` mode).
    segmenter : RegimeSegmenter, optional
        Indoor-run search; built from ``settings`` when omitted.
    policy : DetectionPolicy, optional
        What to report; the policy registered for ``settings.mode`` when omitted.
    """

    __slots__ = ("_policy", "_segmenter", "_settings")

    def __init__(
        self,
        settings: DeploymentSettings | None = None,
        segmenter: RegimeSegmenter | None = None,
        policy: DetectionPolicy | None = None,
    ) -> None:
        self._settings = settings or DeploymentSettings()
        self._segmenter = segmenter or self._default_segmenter(self._settings)
        self._policy = policy or _POLICIES[self._settings.mode](self._settings)

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
        logged_off_site: Sequence[OffSitePeriod] = (),
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
        logged_off_site : sequence of OffSitePeriod, optional
            The sensor's periods from the off-site log; in ``advisory`` mode a detected indoor
            period they cover raises no warning.

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
        detection = Detection(
            reconciliation=reconciled,
            unapplied=tuple(w for w in unapplied if w),
            indoor=indoor_mask(reconciled.intervals, samples.t_ns),
            first_t_utc=first_t,
        )
        reported, pre_deployment = self._policy.resolve(detection, logged_off_site)
        pre_deployment = np.array(pre_deployment, dtype=np.bool_)
        pre_deployment.setflags(write=False)
        events = sorted(reported, key=lambda event: event.t_utc)
        logger.info(
            "Sensor %s (%s mode): %d indoor interval(s) detected, %d event(s), "
            "%d pre-deployment sample(s).",
            series.sensor_id,
            self._policy.mode.value,
            len(reconciled.intervals),
            len(events),
            int(pre_deployment.sum()),
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
        return DeploymentResult(tuple(events), pre_deployment, records)

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
