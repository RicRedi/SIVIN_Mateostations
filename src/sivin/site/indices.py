"""Climate index results for the site: the source protocol and the published entry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Protocol

from sivin.analytics.base import IndexResult
from sivin.core.ids import SensorId
from sivin.quality.pipeline import QualityResult
from sivin.site.columns import INDEX_DECIMALS, SHARE_DECIMALS, rounded_value
from sivin.site.labels import IndexSpec

ENTRY_OK: Final = "ok"
"""``status`` of an index entry computed from data."""

ENTRY_NO_DATA: Final = "no_data"
"""``status`` of an index entry without a single complete day in its period (coverage 0)."""

NO_DATA_DETAIL: Final = "no data"
"""``detail`` of a :data:`ENTRY_NO_DATA` entry."""


def index_entry(result: IndexResult) -> dict[str, Any]:
    """Return the published entry of one index result (``indices/<season>.json``).

    Nothing is published that the data do not support (WP-3.2 review): with ``coverage`` 0 (no
    complete day in the index period, e.g. a sensor off site the whole season) ``value`` and
    ``class`` are ``null`` and ``status`` is ``"no_data"``, whatever the index returned (the
    disease models return 0 and ``"low"`` without data). A ``class`` is published only for a
    ``complete`` result: a class of a partial sum or of a partial risk count would be misleading.

    Parameters
    ----------
    result : IndexResult
        The result.

    Returns
    -------
    dict
        ``value`` (rounded to 0.01 in the index unit, or ``null``), ``unit``, ``coverage``
        (0-1, rounded to 0.001), ``complete``, ``class`` (or ``null``), ``estimated``
        (``true`` when the index relies on a proxy, e.g. leaf wetness from humidity),
        ``status`` (``"ok"`` or ``"no_data"``) and, for ``"no_data"``, ``detail``.
    """
    coverage = rounded_value(result.coverage, SHARE_DECIMALS)
    no_data = result.coverage <= 0.0
    entry: dict[str, Any] = {
        "value": None if no_data else rounded_value(result.value, INDEX_DECIMALS),
        "unit": result.unit,
        "coverage": coverage,
        "complete": result.complete,
        "class": result.classification if result.complete and not no_data else None,
        "estimated": result.estimated,
        "status": ENTRY_NO_DATA if no_data else ENTRY_OK,
    }
    if no_data:
        entry["detail"] = NO_DATA_DETAIL
    return entry


@dataclass(frozen=True)
class IndexBatch:
    """Index results of several sensors for one season.

    Attributes
    ----------
    results : Mapping of SensorId to Mapping of str to IndexResult
        Results per sensor and index id; a sensor without data in the season window is absent.
    failures : tuple of str
        One message per sensor or index that failed.
    failed_sensors : frozenset of SensorId
        Sensors with at least one failed index (retried by the next build).
    """

    results: Mapping[SensorId, Mapping[str, IndexResult]] = field(default_factory=dict)
    failures: tuple[str, ...] = ()
    failed_sensors: frozenset[SensorId] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", MappingProxyType(dict(self.results)))


class IndexSource(Protocol):
    """Computes the configured climate indices (the indices service of :mod:`sivin.app`)."""

    def specs(self) -> tuple[IndexSpec, ...]:
        """Return the id and unit of every configured index, sorted by id.

        Returns
        -------
        tuple of IndexSpec
            The indices of the manifest.
        """
        ...

    def compute(self, season: int, checked: Mapping[SensorId, QualityResult]) -> IndexBatch:
        """Compute every configured index of one season for the given sensors.

        Parameters
        ----------
        season : int
            The season year.
        checked : Mapping of SensorId to QualityResult
            QC results over each sensor's whole record; only these sensors are computed.

        Returns
        -------
        IndexBatch
            Results and failures.
        """
        ...
