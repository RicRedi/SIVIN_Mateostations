"""Winter freeze: days with a damaging minimum temperature in the dormant season."""

from __future__ import annotations

from dataclasses import replace
from typing import Final, Self

import pandas as pd
from pydantic import Field, model_validator

from sivin.analytics.base import IndexContext, IndexParams, IndexResult, SeasonDays, index_registry
from sivin.analytics.ripening.common import RipeningIndex
from sivin.analytics.ripening.params import MonthDayValue
from sivin.analytics.ripening.thresholds import Comparison, Threshold
from sivin.core.daily import DailyWeather
from sivin.core.season import MonthDay, Season

NEW_YEARS_EVE: Final = MonthDay(12, 31)
"""Last day of the autumn part of the dormant season."""

NEW_YEARS_DAY: Final = MonthDay(1, 1)
"""First day of the spring part of the dormant season."""

STATUS_PREVIOUS_AUTUMN_MISSING: Final = "previous_autumn_missing"
"""``details["status"]`` when the autumn part of the winter has no complete day."""


class WinterFreezeParams(IndexParams):
    """Parameters of :class:`WinterFreezeIndex`.

    The dormant season crosses New Year: it runs from ``dormant_start`` of the previous year to
    ``dormant_end`` of the season year (the winter **ending** in the season year).
    """

    dormant_start: MonthDayValue = Field(
        MonthDay(11, 1),
        description="First day of the dormant season in the previous year (MM-DD); "
        "November 1, project default [to be tuned].",
    )
    dormant_end: MonthDayValue = Field(
        MonthDay(3, 31),
        description="Last day of the dormant season in the season year (MM-DD); "
        "March 31, project default [to be tuned].",
    )
    damage_threshold_c: float = Field(
        -15.0,
        description="Winter-injury threshold in °C (daily T_min below it). Plan §3.2 default "
        "[to be verified]; background Zabadal et al. (2007).",
    )
    severe_threshold_c: float = Field(
        -20.0,
        description="Severe winter-injury threshold in °C (daily T_min below it). Plan §3.2 "
        "default [to be verified]; background Zabadal et al. (2007).",
    )

    @model_validator(mode="after")
    def _valid_window(self) -> Self:
        if not self.dormant_end < self.dormant_start:
            raise ValueError("the dormant season must cross New Year (dormant_end < dormant_start)")
        if self.damage_threshold_c < self.severe_threshold_c:
            raise ValueError("severe_threshold_c must not be above damage_threshold_c")
        return self

    @property
    def autumn(self) -> Season:
        """Part of the dormant season in the previous year (``dormant_start``..Dec 31)."""
        return Season(self.dormant_start, NEW_YEARS_EVE)

    @property
    def spring(self) -> Season:
        """Part of the dormant season in the season year (Jan 1..``dormant_end``)."""
        return Season(NEW_YEARS_DAY, self.dormant_end)


@index_registry.register
class WinterFreezeIndex(RipeningIndex[WinterFreezeParams]):
    """Number of days with ``T_min < damage_threshold_c`` in the winter ending in the season year.

    Example: season 2026 covers 2025-11-01 .. 2026-03-31. Only complete days count. The value
    is the number of damage days; ``details`` adds ``severe_days`` and ``min_temp_c``; ``daily``
    holds the daily minima of the winter.

    The autumn part comes from the previous calendar year, so ``ctx.daily`` must contain it.
    When it has no complete day (e.g. the context was built from season-year data only, or the
    sensor started in winter), the value is ``None`` and ``details["status"]`` is
    :data:`STATUS_PREVIOUS_AUTUMN_MISSING`: a count over half a winter would look like a mild
    winter.
    """

    index_id = "winter_freeze"
    unit = "d"
    params_model = WinterFreezeParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the index; see the class docstring.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor; ``ctx.year`` is the year in which the winter ends.

        Returns
        -------
        IndexResult
            Number of damage days (d), ``None`` without any complete day or without a complete
            day in the previous autumn.
        """
        autumn = self._season_days(replace(ctx, year=ctx.year - 1), self.params.autumn)
        spring = self._season_days(ctx, self.params.spring)
        selection = _joined(ctx, autumn, spring)
        temp_min_c = selection.days.frame["temp_min"]
        if temp_min_c.empty:
            return self._result(ctx, selection, None)
        if len(autumn.days) == 0:
            return self._result(
                ctx, selection, None, details={"status": STATUS_PREVIOUS_AUTUMN_MISSING}
            )
        values = temp_min_c.to_numpy()
        damage = Threshold(Comparison.LT, self.params.damage_threshold_c)
        severe = Threshold(Comparison.LT, self.params.severe_threshold_c)
        damage_days = int(damage.holds(values).sum())
        details: dict[str, float | int | str] = {
            "severe_days": int(severe.holds(values).sum()),
            "min_temp_c": float(values.min()),
        }
        return self._result(ctx, selection, float(damage_days), daily=temp_min_c, details=details)


def _joined(ctx: IndexContext, autumn: SeasonDays, spring: SeasonDays) -> SeasonDays:
    """Complete days of both parts of the dormant season, with joint coverage."""
    frame = pd.concat([autumn.days.frame, spring.days.frame])
    n_period_days = autumn.n_period_days + spring.n_period_days
    coverage = len(frame) / n_period_days
    return SeasonDays(
        days=DailyWeather(ctx.sensor_id, frame, ctx.timezone),
        n_period_days=n_period_days,
        coverage=coverage,
        complete=coverage >= ctx.min_season_coverage,
    )
