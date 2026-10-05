"""Mean diurnal temperature range during ripening."""

from __future__ import annotations

import logging
from datetime import date
from typing import Self

from pydantic import Field, model_validator

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.ripening.common import RipeningIndex
from sivin.analytics.ripening.params import MonthDayValue, PeriodParams
from sivin.core.season import MonthDay, Season

logger = logging.getLogger(__name__)


class DtrRipeningParams(PeriodParams):
    """Parameters of :class:`DtrRipeningIndex`.

    The window is ``period_start..period_end`` or, when ``start_date`` is given (e.g. the
    modelled véraison date of a season), ``start_date..period_end`` of that year.
    """

    period_start: MonthDayValue = Field(
        MonthDay(8, 1),
        description=(
            "First day of the ripening window (MM-DD) when no start_date is given. "
            "Project default August 1 [to be tuned]."
        ),
    )
    period_end: MonthDayValue = Field(
        MonthDay(9, 30),
        description="Last day of the ripening window (MM-DD). Project default September 30 "
        "[to be tuned].",
    )
    start_date: date | None = Field(
        None,
        description=(
            "Explicit first day of the window (date), e.g. the modelled véraison; overrides "
            "period_start and must lie in the computed season year, not after period_end."
        ),
    )

    @model_validator(mode="after")
    def _start_before_end(self) -> Self:
        if self.start_date is not None:
            start = MonthDay(self.start_date.month, self.start_date.day)
            if self.period_end < start:
                raise ValueError(
                    f"start_date {self.start_date} is after period_end {self.period_end}"
                )
        return self

    def window(self, year: int) -> Season:
        """Return the ripening window for a season year.

        Parameters
        ----------
        year : int
            The season year.

        Returns
        -------
        Season
            ``start_date..period_end`` if ``start_date`` is set, else the configured period.

        Raises
        ------
        ValueError
            If ``start_date`` is set and lies in another year.
        """
        if self.start_date is None:
            return self.season
        if self.start_date.year != year:
            raise ValueError(f"start_date {self.start_date} does not lie in season year {year}.")
        return Season(MonthDay(self.start_date.month, self.start_date.day), self.period_end)


@index_registry.register
class DtrRipeningIndex(RipeningIndex[DtrRipeningParams]):
    """Mean diurnal temperature range ``T_max - T_min`` over the ripening window.

    Value in °C over the complete days of the window; ``daily`` holds the daily ranges.
    """

    index_id = "dtr_ripening"
    unit = "°C"
    params_model = DtrRipeningParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the index; see the class docstring.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and season year.

        Returns
        -------
        IndexResult
            Mean daily range in °C, ``None`` without any complete day.

        Raises
        ------
        ValueError
            If ``start_date`` lies outside ``ctx.year``.
        """
        window = self.params.window(ctx.year)
        selection = self._season_days(ctx, window)
        frame = selection.days.frame
        range_c = frame["temp_max"] - frame["temp_min"]
        first, last = window.dates(ctx.year)
        details = {"window_start": first.isoformat(), "window_end": last.isoformat()}
        if range_c.empty:
            return self._result(ctx, selection, None, details=details)
        return self._result(
            ctx, selection, float(range_c.mean()), daily=range_c.rename("dtr_c"), details=details
        )
