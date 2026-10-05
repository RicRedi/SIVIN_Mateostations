"""Thermal-time phenology models: budburst, GFV (flowering, véraison) and GSR (sugar ripeness).

All three accumulate :math:`\\sum \\max(0, T_{mean} - T_{base})` from a start day with
:class:`~sivin.analytics.thermal.thermal_time.ThermalTimeModel` and predict a stage on the
first local date the sum reaches its critical value :math:`F^*`. They differ only in their
parameters and stages, so each one is a small subclass of :class:`ThermalTimePhenologyIndex`.
The predictions are orientational until calibrated against local BBCH observations.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import date
from itertools import pairwise
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.thermal.base import STATUS_KEY, ThermalIndex, ThermalParams
from sivin.analytics.thermal.thermal_time import ThermalTimeCurve, ThermalTimeModel
from sivin.core.season import MonthDay, Season

logger = logging.getLogger(__name__)

DAY_OF_YEAR_UNIT: Final = "DOY"
"""Unit of the phenology values: day of the year of the local date (January 1 = 1)."""

NOT_REACHED: Final = "not reached"
"""Detail value of a stage whose critical sum is not reached within the period and data."""

NOT_CONFIGURED: Final = "not configured"
"""Status detail of a model without any stage parameters."""

GFV_BASE_TEMP_C: Final = 0.0
"""Base temperature of the Grapevine Flowering Véraison model in °C (Parker et al., 2011)."""

GFV_START: Final = MonthDay(3, 1)
"""Start of the GFV accumulation, day of year 60 = March 1 in common years (Parker et al., 2011);
defined here as March 1 in every year."""

GFV_FLOWERING_F_STAR_C_D: Final = 1282.0
"""Critical sum for flowering of the general GFV model in °C·d (Parker et al., 2011)
[to be verified]."""

GFV_VERAISON_F_STAR_C_D: Final = 2528.0
"""Critical sum for véraison of the general GFV model in °C·d (Parker et al., 2011)
[to be verified]."""

GSR_BASE_TEMP_C: Final = 0.0
"""Base temperature of the Grapevine Sugar Ripeness model in °C (Parker et al., 2020)."""

GSR_START: Final = MonthDay(4, 1)
"""Start of the GSR accumulation, April 1 (day of year 91 in common years; Parker et al., 2020)."""

BUDBURST_BASE_TEMP_C: Final = 5.0
"""Base temperature of the budburst model in °C; project default [to be verified]."""

BUDBURST_START: Final = MonthDay(1, 1)
"""Start of the budburst accumulation; project default, not from literature."""

BUDBURST_END: Final = MonthDay(6, 30)
"""End of the budburst prediction period; project default, not from literature."""

SEASON_END: Final = MonthDay(10, 31)
"""End of the GFV and GSR prediction period; project default (end of the vegetation season)."""


class PhenologyStage(BaseModel):
    """A stage predicted when the thermal sum reaches its critical value.

    Attributes
    ----------
    label : str
        Machine-readable stage name, used as prefix of the result details.
    f_star_c_d : float
        Critical thermal sum :math:`F^*` in °C·d.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(
        min_length=1, pattern=r"^[a-z0-9_]+$", description="Stage name (lower-case, no unit)."
    )
    f_star_c_d: float = Field(gt=0.0, description="Critical thermal sum F* in °C·d.")


class PhenologyParams(ThermalParams):
    """Parameters shared by the thermal-time phenology models."""

    base_temp_c: float = Field(description="Base temperature in °C.")
    period: Season = Field(
        description="Prediction period: accumulation starts on its first day; stages not "
        "reached by its last day are 'not reached'."
    )


