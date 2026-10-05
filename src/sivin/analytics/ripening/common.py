"""Shared base of the ripening and risk indices: result assembly and day selection."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import replace
from datetime import date

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.analytics.base import (
    ClimateIndex,
    IndexContext,
    IndexParams,
    IndexResult,
    SeasonDays,
)
from sivin.analytics.ripening.psychrometry import non_positive_humidity
from sivin.core.daily import DailyWeather
from sivin.core.timeutil import LocalTimeConverter

logger = logging.getLogger(__name__)


class RipeningIndex[P: IndexParams](ClimateIndex[P]):
    """Base class of the indices of this package (MIGRATION_PLAN §3.2).

    It adds two helpers to :class:`~sivin.analytics.base.ClimateIndex`: building an
    :class:`~sivin.analytics.base.IndexResult` from a day selection, and restricting a
    selection to days whose humidity is complete as well (for dew point and VPD).
    """

    def _result(
        self,
        ctx: IndexContext,
        selection: SeasonDays,
        value: float | None,
        *,
        classification: str | None = None,
        daily: pd.Series | None = None,
        details: Mapping[str, float | int | str] | None = None,
    ) -> IndexResult:
        """Assemble the result of this index.

        Parameters
        ----------
        ctx : IndexContext
            Input of :meth:`compute`.
        selection : SeasonDays
            The days the value was computed from; gives coverage and completeness.
        value : float or None
            Index value in :attr:`unit`; ``None`` when there was no usable day.
        classification : str, optional
            Class label.
        daily : pandas.Series, optional
            Daily or cumulative curve indexed by local date.
        details : Mapping, optional
            Additional numbers; ``n_days`` (number of days used) is always added. Entries that
            are ``NaN`` or infinite are omitted, so the details are always valid JSON.

        Returns
        -------
        IndexResult
            The result.
        """
        return IndexResult(
            index_id=self.index_id,
            sensor_id=ctx.sensor_id,
            year=ctx.year,
            value=value,
            unit=self.unit,
            coverage=selection.coverage,
            complete=selection.complete,
            classification=classification,
            daily=daily,
            details={"n_days": len(selection.days), **_finite(details or {})},
        )

    @staticmethod
    def _with_complete_humidity(ctx: IndexContext, selection: SeasonDays) -> SeasonDays:
        """Keep only the days whose humidity coverage also reaches ``min_daily_coverage``.

        Parameters
        ----------
        ctx : IndexContext
            Input of :meth:`compute`.
        selection : SeasonDays
            Days with complete temperature.

        Returns
        -------
        SeasonDays
            Days with complete temperature and humidity; coverage recomputed on the same period.
        """
        frame = selection.days.frame
        kept = frame.loc[frame["rh_coverage"] >= ctx.min_daily_coverage]
        days = DailyWeather(ctx.sensor_id, kept, ctx.timezone)
        coverage = len(days) / selection.n_period_days
        return replace(
            selection,
            days=days,
            coverage=coverage,
            complete=coverage >= ctx.min_season_coverage,
        )


def nan_to_none(value: float) -> float | None:
    """Return ``None`` for ``NaN`` (no usable data), the value otherwise.

    Parameters
    ----------
    value : float
        A computed figure in any unit.

    Returns
    -------
    float or None
        ``value``, or ``None`` if it is ``NaN``.
    """
    return None if math.isnan(value) else value


def count_non_positive_humidity(
    ctx: IndexContext,
    temp_c: npt.NDArray[np.float64],
    rh_pct: npt.NDArray[np.float64],
    days: list[date],
    quantity: str,
) -> int:
    """Count (and log) valid samples on the given days whose humidity is ``<= 0 %``.

    Such values are sensor artefacts; the humidity-based indices treat them as invalid.

    Parameters
    ----------
    ctx : IndexContext
        Input of :meth:`compute`.
    temp_c, rh_pct : numpy.ndarray of float
        Masked temperature (°C) and humidity (%) per row (``NaN`` = not valid).
    days : list of datetime.date
        Local days the index uses.
    quantity : str
        Name of the derived quantity for the log message, e.g. ``"dew point"``.

    Returns
    -------
    int
        Number of samples with valid temperature and ``RH <= 0 %`` on ``days``.
    """
    dates = LocalTimeConverter(ctx.timezone).local_dates(ctx.series.timestamps)
    in_days = dates.isin(set(days)).to_numpy()
    count = int((non_positive_humidity(rh_pct) & ~np.isnan(temp_c) & in_days).sum())
    if count:
        logger.warning(
            "Sensor %s: %d sample(s) with RH <= 0 %% are invalid and have no %s.",
            ctx.sensor_id,
            count,
            quantity,
        )
    return count


def _finite(details: Mapping[str, float | int | str]) -> dict[str, float | int | str]:
    """Drop ``NaN`` and infinite numbers from result details."""
    return {
        key: value
        for key, value in details.items()
        if isinstance(value, str) or math.isfinite(value)
    }
