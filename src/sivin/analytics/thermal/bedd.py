"""Biologically effective degree-days after Gladstones (1992) (``bedd``)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Final, Literal, Self

import pandas as pd
from pydantic import Field, model_validator

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.thermal.base import ThermalIndex, ThermalParams
from sivin.analytics.thermal.formulas import bedd_daily, bedd_daily_cap_before_adjustment
from sivin.core.season import Season

logger = logging.getLogger(__name__)

BEDD_BASE_TEMP_C: Final = 10.0
"""Base temperature in °C (Gladstones, 1992)."""

BEDD_CAP_C_D: Final = 9.0
"""Upper limit of the daily contribution in °C·d, i.e. no further effect above a 19 °C daily
mean (Gladstones, 1992; as implemented in xclim 0.62, secondary source)."""

BEDD_DTR_LOWER_C: Final = 10.0
"""Diurnal range in °C below which the contribution is reduced (Gladstones, 1992; secondary
source xclim 0.62)."""

BEDD_DTR_UPPER_C: Final = 13.0
"""Diurnal range in °C above which the contribution is increased (Gladstones, 1992; secondary
source xclim 0.62)."""

BEDD_DTR_FACTOR: Final = 0.25
"""Adjustment per °C of diurnal range outside 10-13 °C, in °C·d/°C (Gladstones, 1992;
secondary source xclim 0.62)."""

NO_DAY_LENGTH_ADJUSTMENT: Final = 1.0
"""Day-length coefficient that leaves the contribution unchanged."""

type CapOrder = Literal["after_adjustment", "before_adjustment"]
"""Whether the daily cap is applied after or before the day-length and DTR adjustments."""

DEFAULT_CAP_ORDER: Final[CapOrder] = "after_adjustment"
"""Default cap order: the adjusted contribution is capped, min(c, k·max(0, T - 10) + A), as
quoted from Gladstones (1992) by xclim 0.62 (secondary source); the extra floor at 0 is a
project choice."""

BEDD_DAILY_FORMULAS: Final[Mapping[str, Callable[..., pd.Series]]] = MappingProxyType(
    {"after_adjustment": bedd_daily, "before_adjustment": bedd_daily_cap_before_adjustment}
)
"""Daily BEDD formula of each cap order (read-only)."""


class BeddParams(ThermalParams):
    """Parameters of :class:`BeddIndex`.

    Cap, DTR band and factor match the secondary source xclim 0.62 (citing Gladstones, 1992);
    the book itself was not consulted (docs/literature-verification.md).
    """

    base_temp_c: float = Field(BEDD_BASE_TEMP_C, description="Base temperature in °C.")
    cap_c_d: float = Field(
        BEDD_CAP_C_D,
        gt=0.0,
        description="Upper limit of the daily contribution in °C·d (19 °C mean - 10 °C base; "
        "Gladstones, 1992; secondary source).",
    )
    dtr_lower_c: float = Field(
        BEDD_DTR_LOWER_C,
        ge=0.0,
        description="Diurnal temperature range in °C below which the daily contribution is "
        "reduced (Gladstones, 1992; secondary source).",
    )
    dtr_upper_c: float = Field(
        BEDD_DTR_UPPER_C,
        ge=0.0,
        description="Diurnal temperature range in °C above which the daily contribution is "
        "increased (Gladstones, 1992; secondary source).",
    )
    dtr_factor: float = Field(
        BEDD_DTR_FACTOR,
        ge=0.0,
        description="Adjustment in °C·d per °C of diurnal range outside the band; 0 disables "
        "it (Gladstones, 1992; secondary source).",
    )
    day_length_coefficient: float = Field(
        NO_DAY_LENGTH_ADJUSTMENT,
        gt=0.0,
        description="Day-length (latitude) coefficient, dimensionless; 1 = no adjustment. "
        "Gladstones (1992) gives latitude-dependent values that are not shipped "
        "[to be verified].",
    )
    cap_order: CapOrder = Field(
        DEFAULT_CAP_ORDER,
        description="'after_adjustment': cap the adjusted daily contribution (default, form "
        "commonly quoted from Gladstones, 1992); 'before_adjustment': cap the mean excess, "
        "then adjust (Gladstones' monthly formulation as reported; not found in a source "
        "[to be verified]).",
    )
    period: Season = Field(
        default_factory=Season.vegetation,
        description="Accumulation period, April 1 - October 31 (northern hemisphere).",
    )

    @model_validator(mode="after")
    def _check_dtr_band(self) -> Self:
        if self.dtr_upper_c < self.dtr_lower_c:
            raise ValueError(
                f"dtr_upper_c {self.dtr_upper_c} must not be below dtr_lower_c {self.dtr_lower_c}."
            )
        return self


@index_registry.register
class BeddIndex(ThermalIndex[BeddParams]):
    r"""Sum of capped daily degree-days adjusted for diurnal temperature range.

    Daily contribution :math:`\min(c, \max(0, k \max(0, T_{mean} - 10) + A(T_{max}-T_{min})))`
    by default (see :func:`~sivin.analytics.thermal.formulas.bedd_daily`; ``cap_order``
    selects :func:`~sivin.analytics.thermal.formulas.bedd_daily_cap_before_adjustment`
    instead); ``daily`` is the cumulative curve. No classes are defined. Incomplete days
    contribute nothing, so the sum is biased low when days are missing
    (``details["n_missing_days"]``).
    """

    index_id = "bedd"
    unit = "°C·d"
    params_model = BeddParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the biologically effective degree-days of ``ctx.year``.

        Parameters
        ----------
        ctx : IndexContext
            Data and metadata of one sensor and one season year.

        Returns
        -------
        IndexResult
            Value in °C·d and cumulative curve.
        """
        selection = self._season_days(ctx, self.params.period)
        mean_temp_c = self._mean_temp_c(selection)
        if mean_temp_c.empty:
            return self._empty_result(ctx, selection)
        frame = selection.days.frame.loc[mean_temp_c.index]
        params = self.params
        daily_formula = BEDD_DAILY_FORMULAS[params.cap_order]
        contribution = daily_formula(
            mean_temp_c,
            frame["temp_max"] - frame["temp_min"],
            base_temp_c=params.base_temp_c,
            cap_c_d=params.cap_c_d,
            day_length_coefficient=params.day_length_coefficient,
            dtr_lower_c=params.dtr_lower_c,
            dtr_upper_c=params.dtr_upper_c,
            dtr_factor=params.dtr_factor,
        )
        cumulative = contribution.cumsum().rename("cumulative_c_d")
        return self._result(ctx, selection, float(cumulative.iloc[-1]), daily=cumulative)
