"""Frost hours and frost nights in the growing season, optionally after budburst."""

from __future__ import annotations

from datetime import date
from typing import Self

import pandas as pd
from pydantic import Field, model_validator

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.ripening.common import RipeningIndex
from sivin.analytics.ripening.durations import SampleDurations, masked_values
from sivin.analytics.ripening.params import MonthDayValue, PeriodParams, SampleDurationParams
from sivin.analytics.ripening.thresholds import Comparison, Threshold
from sivin.core.schema import Column
from sivin.core.season import MonthDay


class FrostParams(PeriodParams):
    """Parameters of :class:`FrostIndex`.

    Frost is ``T <= frost_c`` and hard frost ``T <= hard_frost_c`` (raw samples); a frost night
    is a complete day with ``T_min < frost_c``, consistent with the ČHMÚ frost day.
    """

    period_start: MonthDayValue = Field(
        MonthDay(4, 1),
        description=(
            "First day of the period (MM-DD); April 1, growing season (Amerine & Winkler 1944). "
            "Project choice [to be tuned]."
        ),
    )
    period_end: MonthDayValue = Field(
        MonthDay(10, 31),
        description=(
            "Last day of the period (MM-DD); October 31, growing season (Amerine & Winkler "
            "1944). Project choice [to be tuned]."
        ),
    )
    frost_c: float = Field(
        0.0, description="Frost threshold in °C (T at or below it). Plan §3.2 default."
    )
    hard_frost_c: float = Field(
        -2.0,
        description="Hard-frost threshold in °C (T at or below it). Plan §3.2 default "
        "[to be verified]; stage-dependent critical temperatures: Poling (2008).",
    )
    after_date: date | None = Field(
        None,
        description=(
            "First day (date) from which frost is critical, e.g. the modelled budburst; "
            "must lie in the computed season year; None = no critical-frost figures."
        ),
    )
    sampling: SampleDurationParams = Field(
        default_factory=SampleDurationParams,
        description="Time represented by one raw sample (s).",
    )

    @model_validator(mode="after")
    def _ordered_thresholds(self) -> Self:
        if self.frost_c < self.hard_frost_c:
            raise ValueError("hard_frost_c must not be above frost_c")
        return self


@index_registry.register
class FrostIndex(RipeningIndex[FrostParams]):
    """Duration-weighted frost hours, frost nights and the absolute minimum.

    Hours come from :class:`~sivin.analytics.ripening.durations.SampleDurations` (time, not
    the number of rows as in the legacy ``frost_events_count``) and are counted on the complete
    days of the period. The value is the frost hours (``T <= frost_c``); ``daily`` holds them
    per day. ``details``: ``frost_h``, ``hard_frost_h``, ``frost_nights``, ``min_temp_c`` and,
    with ``after_date``, the same figures from that day on with the prefix ``critical_``.
    """

    index_id = "frost"
    unit = "h"
    params_model = FrostParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the index; see the class docstring.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and season year.

        Returns
        -------
        IndexResult
            Frost hours (h), ``None`` without any complete day.

        Raises
        ------
        ValueError
            If ``after_date`` lies outside ``ctx.year``.
        """
        params = self.params
        if params.after_date is not None and params.after_date.year != ctx.year:
            raise ValueError(
                f"after_date {params.after_date} does not lie in season year {ctx.year}."
            )
        selection = self._season_days(ctx, params.season)
        if len(selection.days) == 0:
            return self._result(ctx, selection, None)
        frost = Threshold(Comparison.LE, params.frost_c)
        hard_frost = Threshold(Comparison.LE, params.hard_frost_c)
        frost_night = Threshold(Comparison.LT, params.frost_c)
        durations = SampleDurations(params.sampling, ctx.timezone)
        pieces = durations.pieces(
            ctx.series, masked_values(ctx.series, Column.TEMP, ctx.exclude_mask)
        )
        temp_min_c = selection.days.frame["temp_min"]
        table = pd.DataFrame(
            {
                "frost_h": durations.sum_hours(pieces, frost.holds, selection.days.dates),
                "hard_frost_h": durations.sum_hours(pieces, hard_frost.holds, selection.days.dates),
                "frost_nights": pd.Series(
                    frost_night.holds(temp_min_c.to_numpy()), index=temp_min_c.index
                ),
                "temp_min": temp_min_c,
            }
        )
        totals = _summary(table)
        details: dict[str, float | int | str] = dict(totals)
        if params.after_date is not None:
            dates = pd.Series(table.index, index=table.index)
            critical = table.loc[dates >= params.after_date]
            details["after_date"] = params.after_date.isoformat()
            details.update({f"critical_{key}": value for key, value in _summary(critical).items()})
        return self._result(
            ctx, selection, float(totals["frost_h"]), daily=table["frost_h"], details=details
        )


def _summary(table: pd.DataFrame) -> dict[str, float | int]:
    """Totals of a per-day frost table (hours, number of frost nights, minimum in °C)."""
    summary: dict[str, float | int] = {
        "frost_h": float(table["frost_h"].sum()),
        "hard_frost_h": float(table["hard_frost_h"].sum()),
        "frost_nights": int(table["frost_nights"].sum()),
    }
    if not table.empty:
        summary["min_temp_c"] = float(table["temp_min"].min())
    return summary
