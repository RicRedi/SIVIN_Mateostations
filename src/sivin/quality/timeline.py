"""Deployment timeline: reconcile detected transitions with known deployments, mark indoor time.

Known deployment times (``placement.from`` of the sensor registry, MIGRATION_PLAN §2.4) are
ground truth. :class:`KnownDeploymentReconciler` applies these rules:

1. every known time is a ``deployment`` event with source ``registry`` and confidence 1;
2. a detected deployment within the tolerance of a known time is replaced by it;
3. a detected deployment farther than the tolerance from every known time is not applied and
   produces a ``deployment_mismatch`` warning;
4. a known time without a detected deployment within the tolerance produces a warning too;
5. detected retrievals are kept (the registry interface carries no retrieval times);
6. before the first known deployment the sensor counts as indoors (unless that deployment
   precedes the data, in which case the series starts outdoors).

:class:`DeploymentTimeline` then walks the transitions in time order: a deployment switches the
state to outdoor, a retrieval to indoor (a transition into the current state changes nothing).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

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
class Reconciliation:
    """Transitions to apply and the warnings raised on the way.

    Attributes
    ----------
    transitions : tuple of DeploymentEvent
        Deployments and retrievals to apply, in time order.
    warnings : tuple of QualityEvent
        ``deployment_mismatch`` warnings.
    """

    transitions: tuple[DeploymentEvent, ...]
    warnings: tuple[QualityEvent, ...]


class KnownDeploymentReconciler:
    """Apply known deployment times to detected transitions (rules in the module docstring).

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
        self, detected: Sequence[DeploymentEvent], known_utc: Sequence[pd.Timestamp]
    ) -> Reconciliation:
        """Reconcile detected transitions with known deployment times.

        Parameters
        ----------
        detected : sequence of DeploymentEvent
            Detected deployments and retrievals.
        known_utc : sequence of pandas.Timestamp
            Known deployment times (timezone-aware).

        Returns
        -------
        Reconciliation
            Transitions to apply and warnings. Without known times, ``detected`` unchanged.
        """
        if not known_utc:
            return Reconciliation(tuple(sorted(detected, key=_time)), ())
        known = sorted(pd.Timestamp(k).tz_convert("UTC") for k in known_utc)
        deployments = [e for e in detected if e.kind is EventKind.DEPLOYMENT]
        retrievals = [e for e in detected if e.kind is EventKind.RETRIEVAL]
        unmatched = list(deployments)
        transitions: list[DeploymentEvent] = list(retrievals)
        warnings: list[QualityEvent] = []
        for known_t in known:
            match = _nearest(unmatched, known_t)
            if match is not None and _distance_s(match, known_t) <= self._tolerance_s:
                unmatched.remove(match)
            else:
                warnings.append(_missing_detection_warning(known_t, match))
            transitions.append(_known_deployment(known_t, match, self._tolerance_s))
        warnings += [_unconfirmed_detection_warning(event, known) for event in unmatched]
        return Reconciliation(
            tuple(sorted(transitions, key=_time)), tuple(sorted(warnings, key=_time))
        )


class DeploymentTimeline:
    """Indoor/outdoor state over time from an ordered list of transitions.

    Parameters
    ----------
    transitions : sequence of DeploymentEvent
        Deployments and retrievals.
    starts_indoor : bool
        State before the first transition.
    """

    __slots__ = ("_starts_indoor", "_transitions")

    def __init__(self, transitions: Sequence[DeploymentEvent], starts_indoor: bool) -> None:
        self._transitions = tuple(sorted(transitions, key=_time))
        self._starts_indoor = starts_indoor

    def indoor_mask(self, t_ns: npt.NDArray[np.int64]) -> npt.NDArray[np.bool_]:
        """Tell for each sample time whether the sensor was indoors.

        Parameters
        ----------
        t_ns : numpy.ndarray of int
            Sample times in nanoseconds since the Unix epoch (UTC).

        Returns
        -------
        numpy.ndarray of bool
            ``True`` while indoor. A transition at time ``T`` applies from ``T`` on.
        """
        indoor = np.full(t_ns.shape, self._starts_indoor, dtype=np.bool_)
        for event in self._transitions:
            from_position = int(np.searchsorted(t_ns, event.t_utc.value, side="left"))
            indoor[from_position:] = event.kind is EventKind.RETRIEVAL
        return indoor


def _time(event: QualityEvent) -> pd.Timestamp:
    return event.t_utc


def _distance_s(event: QualityEvent, known_t: pd.Timestamp) -> float:
    return abs((event.t_utc - known_t).total_seconds())


def _nearest(events: Sequence[DeploymentEvent], known_t: pd.Timestamp) -> DeploymentEvent | None:
    if not events:
        return None
    return min(events, key=lambda event: _distance_s(event, known_t))


def _known_deployment(
    known_t: pd.Timestamp, nearest: DeploymentEvent | None, tolerance_s: float
) -> DeploymentEvent:
    detail = "known deployment (sensor registry)"
    if nearest is not None and _distance_s(nearest, known_t) <= tolerance_s:
        offset_h = (nearest.t_utc - known_t).total_seconds() / S_PER_H
        detail += f"; detected {offset_h:+.2f} h from it: {nearest.detail}"
    return DeploymentEvent(
        kind=EventKind.DEPLOYMENT,
        t_utc=known_t,
        detail=detail,
        source=EventSource.REGISTRY,
        confidence=1.0,
        origin=ORIGIN,
    )


def _missing_detection_warning(
    known_t: pd.Timestamp, nearest: DeploymentEvent | None
) -> QualityEvent:
    if nearest is None:
        found = "no deployment was detected"
    else:
        offset_h = (nearest.t_utc - known_t).total_seconds() / S_PER_H
        found = f"the nearest detected deployment is {offset_h:+.1f} h away"
    return QualityEvent(
        kind=EventKind.DEPLOYMENT_MISMATCH,
        t_utc=known_t,
        detail=f"known deployment not confirmed by the data: {found}",
        severity=Severity.WARNING,
        source=EventSource.REGISTRY,
        origin=ORIGIN,
    )


def _unconfirmed_detection_warning(
    event: DeploymentEvent, known: Sequence[pd.Timestamp]
) -> QualityEvent:
    offset_h = min(((event.t_utc - k).total_seconds() for k in known), key=abs) / S_PER_H
    return QualityEvent(
        kind=EventKind.DEPLOYMENT_MISMATCH,
        t_utc=event.t_utc,
        detail=(
            f"detected deployment ignored: no known deployment within tolerance "
            f"(nearest {offset_h:+.1f} h); {event.detail}"
        ),
        severity=Severity.WARNING,
        confidence=event.confidence,
        origin=ORIGIN,
    )
