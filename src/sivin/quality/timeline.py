"""Indoor intervals: reconcile detected intervals with known deployment times.

Detection produces **indoor intervals**: the office stay before the first deployment
(``start_utc`` is ``None``) and service visits bracketed by a confirmed retrieval and a
confirmed redeployment. Known deployment times (``placement.from`` of the sensor registry,
MIGRATION_PLAN §2.4) override detection only near themselves. Guiding principle: when in doubt,
do not exclude data. :class:`KnownDeploymentReconciler` applies these rules:

1. a detected deployment within the tolerance of a known time is moved to the known time
   (source ``registry``, confidence 1); if the known time is later, the samples in between
   (classified outdoor by detection) become ``PRE_DEPLOYMENT`` and a warning names the
   excluded duration;
2. a detected deployment with no known time within the tolerance is still applied, with a
   ``deployment_mismatch`` warning (e.g. a service visit missing in the registry);
3. a known time *inside* the detected office stay before the first deployment ends that stay
   at the known time (data after a known deployment are not ``PRE_DEPLOYMENT``), with a
   warning; a known time inside a detected service visit keeps the visit, with a warning;
4. a known time not matched by any detected deployment becomes a ``deployment`` event from the
   registry without flags. Only the *first* known time warns, and only if data exist before it
   (they look like vineyard data and are not flagged); a later known time follows an earlier
   placement and is a relocation (no warning).

Every sample inside an indoor interval gets ``PRE_DEPLOYMENT``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.quality.events import (
    DeploymentEvent,
    EventKind,
    EventSource,
    QualityEvent,
    Severity,
)
from sivin.quality.samples import S_PER_H

logger = logging.getLogger(__name__)

ORIGIN = "deployment"
"""``origin`` of the events produced by deployment detection."""


@dataclass(frozen=True, slots=True)
class IndoorInterval:
    """A period during which the sensor was indoors.

    Attributes
    ----------
    start_utc : pandas.Timestamp or None
        The retrieval; ``None`` for the office stay at the start of the data.
    end_utc : pandas.Timestamp
        The (re)deployment; samples from this time on are outdoors.
    retrieval : DeploymentEvent or None
        Event at ``start_utc``.
    deployment : DeploymentEvent
        Event at ``end_utc``.
    """

    start_utc: pd.Timestamp | None
    end_utc: pd.Timestamp
    retrieval: DeploymentEvent | None
    deployment: DeploymentEvent

    def contains(self, t_utc: pd.Timestamp) -> bool:
        """Tell whether ``t_utc`` lies strictly inside the interval."""
        return (self.start_utc is None or t_utc > self.start_utc) and t_utc < self.end_utc

    @property
    def events(self) -> tuple[DeploymentEvent, ...]:
        """The retrieval (if any) and the deployment."""
        return (self.deployment,) if self.retrieval is None else (self.retrieval, self.deployment)


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Indoor intervals to apply, transition events and warnings.

    Attributes
    ----------
    intervals : tuple of IndoorInterval
        Intervals to apply, in time order.
    transitions : tuple of DeploymentEvent
        Retrievals and deployments (detected and from the registry), in time order.
    warnings : tuple of QualityEvent
        ``deployment_mismatch`` warnings.
    """

    intervals: tuple[IndoorInterval, ...]
    transitions: tuple[DeploymentEvent, ...]
    warnings: tuple[QualityEvent, ...]


