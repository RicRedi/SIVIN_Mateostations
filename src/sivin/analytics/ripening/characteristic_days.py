"""Characteristic days: tropical days and nights, summer, frost and ice days (ČHMÚ terms)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from pydantic import Field

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.ripening.common import RipeningIndex
from sivin.analytics.ripening.params import MonthDayValue, PeriodParams
from sivin.analytics.ripening.thresholds import Comparison, Threshold
from sivin.core.season import MonthDay

TROPICAL_DAYS: Final = "tropical_days"
"""Detail key of the number of tropical days (the index value)."""


@dataclass(frozen=True, slots=True)
class DayCategory:
    """A kind of day defined by a threshold on one daily aggregate, e.g. ``T_max >= 30 °C``.

    Parameters
    ----------
    name : str
        Key of the count in the result details, e.g. ``"tropical_days"``.
    column : str
        Daily aggregate tested: ``"temp_max"`` or ``"temp_min"`` (°C).
    threshold : Threshold
        The test, in °C.
    """

    name: str
    column: str
    threshold: Threshold

    def matches(self, days: pd.DataFrame) -> pd.Series:
        """Tell which days belong to the category.

        Parameters
        ----------
        days : pandas.DataFrame
            Daily aggregates (:attr:`~sivin.core.daily.DailyWeather.frame`).

        Returns
        -------
        pandas.Series of bool
            ``True`` for the days of this category, indexed like ``days``.
        """
        return pd.Series(self.threshold.holds(days[self.column].to_numpy()), index=days.index)


class CharacteristicDaysParams(PeriodParams):
    """Parameters of :class:`CharacteristicDaysIndex` (ČHMÚ climatological definitions)."""

    period_start: MonthDayValue = Field(
        MonthDay(1, 1),
        description="First day of the counting period (MM-DD); January 1 (calendar year).",
    )
    period_end: MonthDayValue = Field(
        MonthDay(12, 31),
        description="Last day of the counting period (MM-DD); December 31 (calendar year).",
    )
    tropical_day_tmax_c: float = Field(
        30.0, description="Tropical day: daily T_max >= this value, °C (ČHMÚ)."
    )
    tropical_night_tmin_c: float = Field(
        20.0, description="Tropical night: daily T_min >= this value, °C (ČHMÚ)."
    )
    summer_day_tmax_c: float = Field(
        25.0, description="Summer day: daily T_max >= this value, °C (ČHMÚ)."
    )
    frost_day_tmin_c: float = Field(
        0.0, description="Frost day: daily T_min < this value, °C (ČHMÚ)."
    )
    ice_day_tmax_c: float = Field(0.0, description="Ice day: daily T_max < this value, °C (ČHMÚ).")

    def categories(self) -> tuple[DayCategory, ...]:
        """Return the day categories defined by these parameters.

        Returns
        -------
        tuple of DayCategory
            Tropical days, tropical nights, summer days, frost days and ice days.
        """
        return (
            DayCategory(
                TROPICAL_DAYS, "temp_max", Threshold(Comparison.GE, self.tropical_day_tmax_c)
            ),
            DayCategory(
                "tropical_nights", "temp_min", Threshold(Comparison.GE, self.tropical_night_tmin_c)
            ),
            DayCategory(
                "summer_days", "temp_max", Threshold(Comparison.GE, self.summer_day_tmax_c)
            ),
            DayCategory("frost_days", "temp_min", Threshold(Comparison.LT, self.frost_day_tmin_c)),
            DayCategory("ice_days", "temp_max", Threshold(Comparison.LT, self.ice_day_tmax_c)),
        )


@index_registry.register
class CharacteristicDaysIndex(RipeningIndex[CharacteristicDaysParams]):
    """Counts of tropical days, tropical nights, summer, frost and ice days.

    Port of the legacy ``calculate_tropical_extremes`` extended by the other characteristic
    days. A "tropical night" uses the minimum of the local **calendar day** (00-24 h), not of
    the night, as the legacy script did. Only complete days of the period count. The value is
    the number of tropical days; ``details`` holds every count and ``daily`` the cumulative
    number of tropical days.
    """

    index_id = "tropical_days_nights"
    unit = "d"
    params_model = CharacteristicDaysParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the index; see the class docstring.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and season year.

        Returns
        -------
        IndexResult
            Number of tropical days (d), ``None`` without any complete day.
        """
        selection = self._season_days(ctx, self.params.season)
        frame = selection.days.frame
        if frame.empty:
            return self._result(ctx, selection, None)
        matches = {category.name: category.matches(frame) for category in self.params.categories()}
        counts = {name: int(match.sum()) for name, match in matches.items()}
        cumulative = matches[TROPICAL_DAYS].cumsum().astype(np.float64).rename(TROPICAL_DAYS)
        return self._result(
            ctx, selection, float(counts[TROPICAL_DAYS]), daily=cumulative, details=counts
        )
