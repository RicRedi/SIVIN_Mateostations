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
from collections.abc import Mapping
from datetime import date
from itertools import pairwise
from types import MappingProxyType
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sivin.analytics.base import IndexContext, IndexResult, SeasonDays, index_registry
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

START_NOT_COVERED: Final = "accumulation start not covered"
"""Status detail when the first days of the accumulation period are missing."""

MISSING_AT_START_KEY: Final = "n_missing_days_at_start"
"""Detail key: days from the period start to the first complete day."""

DEFAULT_MAX_MISSING_DAYS_AT_START: Final = 0
"""Project default of ``max_missing_days_at_start`` (not from literature; to be tuned)."""

GFV_BASE_TEMP_C: Final = 0.0
"""Base temperature of the Grapevine Flowering Véraison model in °C (Parker et al., 2011)."""

GFV_START: Final = MonthDay(3, 1)
"""Start of the GFV accumulation, day of year 60 = March 1 in common years (Parker et al., 2011);
defined here as March 1 in every year."""

GSR_BASE_TEMP_C: Final = 0.0
"""Base temperature of the Grapevine Sugar Ripeness model in °C (Parker et al., 2020)."""

GSR_START: Final = MonthDay(4, 1)
"""Start of the GSR accumulation, April 1 (day of year 91 in common years; Parker et al., 2020)."""


BUDBURST_BASE_TEMP_C: Final = 5.0
"""Base temperature of the budburst model in °C; project default [to be verified].

A 5 °C base with accumulation from January 1 is one of the forcing-only (GDD) variants found in
the budburst literature, but the source of that variant could not be confirmed
(docs/literature-verification.md)."""

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


GSR_CULTIVAR_PRESETS: Final[Mapping[str, tuple[PhenologyStage, ...]]] = MappingProxyType(
    {
        "sauvignon_blanc": (PhenologyStage(label="sugar_200_g_l", f_star_c_d=2820.0),),
    }
)
"""Optional GSR sugar targets per cultivar (read-only); **not active** unless configured.

F* in °C·d to 200 g/L sugar (base 0 °C, from April 1) of Parker et al. (2020), as quoted by
Ausseil et al. (2021, Frontiers in Plant Science 12, 618039); the table of the primary paper
was not read. Only values confirmed in that way are listed (docs/literature-verification.md);
use ``GsrParams(targets=GSR_CULTIVAR_PRESETS["sauvignon_blanc"])`` to apply one."""


class PhenologyParams(ThermalParams):
    """Parameters shared by the thermal-time phenology models."""

    base_temp_c: float = Field(description="Base temperature in °C.")
    period: Season = Field(
        description="Prediction period: accumulation starts on its first day; stages not "
        "reached by its last day are 'not reached'."
    )
    max_missing_days_at_start: int = Field(
        DEFAULT_MAX_MISSING_DAYS_AT_START,
        ge=0,
        description="Maximum number of incomplete days (d) at the start of the period before "
        "the first complete day; more means the accumulation start is not covered (e.g. late "
        "deployment) and no date is predicted. Project default 0, to be tuned.",
    )


