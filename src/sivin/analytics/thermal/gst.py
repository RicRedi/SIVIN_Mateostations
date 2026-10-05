"""Growing season average temperature (``gst``)."""

from __future__ import annotations

import logging
from typing import Final

from pydantic import Field

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.thermal.base import ThermalIndex, ThermalParams
from sivin.analytics.thermal.classification import ClassBound, IntervalClassification
from sivin.core.season import Season

logger = logging.getLogger(__name__)

GST_CLASS_BOUNDS: Final = (
    ("too_cool", 13.0),
    ("cool", 15.0),
    ("intermediate", 17.0),
    ("warm", 19.0),
    ("hot", 24.0),
)
"""Climate-maturity groups of Jones (2006) with inclusive upper bounds in °C: cool 13-15,
intermediate 15-17, warm 17-19, hot 19-24 °C; below 13 and above 24 °C are outside the range
of quality wine production (``too_cool`` / ``too_hot``). Bounds verified against secondary
sources quoting Jones (2006) / Jones et al. (2010); which side of a bound is inclusive is a
project convention (docs/literature-verification.md)."""

GST_TOP_CLASS: Final = "too_hot"
"""Label of growing season temperatures above the last bound."""


def gst_classes() -> IntervalClassification:
    """Return the climate-maturity groups of Jones (2006).

    Returns
    -------
    IntervalClassification
        Six groups; a value equal to a bound belongs to the lower group.
    """
    return IntervalClassification(
        bounds=tuple(ClassBound(label=label, upper=upper) for label, upper in GST_CLASS_BOUNDS),
        top_label=GST_TOP_CLASS,
    )


class GstParams(ThermalParams):
    """Parameters of :class:`GstIndex`."""

    period: Season = Field(
        default_factory=Season.vegetation,
        description="Averaging period, April 1 - October 31 (Jones, 2006).",
    )
    classes: IntervalClassification = Field(
        default_factory=gst_classes,
        description="Climate-maturity groups in °C, inclusive upper bounds (Jones, 2006).",
    )


@index_registry.register
class GstIndex(ThermalIndex[GstParams]):
    """Mean of the daily mean temperatures of the complete days of the growing season.

    The class is assigned only to a complete season.
    """

    index_id = "gst"
    unit = "°C"
    params_model = GstParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the growing season temperature of ``ctx.year``.

        Parameters
        ----------
        ctx : IndexContext
            Data and metadata of one sensor and one season year.

        Returns
        -------
        IndexResult
            Value in °C, climate-maturity group (complete seasons only) and the daily means.
        """
        selection = self._season_days(ctx, self.params.period)
        mean_temp_c = self._mean_temp_c(selection)
        if mean_temp_c.empty:
            return self._empty_result(ctx, selection)
        value_c = float(mean_temp_c.mean())
        label = self.params.classes.classify(value_c) if selection.complete else None
        return self._result(ctx, selection, value_c, classification=label, daily=mean_temp_c)
