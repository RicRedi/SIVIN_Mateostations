"""Events reported by quality control: gaps, steps, deployments and warnings.

Flags (:class:`~sivin.core.flags.QcFlag`) describe single samples; events describe something
that happened at a point in time (a deployment, a gap, a level step) and end up in
``data/derived/events/<sensor_id>.json`` and as markers in the web charts (MIGRATION_PLAN §2.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import pandas as pd


class EventKind(StrEnum):
    """What an event reports.

    The first three values are the transition types of MIGRATION_PLAN §2.7; their strings are
    the ``type`` values of the site contract (§2.6).
    """

    DEPLOYMENT = "deployment"
    """The sensor was carried from indoors (office, transport) into the vineyard."""
    RETRIEVAL = "retrieval"
    """The sensor was brought back indoors (e.g. for service)."""
    STEP = "step"
    """A sudden persistent level shift that is not a change of regime."""
    GAP = "gap"
    """No sample for longer than the gap threshold."""
    IRREGULAR_SAMPLING = "irregular_sampling"
    """Sampling intervals that deviate from the expected interval."""
    NON_POSITIVE_INTERVAL = "non_positive_interval"
    """Two samples with the same or decreasing timestamps."""
    DEPLOYMENT_MISMATCH = "deployment_mismatch"
    """Detected and known (registry) deployment times disagree."""
    UNCONFIRMED_TRANSITION = "unconfirmed_transition"
    """A possible indoor period that is not applied because the evidence is incomplete."""


TRANSITION_KINDS: Final = frozenset({EventKind.DEPLOYMENT, EventKind.RETRIEVAL, EventKind.STEP})
"""Event kinds a :class:`DeploymentEvent` may have."""


class Severity(StrEnum):
    """How much attention an event needs."""

    INFO = "info"
    WARNING = "warning"


class EventSource(StrEnum):
    """Where an event comes from (``source`` in the site contract, MIGRATION_PLAN §2.6)."""

    DETECTED = "detected"
    REGISTRY = "registry"


@dataclass(frozen=True, slots=True)
class QualityEvent:
    """Something quality control found at a point in time.

    Attributes
    ----------
    kind : EventKind
        What the event reports.
    t_utc : pandas.Timestamp
        When it happened (UTC). For an interval (a gap) the start.
    detail : str
        Human-readable description with numbers and units.
    severity : Severity
        ``INFO`` or ``WARNING``.
    source : EventSource
        ``DETECTED`` from the data or taken from the sensor ``REGISTRY``.
    confidence : float or None
        Confidence 0-1 (dimensionless) where the producer defines one.
    end_utc : pandas.Timestamp or None
        End of the interval (UTC) for interval events such as gaps.
    origin : str
        Name of the check or detector that produced the event.

    Raises
    ------
    ValueError
        If a timestamp is not timezone-aware, ``end_utc`` precedes ``t_utc`` or the
        confidence is outside 0-1.
    """

    kind: EventKind
    t_utc: pd.Timestamp
    detail: str
    severity: Severity = Severity.INFO
    source: EventSource = EventSource.DETECTED
    confidence: float | None = None
    end_utc: pd.Timestamp | None = None
    origin: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "t_utc", _utc(self.t_utc, "t_utc"))
        if self.end_utc is not None:
            end = _utc(self.end_utc, "end_utc")
            if end < self.t_utc:
                raise ValueError(f"end_utc {end} precedes t_utc {self.t_utc}.")
            object.__setattr__(self, "end_utc", end)
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be within 0-1, got {self.confidence}.")


@dataclass(frozen=True, slots=True)
class DeploymentEvent(QualityEvent):
    """A transition of the sensor between indoors and the vineyard (MIGRATION_PLAN §2.7).

    Same fields as :class:`QualityEvent`; ``kind`` must be one of :data:`TRANSITION_KINDS` and
    ``confidence`` is required.

    Raises
    ------
    ValueError
        If ``kind`` is not a transition kind or ``confidence`` is missing.
    """

    def __post_init__(self) -> None:
        if self.kind not in TRANSITION_KINDS:
            raise ValueError(f"A DeploymentEvent cannot have kind {self.kind!r}.")
        if self.confidence is None:
            raise ValueError("A DeploymentEvent needs a confidence.")
        QualityEvent.__post_init__(self)

    @property
    def type(self) -> EventKind:
        """The transition type (``deployment``, ``retrieval`` or ``step``)."""
        return self.kind


def _utc(value: pd.Timestamp, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tz is None:
        raise ValueError(f"{name} must be timezone-aware, got {value!r}.")
    return timestamp.tz_convert("UTC")
