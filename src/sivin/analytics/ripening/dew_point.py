"""Mean dew point and dew-point depression over a period (Magnus form)."""

from __future__ import annotations

import pandas as pd
from pydantic import Field

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.ripening.common import (
    RipeningIndex,
    count_non_positive_humidity,
    nan_to_none,
)
from sivin.analytics.ripening.durations import SampleDurations, masked_values
from sivin.analytics.ripening.params import MonthDayValue, PeriodParams, SampleDurationParams
from sivin.analytics.ripening.psychrometry import (
    ALDUCHOV_ESKRIDGE_1996,
    MagnusCoefficients,
    dew_point_c,
)
from sivin.core.schema import Column
from sivin.core.season import MonthDay


class DewPointParams(PeriodParams):
    """Parameters of :class:`DewPointIndex`.

    The legacy ``vineyard_analyst.py`` used ``magnus_a = 17.27``, ``magnus_b_c = 237.7``.
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
    magnus_a: float = Field(
        ALDUCHOV_ESKRIDGE_1996.a,
        gt=0.0,
        description="Magnus coefficient a (dimensionless); 17.625 (Alduchov & Eskridge 1996).",
    )
    magnus_b_c: float = Field(
        ALDUCHOV_ESKRIDGE_1996.b_c,
        gt=0.0,
        description="Magnus coefficient b in °C; 243.04 (Alduchov & Eskridge 1996).",
    )

    sampling: SampleDurationParams = Field(
        default_factory=SampleDurationParams,
        description="Time represented by one raw sample (s), the weight of the daily means.",
    )

    @property
    def coefficients(self) -> MagnusCoefficients:
        """The Magnus coefficients as a value object."""
        return MagnusCoefficients(a=self.magnus_a, b_c=self.magnus_b_c)


@index_registry.register
class DewPointIndex(RipeningIndex[DewPointParams]):
    """Mean dew point and mean dew-point depression ``T - T_d`` over a period.

    Per valid sample (temperature and humidity present and not excluded) the dew point is
    computed with :func:`~sivin.analytics.ripening.psychrometry.dew_point_c`; samples with
    ``RH <= 0`` give no dew point and are counted in ``details["n_rh_non_positive"]``. Daily
    means are weighted by the time each sample represents
    (:meth:`~sivin.analytics.ripening.durations.SampleDurations.daily_means`); the value is the
    mean of the daily means over days whose temperature **and** humidity coverage are
    complete. ``daily`` holds the daily
    mean dew point, ``details["mean_depression_c"]`` the mean daily depression.
    """

    index_id = "dew_point"
    unit = "°C"
    params_model = DewPointParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the index; see the class docstring.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and season year.

        Returns
        -------
        IndexResult
            Mean dew point in °C, ``None`` without any complete day.
        """
        selection = self._with_complete_humidity(ctx, self._season_days(ctx, self.params.season))
        if len(selection.days) == 0:
            return self._result(ctx, selection, None)
        temp_c = masked_values(ctx.series, Column.TEMP, ctx.exclude_mask)
        rh_pct = masked_values(ctx.series, Column.RH, ctx.exclude_mask)
        dew_c = dew_point_c(temp_c, rh_pct, self.params.coefficients)
        days = selection.days.dates
        durations = SampleDurations(self.params.sampling, ctx.timezone)
        daily = pd.DataFrame(
            {
                "dew_point_c": durations.daily_means(ctx.series, dew_c, days),
                "depression_c": durations.daily_means(ctx.series, temp_c - dew_c, days),
            }
        )
        n_rh_non_positive = count_non_positive_humidity(ctx, temp_c, rh_pct, days, "dew point")
        return self._result(
            ctx,
            selection,
            nan_to_none(float(daily["dew_point_c"].mean())),
            daily=daily["dew_point_c"],
            details={
                "mean_depression_c": float(daily["depression_c"].mean()),
                "n_rh_non_positive": n_rh_non_positive,
                "magnus_a": self.params.magnus_a,
                "magnus_b_c": self.params.magnus_b_c,
            },
        )
