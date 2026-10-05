"""Mapping of quality-control events to the ``events/<sensor_id>.json`` entries of the site.

Quality control reports many event kinds (:class:`~sivin.quality.events.EventKind`); the site
publishes those worth a marker on the chart (``site.events``). Each published kind keeps its
string as the contract ``type``. Its *shape* decides the fields:

* **point** (``deployment``, ``retrieval``, ``step``, ``unconfirmed_transition``): ``type``,
  ``t``, ``source``, ``confidence``, ``detail``;
* **interval** (every other kind, e.g. ``off_site``, ``low_battery``, ``unlogged_off_site``):
  additionally ``t_end``, the end in Unix seconds, ``null`` while an ``off_site`` period is open.

The table is in ``docs/site.md``.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Final

from sivin.quality.events import EventKind, QualityEvent
from sivin.site.columns import CONFIDENCE_DECIMALS, rounded_value, unix_second

POINT_KINDS: Final = frozenset(
    {
        EventKind.DEPLOYMENT,
        EventKind.RETRIEVAL,
        EventKind.STEP,
        EventKind.UNCONFIRMED_TRANSITION,
    }
)
"""Kinds published as point events (no ``t_end``); all others are intervals."""


class SiteEventMapping:
    """Turn QC events into contract entries, keeping only the published kinds.

    Parameters
    ----------
    published : collection of EventKind
        The kinds to publish (``site.events``).
    """

    __slots__ = ("_published",)

    def __init__(self, published: Collection[EventKind]) -> None:
        self._published = frozenset(published)

    def entries(self, events: Collection[QualityEvent]) -> list[dict[str, object]]:
        """Return the entries of the published events, in the given (time) order.

        Parameters
        ----------
        events : collection of QualityEvent
            The QC events of one sensor.

        Returns
        -------
        list of dict
            One contract entry per published event.
        """
        return [self.entry(event) for event in events if event.kind in self._published]

    @staticmethod
    def entry(event: QualityEvent) -> dict[str, object]:
        """Return the contract entry of one event.

        Parameters
        ----------
        event : QualityEvent
            The event.

        Returns
        -------
        dict
            ``type``, ``t`` (Unix s), ``t_end`` (Unix s or ``null``, intervals only),
            ``source``, ``confidence`` (0-1 or ``null``), ``detail``.
        """
        entry: dict[str, object] = {"type": str(event.kind), "t": unix_second(event.t_utc)}
        if event.kind not in POINT_KINDS:
            entry["t_end"] = None if event.end_utc is None else unix_second(event.end_utc)
        entry["source"] = str(event.source)
        entry["confidence"] = rounded_value(event.confidence, CONFIDENCE_DECIMALS)
        entry["detail"] = event.detail or None
        return entry
