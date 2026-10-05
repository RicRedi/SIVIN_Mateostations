"""Extension point for climate indices: :class:`ClimateIndex`, its input, result and registry.

A new index is a new subclass of :class:`ClimateIndex` that registers itself::

    class HuglinParams(IndexParams):
        base_temp_c: float = Field(10.0, description="Base temperature in °C.")


    @index_registry.register
    class HuglinIndex(ClimateIndex[HuglinParams]):
        index_id = "huglin"
        unit = "°C·d"
        params_model = HuglinParams

        def compute(self, ctx: IndexContext) -> IndexResult: ...

The real indices are implemented in ``sivin.analytics.thermal``, ``.ripening`` and ``.disease``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Final, cast, overload

import pandas as pd
from pydantic import BaseModel, ConfigDict

from sivin.core.daily import DailyWeather
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries
from sivin.core.season import Season

logger = logging.getLogger(__name__)

DEFAULT_MIN_DAILY_COVERAGE: Final = 0.9
"""Share of a day (0-1) that valid samples must cover for the day to count as complete.

Project default, not taken from literature; to be tuned on real data
(``analytics.min_daily_coverage`` in the configuration).
"""

DEFAULT_MIN_SEASON_COVERAGE: Final = 0.9
"""Share (0-1) of the days of an index period that must be complete for a complete result.

