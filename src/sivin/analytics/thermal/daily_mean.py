"""Definitions of the daily mean temperature used by the thermal indices.

The literature on growing degree-days computes the daily mean as ``(T_max + T_min) / 2``
(the convention of the climatological station networks the indices were defined on), whereas
:class:`~sivin.core.daily.DailyWeather` provides the arithmetic mean of all valid samples. Each
definition is a small class registered in :data:`daily_mean_registry`; an index parameter
selects one by name. A new definition is a new registered class.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import ClassVar, Final

import pandas as pd

from sivin.core.daily import DailyWeather

logger = logging.getLogger(__name__)


class DailyMeanDefinition(ABC):
    """How one daily mean temperature in °C is derived from daily aggregates."""

    name: ClassVar[str]

    @abstractmethod
    def mean_temp_c(self, days: DailyWeather) -> pd.Series:
        """Return the daily mean temperature of every day.

        Parameters
        ----------
        days : DailyWeather
            Daily aggregates (usually only complete days).

        Returns
        -------
        pandas.Series
            Daily mean temperature in °C, indexed by local date.
        """


class DailyMeanRegistry:
    """Registry of :class:`DailyMeanDefinition` classes keyed by their ``name``.

    Like the index registry it is filled by class decorators on import and never changed
    afterwards (MIGRATION_PLAN §1.2, point 2).
    """

    __slots__ = ("_classes",)

    def __init__(self) -> None:
        self._classes: dict[str, type[DailyMeanDefinition]] = {}

    def register[C: type[DailyMeanDefinition]](self, cls: C) -> C:
        """Register a definition class; use as a class decorator.

        Parameters
        ----------
        cls : type[DailyMeanDefinition]
            The class to register under its ``name``.

        Returns
        -------
        type[DailyMeanDefinition]
            The class unchanged.

        Raises
        ------
        ValueError
            If the name is already registered.
        """
        if cls.name in self._classes:
            raise ValueError(f"Daily mean definition {cls.name!r} is already registered.")
        self._classes[cls.name] = cls
        return cls

    def create(self, name: str) -> DailyMeanDefinition:
        """Instantiate the definition registered under ``name``.

        Parameters
        ----------
        name : str
            Registered name, e.g. ``"minmax"``.

        Returns
        -------
        DailyMeanDefinition
            A new instance.

        Raises
        ------
        KeyError
            If the name is unknown.
        """
        try:
            return self._classes[name]()
        except KeyError:
            raise KeyError(
                f"Unknown daily mean definition {name!r}; known: {', '.join(self.names())}."
            ) from None

    def names(self) -> tuple[str, ...]:
        """Return the registered names, sorted.

        Returns
        -------
        tuple of str
            Sorted names.
        """
        return tuple(sorted(self._classes))

    def __contains__(self, name: object) -> bool:
        return name in self._classes


daily_mean_registry: Final = DailyMeanRegistry()
"""Registry of the daily mean definitions (filled on import of this module)."""


@daily_mean_registry.register
class MinMaxMean(DailyMeanDefinition):
    """Daily mean as ``(T_max + T_min) / 2`` in °C (Winkler convention).

    This is the convention of the growing degree-day literature (Amerine and Winkler, 1944;
    Winkler et al., 1974) and of the legacy ``vineyard_analyst.calculate_gdd``.
    """

    name = "minmax"

    def mean_temp_c(self, days: DailyWeather) -> pd.Series:
        """Return ``(temp_max + temp_min) / 2`` in °C per local date."""
        frame = days.frame
        return ((frame["temp_max"] + frame["temp_min"]) / 2.0).rename("mean_temp_c")


@daily_mean_registry.register
class SampleMean(DailyMeanDefinition):
    """Daily mean as the arithmetic mean of all valid samples of the day, in °C.

    This is ``DailyWeather.temp_mean`` and the mean the legacy
    ``vineyard_analyst.calculate_huglin_index`` used.
    """

    name = "sample_mean"

    def mean_temp_c(self, days: DailyWeather) -> pd.Series:
        """Return ``temp_mean`` in °C per local date."""
        return days.frame["temp_mean"].rename("mean_temp_c")


DEFAULT_DAILY_MEAN: Final = MinMaxMean.name
"""Default daily mean definition of all thermal indices (Winkler convention)."""
