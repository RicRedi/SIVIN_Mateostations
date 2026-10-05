"""Cool Night Index (Tonietto and Carbonneau, 2004)."""

from __future__ import annotations

from typing import Final

from pydantic import Field

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.ripening.common import RipeningIndex
from sivin.analytics.ripening.params import MonthDayValue, PeriodParams
from sivin.analytics.ripening.thresholds import UpperBoundClasses
from sivin.core.season import MonthDay

SEPTEMBER: Final = 9
"""Month of the Cool Night Index in the northern hemisphere (Tonietto and Carbonneau, 2004)."""

COOL_NIGHT_CLASSES: Final = UpperBoundClasses(
    bounds=(
        (12.0, "very_cool_nights"),
        (14.0, "cool_nights"),
        (18.0, "temperate_nights"),
    ),
    top_label="warm_nights",
)
"""Classes of the Cool Night Index in °C (Tonietto and Carbonneau, 2004, CI classes).

CI+2 very cool nights ``CI <= 12``, CI+1 cool nights ``12 < CI <= 14``, CI-1 temperate nights
``14 < CI <= 18``, CI-2 warm nights ``CI > 18``. Which side of each boundary is inclusive is
``[to be verified]`` against the original table.
"""


class CoolNightParams(PeriodParams):
    """Parameters of :class:`CoolNightIndex`."""

    period_start: MonthDayValue = Field(
        MonthDay(SEPTEMBER, 1),
        description="First day of the period (MM-DD); September 1 (Tonietto & Carbonneau 2004).",
    )
    period_end: MonthDayValue = Field(
        MonthDay(SEPTEMBER, 30),
        description="Last day of the period (MM-DD); September 30 (Tonietto & Carbonneau 2004).",
    )


@index_registry.register
class CoolNightIndex(RipeningIndex[CoolNightParams]):
    """Cool Night Index: mean of the daily minimum temperatures in September.

    Value in °C over the complete days of the period, classified with
    :data:`COOL_NIGHT_CLASSES`; ``daily`` holds the daily minima used.
    """

    index_id = "cool_night"
    unit = "°C"
    params_model = CoolNightParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the index; see the class docstring.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and season year.

        Returns
        -------
        IndexResult
            Mean daily minimum in °C, ``None`` without any complete day.
        """
        selection = self._season_days(ctx, self.params.season)
        temp_min_c = selection.days.frame["temp_min"]
        if temp_min_c.empty:
            return self._result(ctx, selection, None)
        value = float(temp_min_c.mean())
        return self._result(
            ctx,
            selection,
            value,
            classification=COOL_NIGHT_CLASSES.classify(value),
            daily=temp_min_c,
        )
