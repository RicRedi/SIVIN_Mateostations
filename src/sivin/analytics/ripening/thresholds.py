"""Threshold tests and threshold-based classes used by several indices."""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType
from typing import Final

import numpy as np
import numpy.typing as npt

from sivin.analytics.ripening.durations import FloatArray


class Comparison(StrEnum):
    """How a value is compared with a threshold."""

    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="

    def holds(self, values: npt.ArrayLike, limit: float) -> npt.NDArray[np.bool_]:
        """Compare values with a limit element-wise.

        Parameters
        ----------
        values : array_like of float
            Values to test (``NaN`` never satisfies a comparison).
        limit : float
            The threshold, in the unit of ``values``.

        Returns
        -------
        numpy.ndarray of bool
            ``values <op> limit``.
        """
        array = np.asarray(values, dtype=np.float64)
        return np.asarray(_OPERATORS[self](array, limit), dtype=np.bool_)


_OPERATORS: Final[Mapping[Comparison, Callable[[FloatArray, float], object]]] = MappingProxyType(
    {
        Comparison.LT: operator.lt,
        Comparison.LE: operator.le,
        Comparison.GT: operator.gt,
        Comparison.GE: operator.ge,
    }
)
"""The operator behind each :class:`Comparison` (read-only)."""


@dataclass(frozen=True, slots=True)
class Threshold:
    """A one-sided threshold test, e.g. ``T_max >= 30 °C``.

    Parameters
    ----------
    comparison : Comparison
        The operator.
    limit : float
        The threshold, in the unit of the tested values.
    """

    comparison: Comparison
    limit: float

    def holds(self, values: npt.ArrayLike) -> npt.NDArray[np.bool_]:
        """Test values against the threshold.

        Parameters
        ----------
        values : array_like of float
            Values in the unit of :attr:`limit`.

        Returns
        -------
        numpy.ndarray of bool
            ``True`` where the threshold condition holds.
        """
        return self.comparison.holds(values, self.limit)

    def __str__(self) -> str:
        return f"{self.comparison} {self.limit:g}"


@dataclass(frozen=True, slots=True)
class UpperBoundClasses:
    """Classes defined by increasing upper bounds, e.g. ``<= 12``, ``(12, 14]``, ``> 14``.

    A value belongs to the first class whose upper bound it does not exceed
    (``value <= bound``), or to ``top_label`` if it exceeds every bound.

    Parameters
    ----------
    bounds : tuple of (float, str)
        ``(upper_bound, label)`` pairs with strictly increasing bounds.
    top_label : str
        Label of values above the last bound.

    Raises
    ------
    ValueError
        If there are no bounds or they are not strictly increasing.
    """

    bounds: tuple[tuple[float, str], ...]
    top_label: str

    def __post_init__(self) -> None:
        limits = [bound for bound, _ in self.bounds]
        if not limits or any(b <= a for a, b in pairwise(limits)):
            raise ValueError(f"Class bounds must be non-empty and increasing, got {limits}.")

    def classify(self, value: float) -> str:
        """Return the label of the class a value falls into.

        Parameters
        ----------
        value : float
            The value, in the unit of the bounds.

        Returns
        -------
        str
            The class label.
        """
        for bound, label in self.bounds:
            if value <= bound:
                return label
        return self.top_label
