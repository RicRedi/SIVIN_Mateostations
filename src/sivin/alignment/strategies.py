"""How one sensor's samples are mapped onto grid points (MIGRATION_PLAN §2.7).

:class:`AlignmentStrategy` is the extension point; implementations register themselves in
:data:`strategy_registry`. Every strategy works on a :class:`SampleSet`, which holds only the
*usable* samples of one variable of one sensor (not excluded by the QC mask, not ``NaN``), so
excluded and missing values can never be paired. All computations are vectorised with
:func:`numpy.searchsorted`; there is no Python loop over samples or grid points.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Final, Self, cast, get_args, get_origin

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from sivin.alignment.grid import TimeGrid, epoch_ns
from sivin.alignment.registry import ClassRegistry
from sivin.core.defaults import DEFAULT_SAMPLING_INTERVAL_S
from sivin.core.schema import Column, MeasurementSeries

logger = logging.getLogger(__name__)

NS_PER_S: Final = 1_000_000_000
"""Nanoseconds per second (unit conversion)."""

MAX_GAP_FACTOR: Final = 1.5
"""Default ``max_gap_s`` of :class:`LinearInterpolation` as a multiple of the sampling interval.

Project choice [to be verified on real data]: 1.5 x the nominal 1830 s bridges two neighbouring
samples of an uninterrupted record, with room for clock jitter and drift, but not a missing
sample (which makes a gap of about 2 x 1830 s).
"""

DEFAULT_MAX_GAP_S: Final = MAX_GAP_FACTOR * DEFAULT_SAMPLING_INTERVAL_S
"""Default largest distance in seconds between two samples that may be interpolated (2745 s)."""

DEFAULT_TOLERANCE_MARGIN_S: Final = 20.0
"""Default margin in seconds added to half the sampling interval for the nearest tolerance.

