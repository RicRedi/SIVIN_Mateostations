"""Heat accumulation and phenology indices (MIGRATION_PLAN §3.1).

Importing this package registers ``gdd_winkler``, ``huglin``, ``gst``, ``bedd``, ``budburst``,
``gfv`` and ``gsr`` in :data:`sivin.analytics.base.index_registry`.
"""

from sivin.analytics.thermal.bedd import BeddIndex, BeddParams
from sivin.analytics.thermal.classification import ClassBound, IntervalClassification
from sivin.analytics.thermal.daily_mean import (
    DailyMeanDefinition,
    DailyMeanRegistry,
    MinMaxMean,
    SampleMean,
    daily_mean_registry,
)
from sivin.analytics.thermal.gdd import GddWinklerIndex, GddWinklerParams
from sivin.analytics.thermal.gst import GstIndex, GstParams
from sivin.analytics.thermal.huglin import HuglinIndex, HuglinParams, LatitudeBand
from sivin.analytics.thermal.phenology import (
    BudburstIndex,
    BudburstParams,
    GfvIndex,
    GfvParams,
    GsrIndex,
    GsrParams,
    PhenologyStage,
    ThermalTimePhenologyIndex,
)
from sivin.analytics.thermal.thermal_time import ThermalTimeCurve, ThermalTimeModel

__all__ = [
    "BeddIndex",
    "BeddParams",
    "BudburstIndex",
    "BudburstParams",
    "ClassBound",
    "DailyMeanDefinition",
    "DailyMeanRegistry",
    "GddWinklerIndex",
    "GddWinklerParams",
    "GfvIndex",
    "GfvParams",
    "GsrIndex",
    "GsrParams",
    "GstIndex",
    "GstParams",
    "HuglinIndex",
    "HuglinParams",
    "IntervalClassification",
    "LatitudeBand",
    "MinMaxMean",
    "PhenologyStage",
    "SampleMean",
    "ThermalTimeCurve",
    "ThermalTimeModel",
    "ThermalTimePhenologyIndex",
    "daily_mean_registry",
]