class ThermalTimePhenologyIndex[P: PhenologyParams](ThermalIndex[P]):
    """Predicts the dates of stages from a thermal-time sum (see the module docstring).

    The value is the day of the year of the **last** stage of :meth:`stages` (``None`` if it
    is not reached or no stage is configured). Coverage and completeness refer to the days
    from the period start until that stage, or until the period end if it is not reached.
    ``daily`` is the cumulative sum in °C·d.
    """

    unit = DAY_OF_YEAR_UNIT

    @abstractmethod
    def stages(self) -> tuple[PhenologyStage, ...]:
        """Return the stages to predict, in phenological order.

        Returns
        -------
        tuple of PhenologyStage
            Stages with their critical sums; empty if the model is not configured.
        """

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Predict the stage dates of ``ctx.year``.

        Parameters
        ----------
        ctx : IndexContext
            Data and metadata of one sensor and one season year.

        Returns
        -------
        IndexResult
            Day of year of the last stage, per-stage dates in ``details``, cumulative curve.
        """
        period = self.params.period
        selection = self._season_days(ctx, period)
        stages = self.stages()
        if not stages:
            return self._result(ctx, selection, None, details={STATUS_KEY: NOT_CONFIGURED})
        mean_temp_c = self._mean_temp_c(selection)
        if mean_temp_c.empty:
            return self._empty_result(ctx, selection)
        curve = ThermalTimeModel(self.params.base_temp_c).accumulate(mean_temp_c)
        reached = {stage.label: curve.date_reached(stage.f_star_c_d) for stage in stages}
        details = _stage_details(stages, reached, curve)
        last_date = reached[stages[-1].label]
        if last_date is None:
            details[STATUS_KEY] = f"{stages[-1].label} {NOT_REACHED}"
            return self._result(ctx, selection, None, daily=curve.cumulative_c_d, details=details)
        selection = self._season_days(ctx, Season(period.start, _month_day(last_date)))
        value_doy = float(_day_of_year(last_date))
        return self._result(ctx, selection, value_doy, daily=curve.cumulative_c_d, details=details)


def _check_increasing(stages: tuple[PhenologyStage, ...]) -> None:
    sums_c_d = [stage.f_star_c_d for stage in stages]
    if any(later <= earlier for earlier, later in pairwise(sums_c_d)):
        raise ValueError(f"Critical sums must increase in stage order, got {sums_c_d}.")
    labels = [stage.label for stage in stages]
    if len(set(labels)) != len(labels):
        raise ValueError(f"Stage labels must be unique, got {labels}.")


def _month_day(day: date) -> MonthDay:
    return MonthDay(day.month, day.day)


def _day_of_year(day: date) -> int:
    return day.timetuple().tm_yday


def _stage_details(
    stages: tuple[PhenologyStage, ...],
    reached: dict[str, date | None],
    curve: ThermalTimeCurve,
) -> dict[str, float | int | str]:
    details: dict[str, float | int | str] = {"thermal_sum_c_d": curve.total_c_d}
    for stage in stages:
        day = reached[stage.label]
        details[f"{stage.label}_f_star_c_d"] = stage.f_star_c_d
        details[f"{stage.label}_date"] = NOT_REACHED if day is None else day.isoformat()
        if day is not None:
            details[f"{stage.label}_doy"] = _day_of_year(day)
    return details


class BudburstParams(PhenologyParams):
    """Parameters of :class:`BudburstIndex`; no value is claimed from literature."""

    base_temp_c: float = Field(
        BUDBURST_BASE_TEMP_C,
        description="Base temperature in °C; project default [to be verified] (models compared "
        "by García de Cortázar-Atauri et al., 2009, use various bases).",
    )
    period: Season = Field(
        default_factory=lambda: Season(BUDBURST_START, BUDBURST_END),
        description="Prediction period (local dates); January 1 - June 30 is a project default.",
    )
    f_star_c_d: float | None = Field(
        None,
        gt=0.0,
        description="Critical thermal sum for budburst in °C·d; no default (needs local "
        "calibration). Without it the result is 'not configured'.",
    )


@index_registry.register
class BudburstIndex(ThermalTimePhenologyIndex[BudburstParams]):
    """Orientational budburst date from a thermal-time sum (``estimated=True``)."""

    index_id = "budburst"
    params_model = BudburstParams
    estimated = True

    def stages(self) -> tuple[PhenologyStage, ...]:
        """Return the budburst stage if :attr:`BudburstParams.f_star_c_d` is set."""
        f_star_c_d = self.params.f_star_c_d
        if f_star_c_d is None:
            return ()
        return (PhenologyStage(label="budburst", f_star_c_d=f_star_c_d),)


class GfvParams(PhenologyParams):
    """Parameters of :class:`GfvIndex` (general model of Parker et al., 2011)."""

    base_temp_c: float = Field(
        GFV_BASE_TEMP_C, description="Base temperature in °C (Parker et al., 2011)."
    )
    period: Season = Field(
        default_factory=lambda: Season(GFV_START, SEASON_END),
        description="Prediction period; starts March 1 (day of year 60 in common years, Parker "
        "et al., 2011); the end, October 31, is a project default.",
    )
    flowering_f_star_c_d: float = Field(
        GFV_FLOWERING_F_STAR_C_D,
        gt=0.0,
        description="Critical sum for flowering in °C·d, general model of Parker et al. (2011) "
        "[to be verified]; cultivar values in Parker et al. (2013).",
    )
    veraison_f_star_c_d: float = Field(
        GFV_VERAISON_F_STAR_C_D,
        gt=0.0,
        description="Critical sum for véraison in °C·d, general model of Parker et al. (2011) "
        "[to be verified]; cultivar values in Parker et al. (2013).",
    )

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        _check_increasing(GfvIndex.stages_of(self))
        return self


@index_registry.register
class GfvIndex(ThermalTimePhenologyIndex[GfvParams]):
    """Grapevine Flowering Véraison model: value = day of year of véraison."""

    index_id = "gfv"
    params_model = GfvParams

    def stages(self) -> tuple[PhenologyStage, ...]:
        """Return flowering and véraison with their critical sums."""
        return self.stages_of(self.params)

    @staticmethod
    def stages_of(params: GfvParams) -> tuple[PhenologyStage, ...]:
        """Return the flowering and véraison stages defined by a parameter set.

        Parameters
        ----------
        params : GfvParams
            The parameters.

        Returns
        -------
        tuple of PhenologyStage
            Flowering and véraison, in this order.
        """
        return (
            PhenologyStage(label="flowering", f_star_c_d=params.flowering_f_star_c_d),
            PhenologyStage(label="veraison", f_star_c_d=params.veraison_f_star_c_d),
        )


class GsrParams(PhenologyParams):
    """Parameters of :class:`GsrIndex`; no cultivar value is shipped."""

    base_temp_c: float = Field(
        GSR_BASE_TEMP_C, description="Base temperature in °C (Parker et al., 2020)."
    )
    period: Season = Field(
        default_factory=lambda: Season(GSR_START, SEASON_END),
        description="Prediction period; starts April 1 (Parker et al., 2020); the end, "
        "October 31, is a project default.",
    )
    targets: tuple[PhenologyStage, ...] = Field(
        (),
        description="Sugar targets as (label, F* in °C·d) for the cultivar of the sensor, e.g. "
        "label 'sugar_200_g_l', from Parker et al. (2020); none shipped. The value is the "
        "day of year of the last target.",
    )

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        _check_increasing(self.targets)
        return self


@index_registry.register
class GsrIndex(ThermalTimePhenologyIndex[GsrParams]):
    """Grapevine Sugar Ripeness model: value = day of year of the last configured target."""

    index_id = "gsr"
    params_model = GsrParams

    def stages(self) -> tuple[PhenologyStage, ...]:
        """Return the configured sugar targets (empty by default)."""
        return self.params.targets