class KnownDeploymentReconciler:
    """Apply known deployment times to detected intervals (rules in the module docstring).

    Parameters
    ----------
    tolerance_s : float
        Largest distance in seconds between a detected and a known deployment that still
        counts as agreement.
    """

    __slots__ = ("_tolerance_s",)

    def __init__(self, tolerance_s: float) -> None:
        self._tolerance_s = tolerance_s

    def reconcile(
        self,
        detected: Sequence[IndoorInterval],
        known_utc: Sequence[pd.Timestamp],
        first_sample_utc: pd.Timestamp | None,
    ) -> Reconciliation:
        """Reconcile detected indoor intervals with known deployment times.

        Parameters
        ----------
        detected : sequence of IndoorInterval
            Detected intervals.
        known_utc : sequence of pandas.Timestamp
            Known deployment times (UTC).
        first_sample_utc : pandas.Timestamp or None
            Time of the first sample (``None`` without data).

        Returns
        -------
        Reconciliation
            Intervals, events and warnings.
        """
        intervals = sorted(detected, key=_interval_end)
        if not known_utc:
            detected_events = [e for interval in intervals for e in interval.events]
            return Reconciliation(tuple(intervals), tuple(sorted(detected_events, key=_time)), ())
        known = sorted({pd.Timestamp(k).tz_convert("UTC") for k in known_utc})
        used: set[pd.Timestamp] = set()
        warnings: list[QualityEvent] = []
        applied = [self._apply(interval, known, used, warnings) for interval in intervals]
        events: list[DeploymentEvent] = [e for interval in applied for e in interval.events]
        for known_t in known:
            if known_t in used:
                continue
            first = known_t == known[0]
            events.append(_registry_event(known_t, "known relocation" if not first else None))
            if first and first_sample_utc is not None and first_sample_utc < known_t:
                warnings.append(
                    _warning(
                        known_t,
                        "no indoor period detected before the first known deployment; the "
                        "earlier data look like vineyard data and are not flagged",
                        EventSource.REGISTRY,
                    )
                )
        return Reconciliation(
            tuple(applied), tuple(sorted(events, key=_time)), tuple(sorted(warnings, key=_time))
        )

    def _apply(
        self,
        interval: IndoorInterval,
        known: list[pd.Timestamp],
        used: set[pd.Timestamp],
        warnings: list[QualityEvent],
    ) -> IndoorInterval:
        detected = interval.deployment
        near = [k for k in known if k not in used and _distance_s(detected, k) <= self._tolerance_s]
        if near:
            known_t = min(near, key=lambda k: _distance_s(detected, k))
            used.add(known_t)
            offset_h = (detected.t_utc - known_t).total_seconds() / S_PER_H
            detail = f"detected {offset_h:+.2f} h from it: {detected.detail}"
            interval = replace(
                interval, end_utc=known_t, deployment=_registry_event(known_t, detail)
            )
            if known_t > detected.t_utc:
                warnings.append(
                    _warning(
                        known_t,
                        f"known deployment {-offset_h:.2f} h after the detected one: "
                        f"{-offset_h:.2f} h of data classified as outdoor become "
                        "PRE_DEPLOYMENT (registry is ground truth)",
                        EventSource.REGISTRY,
                    )
                )
        else:
            what = "service visit" if interval.retrieval is not None else "deployment"
            warnings.append(
                _warning(
                    detected.t_utc,
                    f"detected {what} applied, but no known deployment within the tolerance",
                    EventSource.DETECTED,
                )
            )
        inside = [k for k in known if k not in used and interval.contains(k)]
        if not inside:
            return interval
        used.update(inside)
        if interval.start_utc is not None:
            warnings += [
                _warning(
                    k,
                    "known deployment inside a detected service visit; visit kept",
                    EventSource.REGISTRY,
                )
                for k in inside
            ]
            return interval
        known_t = inside[0]
        warnings.append(
            _warning(
                known_t,
                f"detected indoor period lasts until {interval.end_utc.isoformat()}; data from "
                "the known deployment on are not flagged",
                EventSource.REGISTRY,
            )
        )
        return replace(interval, end_utc=known_t, deployment=_registry_event(known_t, None))


def indoor_mask(
    intervals: Sequence[IndoorInterval], t_ns: npt.NDArray[np.int64]
) -> npt.NDArray[np.bool_]:
    """Tell for each sample time whether it lies in an indoor interval.

    Parameters
    ----------
    intervals : sequence of IndoorInterval
        The intervals.
    t_ns : numpy.ndarray of int
        Sample times in nanoseconds since the Unix epoch (UTC), increasing.

    Returns
    -------
    numpy.ndarray of bool
        ``True`` inside ``[start_utc, end_utc)``.
    """
    indoor = np.zeros(t_ns.shape, dtype=np.bool_)
    for interval in intervals:
        start = (
            0
            if interval.start_utc is None
            else int(np.searchsorted(t_ns, interval.start_utc.value, side="left"))
        )
        end = int(np.searchsorted(t_ns, interval.end_utc.value, side="left"))
        indoor[start:end] = True
    return indoor


def _time(event: QualityEvent) -> pd.Timestamp:
    return event.t_utc


def _interval_end(interval: IndoorInterval) -> pd.Timestamp:
    return interval.end_utc


def _distance_s(event: QualityEvent, t_utc: pd.Timestamp) -> float:
    return abs((event.t_utc - t_utc).total_seconds())


def _registry_event(known_t: pd.Timestamp, detail: str | None) -> DeploymentEvent:
    text = "known deployment (sensor registry)"
    if detail:
        text += f"; {detail}"
    return DeploymentEvent(
        kind=EventKind.DEPLOYMENT,
        t_utc=known_t,
        detail=text,
        source=EventSource.REGISTRY,
        confidence=1.0,
        origin=ORIGIN,
    )


def _warning(t_utc: pd.Timestamp, detail: str, source: EventSource) -> QualityEvent:
    return QualityEvent(
        kind=EventKind.DEPLOYMENT_MISMATCH,
        t_utc=t_utc,
        detail=detail,
        severity=Severity.WARNING,
        source=source,
        origin=ORIGIN,
    )
