"""Pure column builders of the site files: times, rounded values, month keys.

Every function is free of I/O and tested in isolation (``tests/site/test_columns.py``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

VALUE_DECIMALS: Final = 2
"""Decimals of published measured values: temperature (°C), humidity (%), precipitation (mm)
and battery voltage (V), raw and daily.

The provider's export has at most two decimals (temperature 0.01 °C, battery 0.01 V; humidity
and precipitation 0.1, MIGRATION_PLAN §0.6.1), so 0.01 keeps every raw value exactly and cuts
the float noise of daily means.
"""

SHARE_DECIMALS: Final = 3
"""Decimals of published shares 0-1 (daily ``coverage``, index ``coverage``): 0.001 of a day
is 86 s, less than one sampling interval."""

INDEX_DECIMALS: Final = 2
"""Decimals of published index values (in the unit of each index)."""

CONFIDENCE_DECIMALS: Final = 2
"""Decimals of published event confidences 0-1."""

NANOSECONDS_PER_SECOND: Final = 1_000_000_000
"""Nanoseconds per second (``datetime64[ns]`` to Unix seconds)."""

MONTH_KEY_FORMAT: Final = "%Y-%m"
"""Format of the ``raw/<YYYY-MM>.json`` keys (UTC months, MIGRATION_PLAN §2.6)."""


def unix_seconds(timestamps: pd.Series | pd.DatetimeIndex) -> list[int]:
    """Convert aware timestamps to whole Unix seconds (UTC), rounding down.

    Parameters
    ----------
    timestamps : pandas.Series or pandas.DatetimeIndex
        Timezone-aware timestamps (any resolution).

    Returns
    -------
    list of int
        Seconds since 1970-01-01T00:00:00Z.
    """
    index = pd.DatetimeIndex(timestamps).tz_convert("UTC").tz_localize(None).as_unit("ns")
    nanoseconds = np.asarray(index, dtype="datetime64[ns]").view(np.int64)
    return [int(value) for value in np.floor_divide(nanoseconds, NANOSECONDS_PER_SECOND)]


def unix_second(moment: pd.Timestamp | datetime) -> int:
    """Convert one aware instant to whole Unix seconds (UTC), rounding down.

    Parameters
    ----------
    moment : pandas.Timestamp or datetime.datetime
        A timezone-aware instant.

    Returns
    -------
    int
        Seconds since the epoch.
    """
    return unix_seconds(pd.DatetimeIndex([pd.Timestamp(moment)]))[0]


def rounded(values: npt.ArrayLike, decimals: int) -> list[float | None]:
    """Round values for publication; missing values become ``None`` (JSON ``null``).

    Parameters
    ----------
    values : array_like of float
        Values in any unit; ``NaN`` = missing.
    decimals : int
        Decimals to keep.

    Returns
    -------
    list of float or None
        Rounded values (``-0.0`` is written as ``0.0``).
    """
    array = np.round(np.asarray(values, dtype=np.float64), decimals) + 0.0
    return [None if np.isnan(value) else float(value) for value in array]


def rounded_value(value: float | None, decimals: int) -> float | None:
    """Round one value for publication (:func:`rounded` for a scalar).

    Parameters
    ----------
    value : float or None
        A value; ``None`` or ``NaN`` = missing.
    decimals : int
        Decimals to keep.

    Returns
    -------
    float or None
        The rounded value, or ``None``.
    """
    if value is None:
        return None
    return rounded([value], decimals)[0]


def utc_month_keys(timestamps: pd.Series) -> npt.NDArray[np.str_]:
    """Return the UTC month of each timestamp as ``YYYY-MM``.

    Parameters
    ----------
    timestamps : pandas.Series
        Timezone-aware timestamps.

    Returns
    -------
    numpy.ndarray of str
        One key per timestamp, e.g. ``"2026-07"``.
    """
    utc = pd.DatetimeIndex(timestamps).tz_convert("UTC")
    return np.asarray(utc.strftime(MONTH_KEY_FORMAT), dtype=np.str_)


def local_years(first_utc: pd.Timestamp, last_utc: pd.Timestamp, timezone: str) -> tuple[int, ...]:
    """Return every calendar year of a time zone from the year of ``first_utc`` to ``last_utc``.

    Parameters
    ----------
    first_utc, last_utc : pandas.Timestamp
        Timezone-aware bounds.
    timezone : str
        IANA zone of the calendar years.

    Returns
    -------
    tuple of int
        Consecutive years, e.g. ``(2025, 2026)``.
    """
    first_year = pd.Timestamp(first_utc).tz_convert(timezone).year
    last_year = pd.Timestamp(last_utc).tz_convert(timezone).year
    return tuple(range(first_year, last_year + 1))


def iso_dates(days: list[date]) -> list[str]:
    """Format local dates as ``YYYY-MM-DD``.

    Parameters
    ----------
    days : list of datetime.date
        Dates.

    Returns
    -------
    list of str
        ISO dates.
    """
    return [day.isoformat() for day in days]


def iso_utc_seconds(moment: datetime) -> str:
    """Format an aware instant as ISO 8601 UTC with whole seconds and ``Z``.

    Parameters
    ----------
    moment : datetime.datetime
        A timezone-aware instant.

    Returns
    -------
    str
        E.g. ``"2026-10-05T04:00:00Z"``.

    Raises
    ------
    ValueError
        If ``moment`` is naive.
    """
    timestamp = pd.Timestamp(moment)
    if timestamp.tz is None:
        raise ValueError(f"generated_at must be timezone-aware, got {moment!r}.")
    return timestamp.tz_convert("UTC").floor("s").strftime("%Y-%m-%dT%H:%M:%SZ")