Project choice [to be tuned on real data]: in an uninterrupted record sampled every
``expected_interval_s``, no instant is farther than half the interval from a sample; the margin
absorbs clock jitter. With the nominal 1830 s it gives 935 s, so 1830 s sampling covers every
point of an 1800 s grid.
"""


@dataclass(frozen=True, slots=True, eq=False)
class SampleSet:
    """The usable samples of one variable of one sensor, in time order.

    Parameters
    ----------
    times_ns : numpy.ndarray of int64
        Sample instants in nanoseconds since the Unix epoch (UTC), strictly increasing.
    sample_values : numpy.ndarray of float64
        Sample values in the unit of the variable (°C, %), none of them ``NaN``.

    Raises
    ------
    ValueError
        If the arrays differ in shape, times are not strictly increasing or a value is ``NaN``.
    """

    times_ns: npt.NDArray[np.int64]
    sample_values: npt.NDArray[np.float64]

    def __post_init__(self) -> None:
        if self.times_ns.ndim != 1 or self.times_ns.shape != self.sample_values.shape:
            raise ValueError(
                f"times_ns {self.times_ns.shape} and sample_values "
                f"{self.sample_values.shape} must be 1-D arrays of the same length."
            )
        if np.any(np.diff(self.times_ns) <= 0):
            raise ValueError("Sample times must be strictly increasing.")
        if np.isnan(self.sample_values).any():
            raise ValueError("Sample values must not be NaN; drop missing samples first.")

    @classmethod
    def from_series(cls, series: MeasurementSeries, variable: str, exclude_mask: int) -> SampleSet:
        """Select the usable samples of ``variable`` from a series.

        Parameters
        ----------
        series : MeasurementSeries
            The sensor's measurements.
        variable : str
            Column name of the variable, ``"temp_c"`` or ``"rh_pct"``.
        exclude_mask : int
            :class:`~sivin.core.flags.QcFlag` bits that exclude a sample.

        Returns
        -------
        SampleSet
            Samples of complete rows (temperature **and** humidity present, the whole-row rule
            of :meth:`~sivin.core.schema.MeasurementSeries.complete_mask`) that are not
            excluded. The rule is checked on the values, so a row with one variable missing is
            skipped for both variables even when it carries no ``MISSING`` flag.
        """
        frame = series.frame
        values = frame[variable].to_numpy(dtype=np.float64)
        usable = series.complete_mask(exclude_mask).to_numpy()
        times_ns = epoch_ns(frame[Column.TIMESTAMP])
        return cls(times_ns[usable], values[usable])

    def __len__(self) -> int:
        return len(self.times_ns)


@dataclass(frozen=True, slots=True, eq=False)
class AlignedValues:
    """The result of aligning one :class:`SampleSet` onto a grid.

    Parameters
    ----------
    grid_values : numpy.ndarray of float64
        One value per grid point in the unit of the variable; ``NaN`` where invalid.
    valid : numpy.ndarray of bool
        ``True`` where a value could be assigned.
    offset_s : numpy.ndarray of float64 or None
        Absolute distance in seconds between the grid point and the sample used; ``NaN`` where
        invalid. ``None`` for strategies that do not pick a single sample.
    """

    grid_values: npt.NDArray[np.float64]
    valid: npt.NDArray[np.bool_]
    offset_s: npt.NDArray[np.float64] | None = None

    def __post_init__(self) -> None:
        shapes = {self.grid_values.shape, self.valid.shape}
        if self.offset_s is not None:
            shapes.add(self.offset_s.shape)
        if len(shapes) != 1 or self.grid_values.ndim != 1:
            raise ValueError(f"Aligned arrays must be 1-D of equal length, got {sorted(shapes)}.")

    @classmethod
    def invalid(cls, n_points: int, *, with_offsets: bool) -> AlignedValues:
        """Return a result in which no grid point is valid.

        Parameters
        ----------
        n_points : int
            Number of grid points.
        with_offsets : bool
            Whether to include an (all ``NaN``) offset array.

        Returns
        -------
        AlignedValues
            ``NaN`` values, ``False`` validity.
        """
        nan = np.full(n_points, np.nan, dtype=np.float64)
        offsets = nan.copy() if with_offsets else None
        return cls(nan, np.zeros(n_points, dtype=np.bool_), offsets)


class StrategyParams(BaseModel):
    """Base of the parameter models of alignment strategies (frozen, unknown keys rejected)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class AlignmentStrategy[P: StrategyParams](ABC):
    """Extension point: put the samples of one sensor and variable onto a grid.

    Subclasses set :attr:`strategy_id` and :attr:`params_model`, implement :meth:`align` and
    register with ``@strategy_registry.register``.

    Parameters
    ----------
    params : P, optional
        Validated parameters (an instance of :attr:`params_model`); its defaults when omitted.

    Raises
    ------
    TypeError
        If ``params`` is not an instance of :attr:`params_model`.
    """

    strategy_id: ClassVar[str]
    """Identifier under which the strategy is registered (e.g. in the configuration)."""

    params_model: ClassVar[type[StrategyParams]] = StrategyParams
    """Pydantic model of the strategy's parameters; must be the type argument ``P``."""

    provides_offsets: ClassVar[bool] = False
    """Whether :meth:`align` reports the offset of the sample used for every grid point."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Check that :attr:`params_model` matches the generic argument ``P``.

        Raises
        ------
        TypeError
            If the class parametrises :class:`AlignmentStrategy` with a params class that
            :attr:`params_model` is not a subclass of.
        """
        super().__init_subclass__(**kwargs)
        declared_args = [
            get_args(base)[0]
            for base in getattr(cls, "__orig_bases__", ())
            if get_origin(base) is AlignmentStrategy
        ]
        for declared in declared_args:
            if isinstance(declared, type) and not issubclass(cls.params_model, declared):
                raise TypeError(
                    f"{cls.__name__}.params_model is {cls.params_model.__name__}, but the class "
                    f"is declared as AlignmentStrategy[{declared.__name__}]."
                )

    def __init__(self, params: P | None = None) -> None:
        if params is None:
            params = cast(P, self.params_model())
        if not isinstance(params, self.params_model):
            raise TypeError(
                f"{type(self).__name__} expects {self.params_model.__name__}, "
                f"got {type(params).__name__}."
            )
        self._params: P = params

    @classmethod
    def from_params(cls, params: Mapping[str, Any] | None = None) -> Self:
        """Build the strategy from raw parameter values, e.g. from the configuration.

        Parameters
        ----------
        params : Mapping, optional
            Raw values validated by :attr:`params_model`.

        Returns
        -------
        AlignmentStrategy
            A new instance.
        """
        return cls(cast(P, cls.params_model.model_validate(dict(params or {}))))

    @property
    def params(self) -> P:
        """The strategy's parameters."""
        return self._params

    @abstractmethod
    def align(self, samples: SampleSet, grid: TimeGrid) -> AlignedValues:
        """Assign a value to every grid point from the usable samples.

        Parameters
        ----------
        samples : SampleSet
            Usable samples of one sensor and variable.
        grid : TimeGrid
            The target grid.

        Returns
        -------
        AlignedValues
            Arrays with one entry per grid point.
        """

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._params!r})"


