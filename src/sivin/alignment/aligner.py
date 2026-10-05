"""Put several sensors on a common time grid (MIGRATION_PLAN §2.7, WP-1.6).

The sensors sample every ~1825 s with clocks that are neither synchronised nor stable, so their
timestamps never coincide. :class:`SensorAligner` maps each sensor's usable samples onto one
:class:`~sivin.alignment.grid.TimeGrid` with an
:class:`~sivin.alignment.strategies.AlignmentStrategy` and returns an
:class:`~sivin.alignment.panel.AlignedPanel`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Final

import pandas as pd

from sivin.alignment.config import AlignmentConfig
from sivin.alignment.grid import GridPolicy, TimeGrid, span_registry
from sivin.alignment.panel import AlignedPanel
from sivin.alignment.strategies import (
    AlignedValues,
    AlignmentStrategy,
    SampleSet,
    strategy_registry,
)
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import TIMESTAMP_DTYPE, Column, MeasurementSeries

logger = logging.getLogger(__name__)

ALIGNED_VARIABLES: Final = (str(Column.TEMP), str(Column.RH))
"""Variables aligned by default: air temperature (°C) and relative humidity (%)."""


class SensorAligner:
    """Align the measurements of N >= 1 sensors onto a common UTC grid.

    Every variable of every sensor is aligned independently: a sample whose temperature is
    usable but whose humidity is ``NaN`` still contributes its temperature. Samples whose
    ``qc`` flags intersect ``exclude_mask`` and ``NaN`` values are never paired.

    Parameters
    ----------
    strategy : AlignmentStrategy
        How samples are mapped onto grid points.
    grid_policy : GridPolicy, optional
        How the grid is derived when :meth:`align` gets no explicit grid. Default: 30 min step,
        union of the data spans.
    exclude_mask : int, optional
        :class:`~sivin.core.flags.QcFlag` bits that exclude a sample. Default
        ``QcFlag.DEFAULT_EXCLUDE`` (the same default as ``analytics.exclude_mask``).

    Raises
    ------
    ValueError
        If ``exclude_mask`` contains bits that are not :class:`QcFlag` values.
    """

    __slots__ = ("_exclude_mask", "_grid_policy", "_strategy")

    def __init__(
        self,
        strategy: AlignmentStrategy[Any],
        grid_policy: GridPolicy | None = None,
        exclude_mask: int = int(QcFlag.DEFAULT_EXCLUDE),
    ) -> None:
        unknown = int(exclude_mask) & ~QcFlag.all_bits()
        if exclude_mask < 0 or unknown:
            raise ValueError(f"exclude_mask {exclude_mask} contains bits that are not QcFlags.")
        self._strategy = strategy
        self._grid_policy = GridPolicy() if grid_policy is None else grid_policy
        self._exclude_mask = int(exclude_mask)

    @classmethod
    def from_config(cls, config: AlignmentConfig, exclude_mask: int) -> SensorAligner:
        """Build an aligner from its configuration section.

        Parameters
        ----------
        config : AlignmentConfig
            Strategy, its parameters, grid step and span rule.
        exclude_mask : int
            :class:`QcFlag` bits that exclude a sample (``analytics.exclude_mask``).

        Returns
        -------
        SensorAligner
            The configured aligner.
        """
        strategy = strategy_registry.get(config.strategy).from_params(config.params)
        span = span_registry.get(config.span)()
        return cls(strategy, GridPolicy(config.grid_step_s, span), exclude_mask)

    @property
    def strategy(self) -> AlignmentStrategy[Any]:
        """The alignment strategy."""
        return self._strategy

    @property
    def grid_policy(self) -> GridPolicy:
        """The policy that derives the grid from the data."""
        return self._grid_policy

    @property
    def exclude_mask(self) -> int:
        """The :class:`QcFlag` bits that exclude a sample."""
        return self._exclude_mask

    def grid_for(self, series: Sequence[MeasurementSeries]) -> TimeGrid | None:
        """Derive the grid for ``series`` with the aligner's policy and exclusion mask.

        Parameters
        ----------
        series : sequence of MeasurementSeries
            The series to cover.

        Returns
        -------
        TimeGrid or None
            The grid, or ``None`` if there is no usable data (or no overlap).
        """
        return TimeGrid.from_series(series, self._grid_policy, self._exclude_mask)

    def align(
        self, series: Sequence[MeasurementSeries], grid: TimeGrid | None = None
    ) -> AlignedPanel:
        """Align the series onto a common grid.

        Parameters
        ----------
        series : sequence of MeasurementSeries
            One series per sensor, at least one; sensor ids must be unique. Columns are ordered
            by sensor id, whatever the input order.
        grid : TimeGrid, optional
            Explicit target grid; derived with :meth:`grid_for` when omitted.

        Returns
        -------
        AlignedPanel
            Values, validity and (for single-sample strategies) offsets per variable. If no
            grid can be derived, the panel has zero grid points.

        Raises
        ------
        ValueError
            If ``series`` is empty or a sensor id occurs twice.
        """
        ordered = _ordered_unique(series)
        target = self.grid_for(ordered) if grid is None else grid
        if target is None:
            logger.warning(
                "No common grid for sensors %s; returning an empty panel.",
                ", ".join(str(one.sensor_id) for one in ordered),
            )
            return self._empty_panel(ordered)
        aligned = {
            variable: {one.sensor_id: self._align_one(one, variable, target) for one in ordered}
            for variable in ALIGNED_VARIABLES
        }
        logger.info(
            "Aligned %d sensor(s) onto %d grid points (%s, step %.0f s).",
            len(ordered),
            len(target),
            self._strategy.strategy_id,
            target.step_s,
        )
        return AlignedPanel(
            target.times, [one.sensor_id for one in ordered], self._strategy.strategy_id, aligned
        )

    def _align_one(self, series: MeasurementSeries, variable: str, grid: TimeGrid) -> AlignedValues:
        samples = SampleSet.from_series(series, variable, self._exclude_mask)
        return self._strategy.align(samples, grid)

    def _empty_panel(self, ordered: Sequence[MeasurementSeries]) -> AlignedPanel:
        times = pd.DatetimeIndex([], dtype=TIMESTAMP_DTYPE)
        empty = AlignedValues.invalid(0, with_offsets=self._strategy.provides_offsets)
        aligned = {
            variable: {one.sensor_id: empty for one in ordered} for variable in ALIGNED_VARIABLES
        }
        return AlignedPanel(
            times, [one.sensor_id for one in ordered], self._strategy.strategy_id, aligned
        )


def _ordered_unique(series: Sequence[MeasurementSeries]) -> list[MeasurementSeries]:
    if not series:
        raise ValueError("At least one series is needed for an alignment.")
    ids: list[SensorId] = [one.sensor_id for one in series]
    duplicates = sorted({str(sensor) for sensor in ids if ids.count(sensor) > 1})
    if duplicates:
        raise ValueError(f"Each sensor may occur only once; duplicated: {duplicates}.")
    return sorted(series, key=lambda one: one.sensor_id)
