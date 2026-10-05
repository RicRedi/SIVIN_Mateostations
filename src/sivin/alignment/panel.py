"""The result of an alignment: a wide ``time x sensor`` table per variable (MIGRATION_PLAN §2.7)."""

from __future__ import annotations

import itertools
import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.alignment.strategies import AlignedValues
from sivin.core.ids import SensorId
from sivin.core.schema import TIMESTAMP_DTYPE, Column

logger = logging.getLogger(__name__)

SENSOR_AXIS: Final = str(Column.SENSOR_ID)
"""Name of the column axis of the wide tables (sensor ids as strings)."""

SENSOR_A: Final = "sensor_a"
"""Column of :meth:`AlignedPanel.pairwise_differences`: the minuend sensor."""

SENSOR_B: Final = "sensor_b"
"""Column of :meth:`AlignedPanel.pairwise_differences`: the subtrahend sensor."""

DELTA_PREFIX: Final = "delta_"
"""Prefix of the difference column, e.g. ``delta_temp_c`` (unit of the variable)."""


class AlignedPanel:
    """Several sensors on one common time grid, per variable.

    For every variable (``temp_c``, ``rh_pct``) the panel holds a wide table indexed by the
    grid time (``timestamp_utc``, UTC) with one column per sensor id (string), plus a boolean
    validity table of the same shape and, for strategies that pick a single sample, the absolute
    offset in seconds between the grid point and the sample used. Invalid cells are ``NaN``.

    The panel is immutable: it is built once by :class:`~sivin.alignment.aligner.SensorAligner`
    and every accessor returns a copy.

    Parameters
    ----------
    times : pandas.DatetimeIndex
        Grid points, ``datetime64[ns, UTC]``; may be empty.
    sensors : sequence of SensorId
        Sensors in column order, at least one, unique.
    strategy_id : str
        Identifier of the strategy that produced the values.
    aligned : Mapping[str, Mapping[SensorId, AlignedValues]]
        Per variable and sensor, the aligned arrays (one entry per grid point).

    Raises
    ------
    ValueError
        If there is no sensor, sensors repeat, a variable lacks a sensor or an array does not
        match the grid.
    """

    __slots__ = ("_offsets_s", "_sensors", "_strategy_id", "_times", "_valid", "_values")

    def __init__(
        self,
        times: pd.DatetimeIndex,
        sensors: Sequence[SensorId],
        strategy_id: str,
        aligned: Mapping[str, Mapping[SensorId, AlignedValues]],
    ) -> None:
        if not sensors:
            raise ValueError("A panel needs at least one sensor.")
        if len(set(sensors)) != len(sensors):
            raise ValueError(f"Sensors must be unique, got {[str(s) for s in sensors]}.")
        if times.dtype != TIMESTAMP_DTYPE:
            raise ValueError(f"Grid times must be {TIMESTAMP_DTYPE}, got {times.dtype}.")
        self._times = times.rename(str(Column.TIMESTAMP))
        self._sensors = tuple(sensors)
        self._strategy_id = strategy_id
        self._values: dict[str, pd.DataFrame] = {}
        self._valid: dict[str, pd.DataFrame] = {}
        self._offsets_s: dict[str, pd.DataFrame] = {}
        for variable, per_sensor in aligned.items():
            self._add_variable(variable, per_sensor)

    @property
    def times(self) -> pd.DatetimeIndex:
        """The grid points (``datetime64[ns, UTC]``)."""
        return self._times.copy()

    @property
    def sensors(self) -> tuple[SensorId, ...]:
        """The sensors, in column order."""
        return self._sensors

    @property
    def variables(self) -> tuple[str, ...]:
        """The aligned variables, e.g. ``("temp_c", "rh_pct")``."""
        return tuple(self._values)

    @property
    def strategy_id(self) -> str:
        """Identifier of the alignment strategy that produced the panel."""
        return self._strategy_id

    @property
    def is_empty(self) -> bool:
        """``True`` if the grid has no points."""
        return len(self._times) == 0

    def __len__(self) -> int:
        return len(self._times)

    def __repr__(self) -> str:
        return (
            f"AlignedPanel(strategy={self._strategy_id!r}, points={len(self)}, "
            f"sensors={[str(s) for s in self._sensors]}, variables={list(self.variables)})"
        )

    def variable(self, name: str) -> pd.DataFrame:
        """Return the wide value table of a variable.

        Parameters
        ----------
        name : str
            ``"temp_c"`` (°C) or ``"rh_pct"`` (%).

        Returns
        -------
        pandas.DataFrame
            Index ``timestamp_utc``, one ``float64`` column per sensor id, ``NaN`` where
            invalid. Values are in the unit of the variable.

        Raises
        ------
        KeyError
            If the variable was not aligned.
        """
        return self._table(self._values, name).copy()

    def validity(self, name: str) -> pd.DataFrame:
        """Return the validity mask of a variable.

        Parameters
        ----------
        name : str
            Variable name.

        Returns
        -------
        pandas.DataFrame
            Same shape as :meth:`variable`, ``bool``: ``True`` where a value was assigned.

        Raises
        ------
        KeyError
            If the variable was not aligned.
        """
        return self._table(self._valid, name).copy()

    def offsets_s(self, name: str) -> pd.DataFrame | None:
        """Return the absolute offsets between grid points and the samples used.

        Parameters
        ----------
        name : str
            Variable name.

        Returns
        -------
        pandas.DataFrame or None
            Same shape as :meth:`variable`, offsets in seconds (``NaN`` where invalid), or
            ``None`` if the strategy does not pick single samples (interpolation).

        Raises
        ------
        KeyError
            If the variable was not aligned.
        """
        self._table(self._values, name)
        offsets = self._offsets_s.get(name)
        return None if offsets is None else offsets.copy()

    def complete_rows(self, name: str) -> pd.DataFrame:
        """Return the grid points where every sensor has a valid value.

        Parameters
        ----------
        name : str
            Variable name.

        Returns
        -------
        pandas.DataFrame
            The rows of :meth:`variable` without any invalid cell.

        Raises
        ------
        KeyError
            If the variable was not aligned.
        """
        values = self._table(self._values, name)
        complete = self._valid[name].all(axis=1)
        return values.loc[complete].copy()

    def pairwise_differences(
        self,
        name: str,
        pairs: Iterable[tuple[SensorId | str, SensorId | str]] | None = None,
    ) -> pd.DataFrame:
        """Return ``A - B`` for pairs of sensors at every grid point where both are valid.

        By default every pair in column order: for sensors ``s1, s2, s3`` the pairs are
        ``(s1, s2), (s1, s3), (s2, s3)``. The result has one row per pair and valid grid
        point, about 18 bytes each (8 time, 8 difference, 2 x 1 sensor code for fewer than 128
        sensors): a year of 30 min data for 30 sensors (435 pairs) is about 7.6 M rows,
        ~140 MB. Pass ``pairs`` to request only the pairs needed, e.g. neighbours.

        Parameters
        ----------
        name : str
            Variable name.
        pairs : iterable of (SensorId or str, SensorId or str), optional
            Ordered pairs ``(A, B)`` to compute, in the given order; all pairs when omitted.

        Returns
        -------
        pandas.DataFrame
            Long format with columns ``timestamp_utc`` (UTC), ``sensor_a``, ``sensor_b``
            (categorical, categories = all sensor ids of the panel) and ``delta_<name>``
            (difference in the unit of the variable), ordered by pair and then by time.
            Empty for fewer than two sensors.

        Raises
        ------
        KeyError
            If the variable was not aligned or a pair names a sensor not in the panel.
        ValueError
            If a pair names the same sensor twice.
        """
        values = self._table(self._values, name).to_numpy()
        valid = self._valid[name].to_numpy()
        index_pairs = self._pair_indices(pairs)
        code_dtype = np.min_scalar_type(len(self._sensors))
        rows: list[npt.NDArray[np.intp]] = [np.array([], dtype=np.intp)]
        codes_a: list[npt.NDArray[np.integer]] = [np.array([], dtype=code_dtype)]
        codes_b: list[npt.NDArray[np.integer]] = [np.array([], dtype=code_dtype)]
        deltas: list[npt.NDArray[np.float64]] = [np.array([], dtype=np.float64)]
        for i, j in index_pairs:
            both = np.flatnonzero(valid[:, i] & valid[:, j])
            rows.append(both)
            codes_a.append(np.full(len(both), i, dtype=code_dtype))
            codes_b.append(np.full(len(both), j, dtype=code_dtype))
            deltas.append(values[both, i] - values[both, j])
        categories = pd.Index([str(sensor) for sensor in self._sensors], dtype="str")
        return pd.DataFrame(
            {
                str(Column.TIMESTAMP): self._times[np.concatenate(rows)],
                SENSOR_A: pd.Categorical.from_codes(np.concatenate(codes_a), categories),
                SENSOR_B: pd.Categorical.from_codes(np.concatenate(codes_b), categories),
                DELTA_PREFIX + name: np.concatenate(deltas),
            }
        )

    def _pair_indices(
        self, pairs: Iterable[tuple[SensorId | str, SensorId | str]] | None
    ) -> list[tuple[int, int]]:
        if pairs is None:
            return list(itertools.combinations(range(len(self._sensors)), 2))
        positions = {str(sensor): k for k, sensor in enumerate(self._sensors)}
        result: list[tuple[int, int]] = []
        for first, second in pairs:
            try:
                i, j = positions[str(first)], positions[str(second)]
            except KeyError:
                raise KeyError(
                    f"Pair ({first}, {second}) names a sensor not in the panel; "
                    f"sensors: {list(positions)}."
                ) from None
            if i == j:
                raise ValueError(f"Pair ({first}, {second}) names the same sensor twice.")
            result.append((i, j))
        return result

    def _table(self, tables: Mapping[str, pd.DataFrame], name: str) -> pd.DataFrame:
        try:
            return tables[name]
        except KeyError:
            raise KeyError(
                f"Variable {name!r} is not in the panel; aligned: {list(self.variables)}."
            ) from None

    def _add_variable(self, variable: str, per_sensor: Mapping[SensorId, AlignedValues]) -> None:
        missing = [str(s) for s in self._sensors if s not in per_sensor]
        extra = [str(s) for s in per_sensor if s not in self._sensors]
        if missing or extra:
            raise ValueError(f"Variable {variable!r}: missing sensors {missing}, extra {extra}.")
        columns = pd.Index([str(s) for s in self._sensors], name=SENSOR_AXIS, dtype="str")
        arrays = [per_sensor[sensor] for sensor in self._sensors]
        for sensor, array in zip(self._sensors, arrays, strict=True):
            if len(array.valid) != len(self._times):
                raise ValueError(
                    f"Variable {variable!r}, sensor {sensor}: {len(array.valid)} values for "
                    f"{len(self._times)} grid points."
                )
        self._values[variable] = self._frame([a.grid_values for a in arrays], columns, np.float64)
        self._valid[variable] = self._frame([a.valid for a in arrays], columns, np.bool_)
        offsets = [a.offset_s for a in arrays]
        if all(offset is not None for offset in offsets):
            self._offsets_s[variable] = self._frame(offsets, columns, np.float64)

    def _frame(
        self,
        arrays: Sequence[npt.NDArray[np.generic] | None],
        columns: pd.Index,
        dtype: type[np.generic],
    ) -> pd.DataFrame:
        data = np.column_stack([np.asarray(a, dtype=dtype) for a in arrays])
        return pd.DataFrame(data, index=self._times, columns=columns)
