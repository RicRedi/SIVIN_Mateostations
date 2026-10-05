"""Shared base of the ripening and risk indices: result assembly and day selection."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace

import pandas as pd

from sivin.analytics.base import (
    ClimateIndex,
    IndexContext,
    IndexParams,
    IndexResult,
    SeasonDays,
)
from sivin.core.daily import DailyWeather


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
            Additional numbers; ``n_days`` (number of days used) is always added.

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
            details={"n_days": len(selection.days), **(details or {})},
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
