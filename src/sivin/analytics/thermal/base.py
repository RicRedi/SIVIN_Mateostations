"""Common parameters and helpers of the thermal and phenology indices."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import ClassVar, Final

import pandas as pd
from pydantic import Field, field_validator

from sivin.analytics.base import ClimateIndex, IndexContext, IndexParams, IndexResult, SeasonDays
from sivin.analytics.thermal.daily_mean import DEFAULT_DAILY_MEAN, daily_mean_registry

logger = logging.getLogger(__name__)

STATUS_KEY: Final = "status"
"""Key of :attr:`IndexResult.details` explaining why ``value`` is ``None``."""

NO_COMPLETE_DAYS: Final = "no complete days in the period"
"""Status detail of a result without any complete day in its period."""


class ThermalParams(IndexParams):
    """Parameters shared by every index of this package."""

    daily_mean: str = Field(
        DEFAULT_DAILY_MEAN,
        description=(
            "Definition of the daily mean temperature (°C): 'minmax' = (T_max + T_min) / 2, "
            "the Winkler convention (Amerine and Winkler, 1944), or 'sample_mean' = mean of "
            "all valid samples of the local day."
        ),
    )

    @field_validator("daily_mean")
    @classmethod
    def _known_daily_mean(cls, name: str) -> str:
        if name not in daily_mean_registry:
            raise ValueError(
                f"Unknown daily mean definition {name!r}; "
                f"known: {', '.join(daily_mean_registry.names())}."
            )
        return name


class ThermalIndex[P: ThermalParams](ClimateIndex[P]):
    """Base of the indices of this package: daily means and uniform result building.

    Attributes
    ----------
    estimated : bool
        Class variable copied into :attr:`IndexResult.estimated`; ``True`` for indices whose
        output is orientational (uncalibrated model).
    """

    estimated: ClassVar[bool] = False

    def _mean_temp_c(self, selection: SeasonDays) -> pd.Series:
        """Return the daily mean temperature in °C of the selected days, ``NaN`` days dropped.

        Parameters
        ----------
        selection : SeasonDays
            Complete days of the period.

        Returns
        -------
        pandas.Series
            Mean temperature in °C per local date, by :attr:`ThermalParams.daily_mean`.
        """
        definition = daily_mean_registry.create(self.params.daily_mean)
        return definition.mean_temp_c(selection.days).dropna()

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
        """Build the :class:`IndexResult` of this index from a period selection.

        Parameters
        ----------
        ctx : IndexContext
            The input of :meth:`compute`.
        selection : SeasonDays
            The selection the value was computed from (gives coverage and completeness).
        value : float or None
            Index value in :attr:`unit`.
        classification : str, optional
            Class label.
        daily : pandas.Series, optional
            Daily or cumulative curve indexed by local date.
        details : Mapping, optional
            Additional values; ``n_days`` (number of complete days) is always added.

        Returns
        -------
        IndexResult
            The result.
        """
        all_details: dict[str, float | int | str] = {"n_days": len(selection.days)}
        all_details.update(details or {})
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
            details=all_details,
            estimated=self.estimated,
        )

    def _empty_result(self, ctx: IndexContext, selection: SeasonDays) -> IndexResult:
        """Return a result without value because the period has no usable day.

        Parameters
        ----------
        ctx : IndexContext
            The input of :meth:`compute`.
        selection : SeasonDays
            The (empty) selection.

        Returns
        -------
        IndexResult
            ``value=None`` with a status detail.
        """
        logger.info(
            "%s for sensor %s in %d: %s.", self.index_id, ctx.sensor_id, ctx.year, NO_COMPLETE_DAYS
        )
        return self._result(ctx, selection, None, details={STATUS_KEY: NO_COMPLETE_DAYS})