class ThermalTimePhenologyIndex[P: PhenologyParams](ThermalIndex[P]):
    """Predicts the dates of stages from a thermal-time sum (see the module docstring).

    The value is the day of the year of the **last** stage of :meth:`stages`, its local date
    is ``details["date"]``. In leap years every date after February has a DOY one higher
    than in common years; compare dates, not DOY, across years. The value is ``None`` if the
    stage is not reached, no stage is configured or more than ``max_missing_days_at_start``
    days are missing at the start of the period. Coverage and completeness refer to the days
    from the period start until that stage, or until the period end if it is not reached.
    Incomplete days contribute nothing, which delays the predicted date
    (``details["n_missing_days"]``). ``daily`` is the cumulative sum in °C·d.
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
        missed_at_start = (mean_temp_c.index[0] - period.start.in_year(ctx.year)).days
        if missed_at_start > self.params.max_missing_days_at_start:
            return self._start_not_covered(ctx, selection, curve, missed_at_start)
        return self._prediction(ctx, stages, curve, missed_at_start)

    def _start_not_covered(
        self, ctx: IndexContext, selection: SeasonDays, curve: ThermalTimeCurve, missed: int
    ) -> IndexResult:
        logger.info(
            "%s for sensor %s in %d: %s (%d days missing).",
            self.index_id,
            ctx.sensor_id,
            ctx.year,
            START_NOT_COVERED,
            missed,
        )
        details: dict[str, float | int | str] = {
            STATUS_KEY: START_NOT_COVERED,
            MISSING_AT_START_KEY: missed,
        }
        return self._result(ctx, selection, None, daily=curve.cumulative_c_d, details=details)

    def _prediction(
        self,
        ctx: IndexContext,
        stages: tuple[PhenologyStage, ...],
        curve: ThermalTimeCurve,
        missed_at_start: int,
    ) -> IndexResult:
        period = self.params.period
        reached = {stage.label: curve.date_reached(stage.f_star_c_d) for stage in stages}
        details = _stage_details(stages, reached, curve)
        details[MISSING_AT_START_KEY] = missed_at_start
        last_date = reached[stages[-1].label]
        if last_date is None:
            details[STATUS_KEY] = f"{stages[-1].label} {NOT_REACHED}"
            selection = self._season_days(ctx, period)
            return self._result(ctx, selection, None, daily=curve.cumulative_c_d, details=details)
        selection = self._season_days(ctx, Season(period.start, _month_day(last_date)))
        details["date"] = last_date.isoformat()
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
    """Parameters of :class:`GfvIndex` (general model of Parker et al., 2011).

    Base 0 °C and the start on day of year 60 are verified (docs/literature-verification.md).
    No critical sums are shipped: the species-level F* of Parker et al. (2011) could not be
    found, and 1282 / 2528 °C·d, once noted as general-model candidates, are the Sauvignon blanc
    values of Parker et al. (2013) as quoted by Ausseil et al. (2021). See docs/indices/gfv.md.
    """

    base_temp_c: float = Field(
        GFV_BASE_TEMP_C, description="Base temperature in °C (Parker et al., 2011)."
    )
    period: Season = Field(
        default_factory=lambda: Season(GFV_START, SEASON_END),
        description="Prediction period; starts March 1 (day of year 60 in common years, Parker "
        "et al., 2011); the end, October 31, is a project default.",
    )
    flowering_f_star_c_d: float | None = Field(
        None,
        gt=0.0,
        description="Critical sum for flowering in °C·d; no default (general model: Parker et "
        "al., 2011; cultivars: Parker et al., 2013). Without it the result is 'not "
        "configured'.",
    )
    veraison_f_star_c_d: float | None = Field(
        None,
        gt=0.0,
        description="Critical sum for véraison in °C·d; no default (general model: Parker et "
        "al., 2011; cultivars: Parker et al., 2013). Without it the result is 'not "
        "configured'.",
    )

    @model_validator(mode="after")
    def _check_stages(self) -> Self:
        if (self.flowering_f_star_c_d is None) != (self.veraison_f_star_c_d is None):
            raise ValueError("Set both flowering_f_star_c_d and veraison_f_star_c_d, or neither.")
        _check_increasing(GfvIndex.stages_of(self))
        return self


@index_registry.register
class GfvIndex(ThermalTimePhenologyIndex[GfvParams]):
    """Grapevine Flowering Véraison model: value = day of year of véraison.

    Not configured (``value=None``) until both critical sums are set.
    """

    index_id = "gfv"
    params_model = GfvParams

    def stages(self) -> tuple[PhenologyStage, ...]:
        """Return flowering and véraison with their critical sums (empty if not set)."""
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
            Flowering and véraison, in this order; empty if the critical sums are not set.
        """
        if params.flowering_f_star_c_d is None or params.veraison_f_star_c_d is None:
            return ()
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
