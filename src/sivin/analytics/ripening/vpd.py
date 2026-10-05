"""Vapour pressure deficit: daily maxima, hours above a threshold, optional daytime mean."""

from __future__ import annotations

from typing import Final, Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import Field, model_validator

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.ripening.common import (
    RipeningIndex,
    count_non_positive_humidity,
    nan_to_none,
)
from sivin.analytics.ripening.durations import FloatArray, SampleDurations, masked_values
from sivin.analytics.ripening.params import MonthDayValue, PeriodParams, SampleDurationParams
from sivin.analytics.ripening.psychrometry import vapour_pressure_deficit_kpa
from sivin.analytics.ripening.thresholds import Comparison, Threshold
from sivin.core.schema import Column
from sivin.core.season import MonthDay
from sivin.core.timeutil import LocalTimeConverter

HOURS_PER_DAY: Final = 24
"""Hours of a nominal day; upper bound of the daytime hours."""


class VpdParams(PeriodParams):
    """Parameters of :class:`VpdIndex`.

    The daytime mean is computed only when both ``daytime_start_hour`` and
    ``daytime_end_hour`` are given (local clock hours, ``start <= hour < end``).
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
    threshold_kpa: float = Field(
        2.0,
        gt=0.0,
        description="VPD threshold in kPa for the hours above it. Project default "
        "[to be tuned]; not taken from literature.",
    )
    daytime_start_hour: int | None = Field(
        None,
        ge=0,
        lt=HOURS_PER_DAY,
        description="First local clock hour (h, 0-23) of the daytime mean; None = no daytime mean.",
    )
    daytime_end_hour: int | None = Field(
        None,
        gt=0,
        le=HOURS_PER_DAY,
        description="Local clock hour (h, 1-24) at which the daytime window ends (exclusive).",
    )
    sampling: SampleDurationParams = Field(
        default_factory=SampleDurationParams,
        description="Time represented by one raw sample (s).",
    )

    @model_validator(mode="after")
    def _daytime_window(self) -> Self:
        start, end = self.daytime_start_hour, self.daytime_end_hour
        if (start is None) != (end is None):
            raise ValueError("give both daytime_start_hour and daytime_end_hour, or neither")
        if start is not None and end is not None and not start < end:
            raise ValueError("daytime_start_hour must be before daytime_end_hour")
        return self


@index_registry.register
class VpdIndex(RipeningIndex[VpdParams]):
    """Vapour pressure deficit (FAO-56) from temperature and humidity samples.

    Per valid sample VPD is computed with
    :func:`~sivin.analytics.ripening.psychrometry.vapour_pressure_deficit_kpa`. Only days whose
    temperature and humidity coverage are complete count. The value is the mean of the daily
    maxima (kPa); ``daily`` holds the daily maxima. ``details``: ``hours_above_threshold_h``
    (duration-weighted), ``max_vpd_kpa``, ``n_rh_non_positive`` (samples with ``RH <= 0 %``,
    invalid and logged) and, if configured, the duration-weighted ``mean_daytime_vpd_kpa``.
    """

    index_id = "vpd"
    unit = "kPa"
    params_model = VpdParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the index; see the class docstring.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and season year.

        Returns
        -------
        IndexResult
            Mean daily maximum VPD in kPa, ``None`` without any complete day.
        """
        params = self.params
        selection = self._with_complete_humidity(ctx, self._season_days(ctx, params.season))
        if len(selection.days) == 0:
            return self._result(ctx, selection, None)
        temp_c = masked_values(ctx.series, Column.TEMP, ctx.exclude_mask)
        rh_pct = masked_values(ctx.series, Column.RH, ctx.exclude_mask)
        vpd_kpa = vapour_pressure_deficit_kpa(temp_c, rh_pct)
        dates = LocalTimeConverter(ctx.timezone).local_dates(ctx.series.timestamps)
        days = selection.days.dates
        durations = SampleDurations(params.sampling, ctx.timezone)
        in_days = dates.isin(set(days)).to_numpy()
        daily_max = (
            pd.Series(vpd_kpa[in_days], name="vpd_max_kpa")
            .groupby(dates.to_numpy()[in_days])
            .max()
            .reindex(pd.Index(days, dtype=object, name="date"))
        )
        above = Threshold(Comparison.GT, params.threshold_kpa)
        hours_above = durations.hours_by_day(ctx.series, vpd_kpa, above.holds, days)
        details: dict[str, float | int | str] = {
            "hours_above_threshold_h": float(hours_above.sum()),
            "threshold_kpa": params.threshold_kpa,
            "n_rh_non_positive": count_non_positive_humidity(ctx, temp_c, rh_pct, days, "VPD"),
        }
        max_vpd = nan_to_none(float(daily_max.max()))
        if max_vpd is not None:
            details["max_vpd_kpa"] = max_vpd
        daytime_mean = self._daytime_mean_kpa(ctx, durations, vpd_kpa, in_days)
        if daytime_mean is not None:
            details["mean_daytime_vpd_kpa"] = daytime_mean
        return self._result(
            ctx,
            selection,
            nan_to_none(float(daily_max.mean())),
            daily=daily_max,
            details=details,
        )

    def _daytime_mean_kpa(
        self,
        ctx: IndexContext,
        durations: SampleDurations,
        vpd_kpa: FloatArray,
        in_days: npt.NDArray[np.bool_],
    ) -> float | None:
        """Duration-weighted mean VPD (kPa) of the daytime samples, if a window is configured."""
        start, end = self.params.daytime_start_hour, self.params.daytime_end_hour
        if start is None or end is None:
            return None
        hours = ctx.series.timestamps.dt.tz_convert(ctx.timezone).dt.hour.to_numpy()
        daytime = in_days & (hours >= start) & (hours < end)
        return nan_to_none(durations.weighted_mean(ctx.series, vpd_kpa, daytime))
