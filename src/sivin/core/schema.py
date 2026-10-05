"""Canonical measurement schema (MIGRATION_PLAN §2.5).

:class:`MeasurementSeries` is the one in-memory representation of the measurements of one sensor
that every subsystem (parsers, store, quality control, alignment, indices) exchanges. It wraps a
:class:`pandas.DataFrame`, validates it on construction and never exposes its internal frame for
mutation: every operation returns a new instance.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Final, Self

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.core.flags import QcFlag, excluded
from sivin.core.ids import SensorId

logger = logging.getLogger(__name__)


class Column(StrEnum):
    """Column names of the canonical long format (MIGRATION_PLAN §2.5)."""

    SENSOR_ID = "sensor_id"
    TIMESTAMP = "timestamp_utc"
    TEMP = "temp_c"
    RH = "rh_pct"
    QC = "qc"
    SOURCE = "source"


TIMESTAMP_DTYPE: Final = pd.DatetimeTZDtype(unit="ns", tz="UTC")
"""Dtype of :attr:`Column.TIMESTAMP`: nanosecond resolution, UTC (MIGRATION_PLAN §1.5)."""

VALUE_DTYPE: Final = np.dtype(np.float64)
"""Dtype of the measured values; ``NaN`` marks a missing value."""

QC_DTYPE: Final = np.dtype(np.int32)
"""Dtype of the :attr:`Column.QC` bit field (:class:`~sivin.core.flags.QcFlag`)."""

REQUIRED_COLUMNS: Final = (Column.TIMESTAMP, Column.TEMP, Column.RH, Column.QC)
"""Columns every series frame must have, in canonical order."""

OPTIONAL_COLUMNS: Final = (Column.SOURCE,)
"""Columns a series frame may have."""

TimestampLike = pd.Timestamp | datetime | str
"""Anything :class:`pandas.Timestamp` accepts as a tz-aware point in time."""


_NAIVE_TIMESTAMPS_MESSAGE: Final = (
    "Timestamps must be timezone-aware. Convert local wall-clock time with "
    "LocalTimeConverter.to_utc() first."
)


class SchemaError(ValueError):
    """Raised when data violate the canonical measurement schema."""


class MeasurementSeries:
    """Validated measurements of a single sensor in the canonical schema.

    The frame has a default ``RangeIndex`` and the columns

    ========================  =========================  ====  =================================
    column                    dtype                      unit  note
    ========================  =========================  ====  =================================
    ``timestamp_utc``         ``datetime64[ns, UTC]``    —     strictly increasing, unique
    ``temp_c``                ``float64``                °C    ``NaN`` = missing
    ``rh_pct``                ``float64``                %     ``NaN`` = missing
    ``qc``                    ``int32``                  —     :class:`QcFlag` bit field
    ``source`` (optional)     string                     —     name of the source file
    ========================  =========================  ====  =================================

    The ``sensor_id`` column of the long format is not stored per row; it is added by
    :meth:`to_frame`.

    Parameters
    ----------
    sensor_id : SensorId
        The sensor all rows belong to.
    frame : pandas.DataFrame
        Data in the canonical schema. A ``sensor_id`` column is accepted (and dropped) only if
        every row equals ``sensor_id``. Use :meth:`from_records` to normalise raw data first.

    Raises
    ------
    SchemaError
        If the frame does not follow the schema exactly.
    """

    __slots__ = ("_frame", "_sensor_id")

    def __init__(self, sensor_id: SensorId, frame: pd.DataFrame) -> None:
        self._sensor_id = sensor_id
        self._frame = _validated_copy(sensor_id, frame)

    @classmethod
    def from_records(
        cls,
        sensor_id: SensorId,
        timestamps_utc: Sequence[TimestampLike] | pd.Series | pd.DatetimeIndex,
        temp_c: npt.ArrayLike,
        rh_pct: npt.ArrayLike,
        qc: npt.ArrayLike | None = None,
        source: str | Sequence[str] | None = None,
    ) -> Self:
        """Build a series from raw columns, normalising them before validation.

        Normalisation: timestamps are converted to UTC with nanosecond resolution, rows are
        sorted by time (stable), exact duplicate timestamps are dropped keeping the last row
        (a warning is logged), values are cast to ``float64`` and flags to ``int32``.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor all rows belong to.
        timestamps_utc : sequence of timestamps
            Timezone-aware points in time (any zone; converted to UTC). Naive timestamps are
            rejected: convert local wall-clock time with
            :class:`~sivin.core.timeutil.LocalTimeConverter` first.
        temp_c : array_like of float
            Air temperature in °C.
        rh_pct : array_like of float
            Relative humidity in %.
        qc : array_like of int, optional
            :class:`QcFlag` bit fields; ``0`` (no finding) for every row when omitted.
        source : str or sequence of str, optional
            Source file name, either one for all rows or one per row.

        Returns
        -------
        MeasurementSeries
            The validated series.

        Raises
        ------
        SchemaError
            If the columns have different lengths, timestamps are naive or unparsable, or the
            normalised data still violate the schema.
        """
        timestamps = _utc_timestamps(timestamps_utc)
        n_rows = len(timestamps)
        columns: dict[str, object] = {
            Column.TIMESTAMP: timestamps,
            Column.TEMP: _column(temp_c, n_rows, Column.TEMP, VALUE_DTYPE),
            Column.RH: _column(rh_pct, n_rows, Column.RH, VALUE_DTYPE),
            Column.QC: np.zeros(n_rows, dtype=QC_DTYPE) if qc is None else _qc_column(qc, n_rows),
        }
        if source is not None:
            sources = [source] * n_rows if isinstance(source, str) else list(source)
            if len(sources) != n_rows:
                raise SchemaError(f"'{Column.SOURCE}' has {len(sources)} rows, expected {n_rows}.")
            columns[Column.SOURCE] = pd.array(sources, dtype="str")
        frame = pd.DataFrame(columns)
        frame = frame.sort_values(Column.TIMESTAMP, kind="stable", ignore_index=True)
        duplicated = frame[Column.TIMESTAMP].duplicated(keep="last")
        if duplicated.any():
            logger.warning(
                "Sensor %s: dropped %d row(s) with a duplicate timestamp (kept the last).",
                sensor_id,
                int(duplicated.sum()),
            )
            frame = frame.loc[~duplicated].reset_index(drop=True)
        return cls(sensor_id, frame)

    @classmethod
    def empty(cls, sensor_id: SensorId) -> Self:
        """Return a series without rows.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor the (empty) series belongs to.

        Returns
        -------
        MeasurementSeries
            A series with the required columns and zero rows.
        """
        return cls.from_records(sensor_id, pd.DatetimeIndex([], tz="UTC"), [], [])

    @property
    def sensor_id(self) -> SensorId:
        """The sensor all rows belong to."""
        return self._sensor_id

    @property
    def frame(self) -> pd.DataFrame:
        """A copy of the data (without the ``sensor_id`` column)."""
        return self._frame.copy()

    @property
    def timestamps(self) -> pd.Series:
        """A copy of the ``timestamp_utc`` column (``datetime64[ns, UTC]``)."""
        return self._frame[Column.TIMESTAMP].copy()

    @property
    def is_empty(self) -> bool:
        """``True`` if the series has no rows."""
        return self._frame.empty

    def __len__(self) -> int:
        return len(self._frame)

    def __repr__(self) -> str:
        if self.is_empty:
            return f"MeasurementSeries(sensor_id={self._sensor_id}, rows=0)"
        first = self._frame[Column.TIMESTAMP].iloc[0]
        last = self._frame[Column.TIMESTAMP].iloc[-1]
        return (
            f"MeasurementSeries(sensor_id={self._sensor_id}, rows={len(self)}, "
            f"from={first.isoformat()}, to={last.isoformat()})"
        )

    def between(self, start: TimestampLike, end: TimestampLike) -> Self:
        """Select rows with ``start <= timestamp_utc <= end``.

        Parameters
        ----------
        start, end : timestamp
            Timezone-aware bounds (inclusive).

        Returns
        -------
        MeasurementSeries
            A new series with the selected rows.

        Raises
        ------
        ValueError
            If a bound is naive (has no timezone).
        """
        start_utc = _aware_timestamp(start, "start")
        end_utc = _aware_timestamp(end, "end")
        times = self._frame[Column.TIMESTAMP]
        selected = (times >= start_utc) & (times <= end_utc)
        return self._derived(self._frame.loc[selected])

    def with_flags(self, flags: npt.NDArray[np.integer] | pd.Series) -> Self:
        """Return a copy with ``flags`` OR-ed into the ``qc`` column.

        Parameters
        ----------
        flags : numpy.ndarray or pandas.Series of int
            One :class:`QcFlag` bit field per row, in row order.

        Returns
        -------
        MeasurementSeries
            A new series; existing flags are kept.

        Raises
        ------
        SchemaError
            If the length differs from the series or a value is not a valid flag combination.
        """
        values = np.asarray(flags)
        if values.shape != (len(self),):
            raise SchemaError(f"Expected {len(self)} flag values, got shape {values.shape}.")
        if not np.issubdtype(values.dtype, np.integer):
            raise SchemaError(f"Flags must be integers, got dtype {values.dtype}.")
        _check_flag_values(values)
        frame = self._frame.copy()
        frame[Column.QC] = np.bitwise_or(frame[Column.QC].to_numpy(), values.astype(QC_DTYPE))
        return self._derived(frame)

    def valid_mask(self, exclude_mask: int) -> pd.Series:
        """Tell which rows are not excluded by the flags in ``exclude_mask``.

        Only the ``qc`` flags are considered; ``NaN`` values are not checked here.

        Parameters
        ----------
        exclude_mask : int
            Exclusion mask, e.g. ``QcFlag.DEFAULT_EXCLUDE``.

        Returns
        -------
        pandas.Series of bool
            ``True`` for rows that are usable, aligned with :attr:`frame`.
        """
        is_excluded = excluded(self._frame[Column.QC].to_numpy(), exclude_mask)
        return pd.Series(~is_excluded, index=self._frame.index, name="valid", dtype=bool)

    def to_frame(self) -> pd.DataFrame:
        """Return the data in the long format of MIGRATION_PLAN §2.5.

        Returns
        -------
        pandas.DataFrame
            A copy with a leading ``sensor_id`` column (string).
        """
        frame = self._frame.copy()
        sensor_ids = pd.Series(str(self._sensor_id), index=frame.index, dtype="str")
        frame.insert(0, Column.SENSOR_ID, sensor_ids)
        return frame

    def _derived(self, frame: pd.DataFrame) -> Self:
        return type(self)(self._sensor_id, frame.reset_index(drop=True))


def _validated_copy(sensor_id: SensorId, frame: pd.DataFrame) -> pd.DataFrame:
    """Validate ``frame`` against the schema and return a canonical private copy."""
    if not isinstance(frame, pd.DataFrame):
        raise SchemaError(f"Expected a pandas DataFrame, got {type(frame).__name__}.")
    data = frame.copy()
    if Column.SENSOR_ID in data.columns:
        foreign = data[Column.SENSOR_ID].astype("str") != str(sensor_id)
        if foreign.any():
            raise SchemaError(
                f"Column '{Column.SENSOR_ID}' contains ids other than {sensor_id}: "
                f"{sorted(set(data.loc[foreign, Column.SENSOR_ID].astype('str')))}."
            )
        data = data.drop(columns=Column.SENSOR_ID)
    _check_columns(data)
    _check_timestamps(data[Column.TIMESTAMP])
    for column in (Column.TEMP, Column.RH):
        if data[column].dtype != VALUE_DTYPE:
            raise SchemaError(f"Column '{column}' must be float64, got {data[column].dtype}.")
    if data[Column.QC].dtype != QC_DTYPE:
        raise SchemaError(f"Column '{Column.QC}' must be int32, got {data[Column.QC].dtype}.")
    _check_flag_values(data[Column.QC].to_numpy())
    if Column.SOURCE in data.columns:
        data[Column.SOURCE] = _checked_source(data[Column.SOURCE])
    ordered = [str(c) for c in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) if c in data.columns]
    return data[ordered].reset_index(drop=True)


def _check_columns(frame: pd.DataFrame) -> None:
    present = {str(c) for c in frame.columns}
    missing = [str(c) for c in REQUIRED_COLUMNS if c not in present]
    unknown = sorted(present - {str(c) for c in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)})
    if missing or unknown:
        raise SchemaError(f"Invalid columns: missing {missing}, unknown {unknown}.")


def _check_timestamps(times: pd.Series) -> None:
    if times.dtype != TIMESTAMP_DTYPE:
        raise SchemaError(
            f"Column '{Column.TIMESTAMP}' must be {TIMESTAMP_DTYPE}, got {times.dtype}. "
            "Use MeasurementSeries.from_records() to normalise timestamps."
        )
    if times.isna().any():
        raise SchemaError(f"Column '{Column.TIMESTAMP}' contains missing timestamps.")
    if times.duplicated().any():
        raise SchemaError(f"Column '{Column.TIMESTAMP}' contains duplicate timestamps.")
    if not times.is_monotonic_increasing:
        raise SchemaError(f"Column '{Column.TIMESTAMP}' is not sorted in increasing order.")


def _check_flag_values(flags: npt.ArrayLike) -> None:
    values = np.asarray(flags, dtype=np.int64)
    invalid = (values < 0) | (np.bitwise_and(values, ~np.int64(QcFlag.all_bits())) != 0)
    if invalid.any():
        raise SchemaError(f"Invalid QC flag values: {sorted(set(values[invalid].tolist()))}.")


def _checked_source(source: pd.Series) -> pd.Series:
    if source.isna().any() or not pd.api.types.is_string_dtype(source):
        raise SchemaError(f"Column '{Column.SOURCE}' must contain strings only.")
    return source.astype("str")


def _column(
    values: npt.ArrayLike, n_rows: int, name: Column, dtype: np.dtype[np.generic]
) -> npt.NDArray[np.generic]:
    try:
        array = np.asarray(values, dtype=dtype)
    except (TypeError, ValueError) as error:
        raise SchemaError(f"Column '{name}' cannot be converted to {dtype}: {error}") from error
    if array.shape != (n_rows,):
        raise SchemaError(f"Column '{name}' has shape {array.shape}, expected ({n_rows},).")
    return array


def _qc_column(values: npt.ArrayLike, n_rows: int) -> npt.NDArray[np.generic]:
    raw = np.asarray(values)
    if raw.size and not np.issubdtype(raw.dtype, np.integer):
        raise SchemaError(f"Column '{Column.QC}' must contain integers, got dtype {raw.dtype}.")
    _check_flag_values(raw)
    return _column(raw, n_rows, Column.QC, QC_DTYPE)


def _utc_timestamps(
    values: Sequence[TimestampLike] | pd.Series | pd.DatetimeIndex,
) -> pd.DatetimeIndex:
    if isinstance(values, pd.Series | pd.DatetimeIndex):
        index = pd.DatetimeIndex(values)
        if index.tz is None:
            raise SchemaError(_NAIVE_TIMESTAMPS_MESSAGE)
    else:
        try:
            stamps = [pd.Timestamp(value) for value in values]
        except (TypeError, ValueError) as error:
            raise SchemaError(f"Cannot parse timestamps: {error}") from error
        if any(pd.isna(stamp) for stamp in stamps):
            raise SchemaError("Timestamps must not be missing.")
        if any(stamp.tz is None for stamp in stamps):
            raise SchemaError(_NAIVE_TIMESTAMPS_MESSAGE)
        index = pd.DatetimeIndex([stamp.tz_convert("UTC") for stamp in stamps], tz="UTC")
    return index.tz_convert("UTC").as_unit("ns")


def _aware_timestamp(value: TimestampLike, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tz is None:
        raise ValueError(f"'{name}' must be timezone-aware, got {value!r}.")
    return timestamp.tz_convert("UTC")
