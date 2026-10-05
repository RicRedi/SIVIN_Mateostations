"""Configurable model period of the disease models (a :class:`~sivin.core.season.Season`)."""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sivin.core.season import MonthDay, Season

_VEGETATION: Final = Season.vegetation()
"""Default period: April 1 - October 31 (growing season of the northern hemisphere)."""


class SeasonWindow(BaseModel):
    """First and last day of a model period, as month and day (both inclusive).

    The default is the grapevine growing season April 1 - October 31 of
    :meth:`sivin.core.season.Season.vegetation`; it is a project default for the disease models,
    which in the literature start at a phenological stage (budbreak, bloom) rather than at a
    calendar date.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_month: int = Field(
        _VEGETATION.start.month, ge=1, le=12, description="Month of the first day (1-12)."
    )
    start_day: int = Field(
        _VEGETATION.start.day, ge=1, le=31, description="Day of month of the first day (1-31)."
    )
    end_month: int = Field(
        _VEGETATION.end.month, ge=1, le=12, description="Month of the last day (1-12)."
    )
    end_day: int = Field(
        _VEGETATION.end.day, ge=1, le=31, description="Day of month of the last day (1-31)."
    )

    @model_validator(mode="after")
    def _valid_season(self) -> SeasonWindow:
        self.to_season()
        return self

    def to_season(self) -> Season:
        """Return the period as a :class:`~sivin.core.season.Season`.

        Returns
        -------
        Season
            The inclusive period.

        Raises
        ------
        ValueError
            If a month-day does not exist or the period crosses the new year.
        """
        return Season(
            MonthDay(self.start_month, self.start_day), MonthDay(self.end_month, self.end_day)
        )