Project default, not taken from literature; to be tuned on real data
(``analytics.min_season_coverage`` in the configuration).
"""


@dataclass(frozen=True, slots=True)
class IndexContext:
    """Everything an index may use to compute its value for one sensor and one year.

    Attributes
    ----------
    sensor_id : SensorId
        The sensor.
    year : int
        The season year the index is computed for.
    daily : DailyWeather
        Daily aggregates of the sensor (all available days, not only complete ones).
    series : MeasurementSeries
        Raw measurements, for indices that need sub-daily data (e.g. hours below 0 °C).
    latitude_deg : float or None
        Latitude of the sensor in degrees north, if known.
    elevation_m : float or None
        Elevation of the sensor in metres above sea level, if known.
    timezone : str
        IANA zone defining local calendar days.
    min_daily_coverage : float
        Coverage (0-1) a day needs to count as complete.
    min_season_coverage : float
        Share (0-1) of complete days in the index period needed for a complete result.
    exclude_mask : int
        :class:`~sivin.core.flags.QcFlag` bits that exclude a raw sample.
    """

    sensor_id: SensorId
    year: int
    daily: DailyWeather
    series: MeasurementSeries
    latitude_deg: float | None
    elevation_m: float | None
    timezone: str
    min_daily_coverage: float = DEFAULT_MIN_DAILY_COVERAGE
    min_season_coverage: float = DEFAULT_MIN_SEASON_COVERAGE
    exclude_mask: int = int(QcFlag.DEFAULT_EXCLUDE)


@dataclass(frozen=True)
class IndexResult:
    """Value of one index for one sensor and one season.

    Attributes
    ----------
    index_id : str
        Identifier of the index, e.g. ``"huglin"``.
    sensor_id : SensorId
        The sensor.
    year : int
        The season year.
    value : float or None
        The index value in :attr:`unit`; ``None`` if it cannot be computed.
    unit : str
        Unit of :attr:`value`, e.g. ``"°C·d"``.
    coverage : float
        Share (0-1) of complete days in the index period.
    complete : bool
        Whether the data are complete enough for the value to be representative.
    classification : str or None
        Class label, e.g. ``"temperate_warm"``, if the index defines classes.
    daily : pandas.Series or None
        Daily or cumulative curve indexed by local date, for indices that have one.
    details : Mapping
        Additional named numbers or labels (read-only).
    estimated : bool
        ``True`` if the index relies on a proxy (e.g. leaf wetness estimated from humidity).

    Raises
    ------
    ValueError
        If ``coverage`` is outside 0-1.
    """

    index_id: str
    sensor_id: SensorId
    year: int
    value: float | None
    unit: str
    coverage: float
    complete: bool
    classification: str | None = None
    daily: pd.Series | None = None
    details: Mapping[str, float | int | str] = field(default_factory=dict)
    estimated: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.coverage <= 1.0:
            raise ValueError(f"coverage must be within 0-1, got {self.coverage}.")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class SeasonDays:
    """Complete days of an index period, as selected by :meth:`ClimateIndex._season_days`.

    Attributes
    ----------
    days : DailyWeather
        The complete days inside the period.
    n_period_days : int
        Number of calendar days of the period.
    coverage : float
        ``len(days) / n_period_days``, 0-1.
    complete : bool
        ``coverage >= IndexContext.min_season_coverage``.
    """

    days: DailyWeather
    n_period_days: int
    coverage: float
    complete: bool


class IndexParams(BaseModel):
    """Base class of index parameter models: frozen, unknown keys rejected.

    Every field of a subclass must have ``Field(description=...)`` including its unit and the
    source of its default value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ClimateIndex[P: IndexParams](ABC):
    """Abstract climate index computed for one sensor and one season.

    Subclasses set the class variables, implement :meth:`compute` and register themselves
    with :data:`index_registry` (see the module docstring).

    Attributes
    ----------
    index_id : str
        Unique identifier, also the key in the registry and in the site data.
    unit : str
        Unit of the value.
    params_model : type[IndexParams]
        Pydantic model of the parameters; must be the type argument ``P``.

    Parameters
    ----------
    params : P, optional
        Parameters; defaults of :attr:`params_model` when omitted.

    Raises
    ------
    TypeError
        If ``params`` is not an instance of :attr:`params_model`.
    """

    index_id: ClassVar[str]
    unit: ClassVar[str]
    params_model: ClassVar[type[IndexParams]] = IndexParams

    def __init__(self, params: P | None = None) -> None:
        if params is None:
            params = cast(P, self.params_model())
        if not isinstance(params, self.params_model):
            raise TypeError(
                f"{type(self).__name__} expects {self.params_model.__name__}, "
                f"got {type(params).__name__}."
            )
        self._params: P = params

    @property
    def params(self) -> P:
        """The (immutable) parameters of this index."""
        return self._params

    @abstractmethod
    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the index.

        Parameters
        ----------
        ctx : IndexContext
            Data and metadata of one sensor and one season year.

        Returns
        -------
        IndexResult
            The value with its coverage and completeness.
        """

    def _season_days(self, ctx: IndexContext, season: Season) -> SeasonDays:
        """Select the complete days of ``season`` in ``ctx.year`` and measure coverage.

        Parameters
        ----------
        ctx : IndexContext
            Input of :meth:`compute`.
        season : Season
            The index period.

        Returns
        -------
        SeasonDays
            Complete days (``coverage >= ctx.min_daily_coverage``) within the period, and the
            share of the period they represent.
        """
        first, last = season.dates(ctx.year)
        days = ctx.daily.between(first, last).complete_days(ctx.min_daily_coverage)
        n_period_days = season.n_days(ctx.year)
        coverage = len(days) / n_period_days
        return SeasonDays(
            days=days,
            n_period_days=n_period_days,
            coverage=coverage,
            complete=coverage >= ctx.min_season_coverage,
        )


type IndexClass = type[ClimateIndex[Any]]
"""A concrete :class:`ClimateIndex` subclass."""


class IndexRegistry:
    """Registry of climate index classes, keyed by :attr:`ClimateIndex.index_id`.

    Registries are the one kind of module-level mutable state the project allows
    (MIGRATION_PLAN §1.2, point 2): they are filled by class decorators when the module that
    defines an index is imported, and never changed afterwards.
    """

    __slots__ = ("_classes",)

    def __init__(self) -> None:
        self._classes: dict[str, IndexClass] = {}

    @overload
    def register[C: IndexClass](self, target: C) -> C: ...

    @overload
    def register[C: IndexClass](self, target: str) -> Callable[[C], C]: ...

    def register[C: IndexClass](self, target: C | str) -> C | Callable[[C], C]:
        """Register an index class; use as a class decorator.

        Both ``@registry.register`` and ``@registry.register("huglin")`` are accepted; the
        key is always the class's ``index_id``, and the string form must equal it.

        Parameters
        ----------
        target : type[ClimateIndex] or str
            The class to register, or the expected ``index_id``.

        Returns
        -------
        type[ClimateIndex] or callable
            The class unchanged (or a decorator returning it).

        Raises
        ------
        ValueError
            If the ``index_id`` is already registered or differs from the given string.
        TypeError
            If the class is not a concrete :class:`ClimateIndex` with ``index_id`` and ``unit``.
        """
        if isinstance(target, str):
            expected_id = target

            def decorator(cls: C) -> C:
                if getattr(cls, "index_id", None) != expected_id:
                    raise ValueError(
                        f"{cls.__name__}.index_id is {getattr(cls, 'index_id', None)!r}, "
                        f"but it is registered as {expected_id!r}."
                    )
                return self._add(cls)

            return decorator
        return self._add(target)

    def create(self, index_id: str, params: Mapping[str, Any] | None = None) -> ClimateIndex[Any]:
        """Instantiate a registered index with validated parameters.

        Parameters
        ----------
        index_id : str
            Identifier of a registered index.
        params : Mapping, optional
            Raw parameter values (e.g. from the configuration); defaults when omitted.

        Returns
        -------
        ClimateIndex
            A new index instance.

        Raises
        ------
        KeyError
            If no index with this id is registered.
        pydantic.ValidationError
            If the parameters do not fit the index's parameter model.
        """
        cls = self.get(index_id)
        return cls(cls.params_model.model_validate(dict(params or {})))

    def get(self, index_id: str) -> IndexClass:
        """Return the class registered under ``index_id``.

        Parameters
        ----------
        index_id : str
            Identifier of a registered index.

        Returns
        -------
        type[ClimateIndex]
            The registered class.

        Raises
        ------
        KeyError
            If no index with this id is registered.
        """
        try:
            return self._classes[index_id]
        except KeyError:
            raise KeyError(
                f"Unknown index {index_id!r}; registered: {', '.join(self.ids()) or 'none'}."
            ) from None

    def ids(self) -> tuple[str, ...]:
        """Return the registered index ids, sorted.

        Returns
        -------
        tuple of str
            Sorted identifiers.
        """
        return tuple(sorted(self._classes))

    def __contains__(self, index_id: object) -> bool:
        return index_id in self._classes

    def __len__(self) -> int:
        return len(self._classes)

    def _add[C: IndexClass](self, cls: C) -> C:
        if not (isinstance(cls, type) and issubclass(cls, ClimateIndex)):
            raise TypeError(f"Only ClimateIndex subclasses can be registered, got {cls!r}.")
        if getattr(cls, "__abstractmethods__", None):
            raise TypeError(f"{cls.__name__} is abstract and cannot be registered.")
        index_id = getattr(cls, "index_id", None)
        if not isinstance(index_id, str) or not index_id:
            raise TypeError(f"{cls.__name__} must define a non-empty class variable 'index_id'.")
        if not isinstance(getattr(cls, "unit", None), str):
            raise TypeError(f"{cls.__name__} must define a class variable 'unit'.")
        if index_id in self._classes:
            raise ValueError(
                f"Index id {index_id!r} is already registered by "
                f"{self._classes[index_id].__qualname__}."
            )
        self._classes[index_id] = cls
        logger.debug("Registered climate index %r (%s).", index_id, cls.__qualname__)
        return cls


index_registry: Final = IndexRegistry()
"""The project-wide registry of climate indices (filled on import of the index modules)."""