strategy_registry: Final = ClassRegistry[AlignmentStrategy[Any]](
    AlignmentStrategy, "strategy_id", "alignment strategy"
)
"""Registry of :class:`AlignmentStrategy` implementations, keyed by ``strategy_id``."""


class NearestParams(StrategyParams):
    """Parameters of :class:`NearestWithinTolerance`."""

    tolerance_s: float | None = Field(
        None,
        gt=0,
        allow_inf_nan=False,
        description=(
            "Explicit override of the largest distance in seconds (inclusive) between a grid "
            "point and the sample assigned to it. Default (null): expected_interval_s / 2 + "
            "margin_s."
        ),
    )
    expected_interval_s: float = Field(
        DEFAULT_SAMPLING_INTERVAL_S,
        gt=0,
        allow_inf_nan=False,
        description=(
            "Nominal sampling interval of the sensors in seconds. Set from "
            "time.expected_interval_s by the configuration (WP-1.7); default 1830 s, the "
            "median step of the first real export."
        ),
    )
    margin_s: float = Field(
        DEFAULT_TOLERANCE_MARGIN_S,
        ge=0,
        allow_inf_nan=False,
        description=(
            "Margin in seconds added to half the sampling interval for clock jitter; "
            "default 20 s, project choice [to be tuned on real data]."
        ),
    )


@strategy_registry.register
class NearestWithinTolerance(AlignmentStrategy[NearestParams]):
    r"""Take the usable sample nearest to each grid point, if it is close enough.

    For a grid point :math:`g` and usable sample times :math:`t_i`, the chosen sample is
    :math:`i^* = \arg\min_i |t_i - g|`, ties resolved to the earlier sample; the grid point is
    valid if :math:`|t_{i^*} - g| \le \tau`. The tolerance defaults to
    :math:`\tau = T/2 + m` with the expected sampling interval :math:`T` and a jitter margin
    :math:`m` (935 s by default), so an uninterrupted record covers every grid point even when
    it samples more slowly than the grid (1830 s against 1800 s); ``tolerance_s`` overrides it.
    The value is not modified, and the offset :math:`|t_{i^*} - g|` is reported in seconds.
    One sample may serve two neighbouring grid points.

    Parameters
    ----------
    params : NearestParams, optional
        ``tolerance_s`` or ``expected_interval_s`` and ``margin_s``; defaults when omitted.
    """

    strategy_id: ClassVar[str] = "nearest_within_tolerance"
    params_model: ClassVar[type[StrategyParams]] = NearestParams
    provides_offsets: ClassVar[bool] = True

    @property
    def tolerance_s(self) -> float:
        """Effective tolerance in seconds.

        ``params.tolerance_s`` if set, else ``expected_interval_s / 2 + margin_s``.
        """
        configured = self.params.tolerance_s
        if configured is not None:
            return configured
        return self.params.expected_interval_s / 2 + self.params.margin_s

    def align(self, samples: SampleSet, grid: TimeGrid) -> AlignedValues:
        """See :meth:`AlignmentStrategy.align`."""
        grid_ns = grid.times_ns
        n_points = len(grid_ns)
        if len(samples) == 0:
            return AlignedValues.invalid(n_points, with_offsets=self.provides_offsets)
        times_ns = samples.times_ns
        last = len(times_ns) - 1
        after = np.searchsorted(times_ns, grid_ns, side="left")
        before = after - 1
        after_idx = np.minimum(after, last)
        before_idx = np.maximum(before, 0)
        dist_after_ns = np.where(
            after <= last, times_ns[after_idx] - grid_ns, np.iinfo(np.int64).max
        )
        dist_before_ns = np.where(
            before >= 0, grid_ns - times_ns[before_idx], np.iinfo(np.int64).max
        )
        take_before = dist_before_ns <= dist_after_ns
        chosen = np.where(take_before, before_idx, after_idx)
        distance_ns = np.minimum(dist_before_ns, dist_after_ns)
        valid = distance_ns <= round(self.tolerance_s * NS_PER_S)
        values = np.where(valid, samples.sample_values[chosen], np.nan)
        offset_s = np.where(valid, distance_ns / NS_PER_S, np.nan)
        return AlignedValues(values.astype(np.float64), valid, offset_s.astype(np.float64))


