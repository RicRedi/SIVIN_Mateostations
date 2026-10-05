"""Climate index results for the site: the source protocol and the published entry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol

from sivin.analytics.base import IndexResult
from sivin.core.ids import SensorId
from sivin.quality.pipeline import QualityResult
from sivin.site.columns import INDEX_DECIMALS, SHARE_DECIMALS, rounded_value
from sivin.site.labels import IndexSpec


def index_entry(result: IndexResult) -> dict[str, Any]:
    """Return the published entry of one index result (``indices/<season>.json``).

    Parameters
    ----------
    result : IndexResult
        The result.

    Returns
    -------
    dict
        ``value`` (rounded to 0.01 in the index unit, or ``null``), ``unit``, ``coverage``
        (0-1, rounded to 0.001), ``complete``, ``class`` (or ``null``) and ``estimated``
        (``true`` when the index relies on a proxy, e.g. leaf wetness from humidity).
    """
    return {
        "value": rounded_value(result.value, INDEX_DECIMALS),
        "unit": result.unit,
        "coverage": rounded_value(result.coverage, SHARE_DECIMALS),
        "complete": result.complete,
        "class": result.classification,
        "estimated": result.estimated,
    }


@dataclass(frozen=True)
class IndexBatch:
    """Index results of several sensors for one season.

    Attributes
    ----------
    results : Mapping of SensorId to Mapping of str to IndexResult
        Results per sensor and index id; a sensor without data in the season window is absent.
    failures : tuple of str
        One message per sensor or index that failed.
    """

    results: Mapping[SensorId, Mapping[str, IndexResult]] = field(default_factory=dict)
    failures: tuple[str, ...] = ()

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
