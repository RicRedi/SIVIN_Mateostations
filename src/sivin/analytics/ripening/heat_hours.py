"""Duration-weighted hours in temperature bands (optimum, heat stress, extreme heat)."""

from __future__ import annotations

from typing import Final, Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import Field, model_validator

from sivin.analytics.base import IndexContext, IndexResult, SeasonDays, index_registry
from sivin.analytics.ripening.common import RipeningIndex
from sivin.analytics.ripening.durations import FloatArray, SampleDurations, masked_values
from sivin.analytics.ripening.params import MonthDayValue, PeriodParams, SampleDurationParams
from sivin.analytics.ripening.thresholds import Comparison, Threshold
from sivin.core.schema import Column
from sivin.core.season import MonthDay

BAND_COLUMNS: Final = ("optimum_h", "heat_stress_h", "extreme_heat_h", "observed_h")
"""Columns of :meth:`HeatHoursIndex.band_hours`, all in hours."""


class HeatHoursParams(PeriodParams):
    """Parameters of :class:`HeatHoursIndex`.

    The optimum band is ``optimum_min_c <= T <= optimum_max_c``; heat stress is
    ``T > heat_stress_c`` and extreme heat ``T > extreme_heat_c``.
    """

    period_start: MonthDayValue = Field(
        MonthDay(4, 1),
        description=(
            "First day of the period (MM-DD); April 1, growing season (Amerine & Winkler 1944)."
        ),
    )
    period_end: MonthDayValue = Field(
        MonthDay(10, 31),
        description=(
            "Last day of the period (MM-DD); October 31, growing season (Amerine & Winkler 1944)."
        ),
    )
    optimum_min_c: float = Field(
        20.0,
        description="Lower bound of the optimum band in °C (inclusive). Project default "
        "(plan §3.2), not a literature value.",
    )
    optimum_max_c: float = Field(
        30.0,
        description="Upper bound of the optimum band in °C (inclusive). Project default "
        "(plan §3.2), not a literature value.",
    )
    heat_stress_c: float = Field(
        30.0,
        description="Heat-stress threshold in °C (T above it). Project default (plan §3.2); "
        "light-saturated leaf photosynthesis of Semillon was optimal at 30 °C (Greer & Weedon "
        "2012, abstract).",
    )
    extreme_heat_c: float = Field(
        35.0,
        description="Extreme-heat threshold in °C (T above it). Project default (plan §3.2); "
        "a 35 °C daily maximum halved berry anthocyanins vs 25 °C (Mori et al. 2007, "
        "abstract).",
    )
    sampling: SampleDurationParams = Field(
        default_factory=SampleDurationParams,
        description="Time represented by one raw sample (s).",
    )

    @model_validator(mode="after")
    def _ordered_thresholds(self) -> Self:
        if not self.optimum_min_c < self.optimum_max_c:
            raise ValueError("optimum_min_c must be below optimum_max_c")
        if self.extreme_heat_c < self.heat_stress_c:
            raise ValueError("extreme_heat_c must not be below heat_stress_c")
        return self


@index_registry.register
class HeatHoursIndex(RipeningIndex[HeatHoursParams]):
    """Hours with temperatures in the optimum band, above heat stress and above extreme heat.

    Hours are duration-weighted (:class:`~sivin.analytics.ripening.durations.SampleDurations`)
    and counted on the complete days of the period only. The value is the heat-stress hours;
    ``daily`` holds them per day and ``details`` all bands (``optimum_h``, ``heat_stress_h``,
    ``extreme_heat_h``) plus the observed hours (``observed_h``).
    """

    index_id = "heat_hours"
    unit = "h"
    params_model = HeatHoursParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the index; see the class docstring.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and season year.

        Returns
        -------
        IndexResult
            Heat-stress hours (h), ``None`` without any complete day.
        """
        selection = self._season_days(ctx, self.params.season)
        if len(selection.days) == 0:
            return self._result(ctx, selection, None)
        bands = self.band_hours(ctx, selection)
        totals = {column: float(bands[column].sum()) for column in BAND_COLUMNS}
        return self._result(
            ctx, selection, totals["heat_stress_h"], daily=bands["heat_stress_h"], details=totals
        )

    def band_hours(self, ctx: IndexContext, selection: SeasonDays) -> pd.DataFrame:
        """Return the hours of every band per complete day.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and season year.
        selection : SeasonDays
            The complete days of the period.

        Returns
        -------
        pandas.DataFrame
            Columns :data:`BAND_COLUMNS` (h), indexed by local date.
        """
        params = self.params
        durations = SampleDurations(params.sampling, ctx.timezone)
        temp_c = masked_values(ctx.series, Column.TEMP, ctx.exclude_mask)
        optimum_low = Threshold(Comparison.GE, params.optimum_min_c)
        optimum_high = Threshold(Comparison.LE, params.optimum_max_c)
        heat = Threshold(Comparison.GT, params.heat_stress_c)
        extreme = Threshold(Comparison.GT, params.extreme_heat_c)
        conditions = {
            "optimum_h": lambda t: optimum_low.holds(t) & optimum_high.holds(t),
            "heat_stress_h": heat.holds,
            "extreme_heat_h": extreme.holds,
            "observed_h": _always,
        }
        pieces = durations.pieces(ctx.series, temp_c)
        days = selection.days.dates
        return pd.DataFrame(
            {
                column: durations.sum_hours(pieces, condition, days)
                for column, condition in conditions.items()
            },
            columns=list(BAND_COLUMNS),
        )


def _always(values: FloatArray) -> npt.NDArray[np.bool_]:
    """Condition that holds for every (valid) value."""
    return np.ones(values.shape, dtype=np.bool_)
