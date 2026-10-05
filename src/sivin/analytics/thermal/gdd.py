"""Growing degree-days with Winkler regions (``gdd_winkler``)."""

from __future__ import annotations

import logging
from typing import Final

from pydantic import Field

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.thermal.base import ClassifiedSumParams, ThermalIndex
from sivin.analytics.thermal.classification import ClassBound, IntervalClassification
from sivin.analytics.thermal.formulas import fahrenheit_to_celsius_degree_days
from sivin.analytics.thermal.thermal_time import ThermalTimeModel
from sivin.core.season import Season

logger = logging.getLogger(__name__)

GDD_BASE_TEMP_C: Final = 10.0
"""Base temperature of grapevine growing degree-days, 10 °C (50 °F; Amerine and Winkler, 1944)."""

WINKLER_REGION_UPPER_BOUNDS_F_D: Final = (2500.0, 3000.0, 3500.0, 4000.0)
"""Upper bounds of Winkler regions I-IV in °F·d (Amerine and Winkler, 1944)."""

WINKLER_REGION_LABELS: Final = ("region_i", "region_ii", "region_iii", "region_iv", "region_v")
"""Labels of Winkler regions I-V."""


def winkler_regions() -> IntervalClassification:
    """Return the Winkler regions with bounds converted exactly from °F·d to °C·d.

    2500, 3000, 3500 and 4000 °F·d times 5/9 give 1388.9, 1666.7, 1944.4 and 2222.2 °C·d,
    usually quoted rounded as 1389, 1667, 1944 and 2222 °C·d.

    Returns
    -------
    IntervalClassification
        Regions I-V; a value equal to a bound belongs to the lower region.
    """
    bounds = tuple(
        ClassBound(label=label, upper=fahrenheit_to_celsius_degree_days(upper_f_d))
        for label, upper_f_d in zip(
            WINKLER_REGION_LABELS, WINKLER_REGION_UPPER_BOUNDS_F_D, strict=False
        )
    )
    return IntervalClassification(bounds=bounds, top_label=WINKLER_REGION_LABELS[-1])


class GddWinklerParams(ClassifiedSumParams):
    """Parameters of :class:`GddWinklerIndex`."""

    base_temp_c: float = Field(
        GDD_BASE_TEMP_C,
        description="Base temperature in °C; 10 °C (50 °F) after Amerine and Winkler (1944).",
    )
    period: Season = Field(
        default_factory=Season.vegetation,
        description=(
            "Accumulation period (month-day, local dates); April 1 - October 31 for the "
            "northern hemisphere (Amerine and Winkler, 1944)."
        ),
    )
    regions: IntervalClassification = Field(
        default_factory=winkler_regions,
        description=(
            "Winkler regions in °C·d, inclusive upper bounds; default = 2500/3000/3500/4000 °F·d "
            "of Amerine and Winkler (1944) times 5/9."
        ),
    )


@index_registry.register
class GddWinklerIndex(ThermalIndex[GddWinklerParams]):
    r"""Growing degree-days :math:`\sum \max(0, T_{mean} - 10)` with Winkler regions.

    The value is the sum over the complete days of the period; ``daily`` is the cumulative
    curve. Incomplete days contribute nothing, so the sum is biased low when days are missing
    (``details["n_missing_days"]``). The region is assigned only to a complete season with at
    most ``max_missing_days`` missing days.
    """

    index_id = "gdd_winkler"
    unit = "°C·d"
    params_model = GddWinklerParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the growing degree-days of ``ctx.year``.

        Parameters
        ----------
        ctx : IndexContext
            Data and metadata of one sensor and one season year.

        Returns
        -------
        IndexResult
            Value in °C·d, Winkler region (see class docstring) and cumulative curve.
        """
        selection = self._season_days(ctx, self.params.period)
        mean_temp_c = self._mean_temp_c(selection)
        if mean_temp_c.empty:
            return self._empty_result(ctx, selection)
        curve = ThermalTimeModel(self.params.base_temp_c).accumulate(mean_temp_c)
        value_c_d = curve.total_c_d
        region = self.params.sum_class(self.params.regions, value_c_d, selection)
        return self._result(
            ctx, selection, value_c_d, classification=region, daily=curve.cumulative_c_d
        )