class LinearParams(StrategyParams):
    """Parameters of :class:`LinearInterpolation`."""

    max_gap_s: float = Field(
        DEFAULT_MAX_GAP_S,
        gt=0,
        allow_inf_nan=False,
        description=(
            "Largest distance in seconds (inclusive) between the two usable samples that "
            "enclose a grid point for it to be interpolated. Default 1.5 x 1830 s = 2745 s "
            "(neighbouring samples only); project choice, to be verified on real data."
        ),
    )


@strategy_registry.register
class LinearInterpolation(AlignmentStrategy[LinearParams]):
    r"""Interpolate linearly in time between the two usable samples enclosing a grid point.

    For a grid point :math:`g` with usable neighbours :math:`t_l \le g \le t_r` (values
    :math:`v_l, v_r`), the value is

    .. math:: v(g) = v_l + (v_r - v_l) \frac{g - t_l}{t_r - t_l},

    valid only if :math:`t_r - t_l \le \Delta_{max}` (``max_gap_s``). A sample exactly at
    :math:`g` is taken as is. Grid points before the first or after the last usable sample are
    never extrapolated and stay invalid.

    Parameters
    ----------
    params : LinearParams, optional
        ``max_gap_s``; defaults when omitted.
    """

    strategy_id: ClassVar[str] = "linear_interpolation"
    params_model: ClassVar[type[StrategyParams]] = LinearParams

    @property
    def max_gap_s(self) -> float:
        """Largest interpolated gap in seconds."""
        return self.params.max_gap_s

    def align(self, samples: SampleSet, grid: TimeGrid) -> AlignedValues:
        """See :meth:`AlignmentStrategy.align`."""
        grid_ns = grid.times_ns
        n_points = len(grid_ns)
        if len(samples) == 0:
            return AlignedValues.invalid(n_points, with_offsets=self.provides_offsets)
        times_ns = samples.times_ns
        last = len(times_ns) - 1
        left = np.searchsorted(times_ns, grid_ns, side="right") - 1
        right = np.searchsorted(times_ns, grid_ns, side="left")
        enclosed = (left >= 0) & (right <= last)
        left_idx = np.clip(left, 0, last)
        right_idx = np.clip(right, 0, last)
        t_left = times_ns[left_idx]
        t_right = times_ns[right_idx]
        span_ns = t_right - t_left
        valid = enclosed & (span_ns <= round(self.max_gap_s * NS_PER_S))
        weight = np.divide(
            (grid_ns - t_left).astype(np.float64),
            span_ns.astype(np.float64),
            out=np.zeros(n_points, dtype=np.float64),
            where=span_ns > 0,
        )
        v_left = samples.sample_values[left_idx]
        v_right = samples.sample_values[right_idx]
        values = np.where(valid, v_left + (v_right - v_left) * weight, np.nan)
        return AlignedValues(values.astype(np.float64), valid)
