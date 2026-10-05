"""Plain NumPy views of a :class:`~sivin.core.schema.MeasurementSeries` for quality control.

The checks work on arrays: time in seconds since the Unix epoch (from the series' real UTC
timestamps, so irregular sampling is handled exactly) and one ``float64`` array per measured
variable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.core.schema import Column, MeasurementSeries

NS_PER_S: Final = 1_000_000_000
"""Nanoseconds per second (unit conversion of ``datetime64[ns]``)."""

S_PER_H: Final = 3600.0
"""Seconds per hour (unit conversion)."""

S_PER_DAY: Final = 86_400.0
"""Seconds per day (unit conversion)."""

FloatArray = npt.NDArray[np.float64]
"""A one-dimensional ``float64`` array."""


class Variable(StrEnum):
    """A measured variable; the value is the column name of the canonical schema."""

    TEMP = Column.TEMP.value
    RH = Column.RH.value

    @property
    def unit(self) -> str:
        """Unit of the variable (``°C`` or ``%``)."""
        return _UNITS[self]


_UNITS: Final = {Variable.TEMP: "°C", Variable.RH: "%"}


@dataclass(frozen=True, slots=True)
class SampleArrays:
    """Time and values of a series as read-only NumPy arrays.

    Attributes
    ----------
    t_ns : numpy.ndarray of int
        Sample times in nanoseconds since 1970-01-01T00:00:00Z (UTC), strictly increasing.
    t_s : numpy.ndarray of float
        The same times in seconds (for arithmetic with durations).
    temp_c : numpy.ndarray of float
        Air temperature in °C, ``NaN`` where missing.
    rh_pct : numpy.ndarray of float
        Relative humidity in %, ``NaN`` where missing.
    qc : numpy.ndarray of int
        :class:`~sivin.core.flags.QcFlag` bit fields already present in the series.
    """

    t_ns: npt.NDArray[np.int64]
    t_s: FloatArray
    temp_c: FloatArray
    rh_pct: FloatArray
    qc: npt.NDArray[np.int32]

    @classmethod
    def of(cls, series: MeasurementSeries) -> SampleArrays:
        """Extract the arrays of a series.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        SampleArrays
            Read-only arrays in row order.
        """
        frame = series.frame
        t_ns = frame[Column.TIMESTAMP].to_numpy(dtype="datetime64[ns]").view(np.int64).copy()
        return cls(
            t_ns=_readonly(t_ns),
            t_s=_readonly(t_ns.astype(np.float64) / NS_PER_S),
            temp_c=_readonly(frame[Column.TEMP].to_numpy(dtype=np.float64)),
            rh_pct=_readonly(frame[Column.RH].to_numpy(dtype=np.float64)),
            qc=_readonly(frame[Column.QC].to_numpy(dtype=np.int32)),
        )

    def __len__(self) -> int:
        return int(self.t_s.shape[0])

    def values(self, variable: Variable) -> FloatArray:
        """Return the values of one variable.

        Parameters
        ----------
        variable : Variable
            Which variable.

        Returns
        -------
        numpy.ndarray of float
            Values in the unit of the variable (°C or %), ``NaN`` where missing.
        """
        return self.temp_c if variable is Variable.TEMP else self.rh_pct

    def timestamp(self, position: int) -> pd.Timestamp:
        """Return the exact timestamp of one sample.

        Parameters
        ----------
        position : int
            Row position.

        Returns
        -------
        pandas.Timestamp
            The sample time (UTC).
        """
        return pd.Timestamp(int(self.t_ns[position]), unit="ns", tz="UTC")


def _readonly(array: npt.NDArray[Any]) -> npt.NDArray[Any]:
    array.setflags(write=False)
    return array
