"""Time alignment of several sensors onto a common grid (WP-1.6, MIGRATION_PLAN §2.7).

Typical use::

    aligner = SensorAligner(NearestWithinTolerance(), GridPolicy(step_s=1800.0))
    panel = aligner.align([series_a, series_b, series_c])
    panel.variable("temp_c")  # time x sensor, NaN where no usable sample
"""

from sivin.alignment.aligner import ALIGNED_VARIABLES, SensorAligner
from sivin.alignment.config import AlignmentConfig
from sivin.alignment.grid import (
    DEFAULT_GRID_STEP_S,
    GridPolicy,
    OverlapSpan,
    SpanRule,
    TimeGrid,
    UnionSpan,
    span_registry,
)
from sivin.alignment.panel import AlignedPanel
from sivin.alignment.strategies import (
    DEFAULT_MAX_GAP_S,
    AlignedValues,
    AlignmentStrategy,
    LinearInterpolation,
    LinearParams,
    NearestParams,
    NearestWithinTolerance,
    SampleSet,
    StrategyParams,
    strategy_registry,
)

__all__ = [
    "ALIGNED_VARIABLES",
    "DEFAULT_GRID_STEP_S",
    "DEFAULT_MAX_GAP_S",
    "AlignedPanel",
    "AlignedValues",
    "AlignmentConfig",
    "AlignmentStrategy",
    "GridPolicy",
    "LinearInterpolation",
    "LinearParams",
    "NearestParams",
    "NearestWithinTolerance",
    "OverlapSpan",
    "SampleSet",
    "SensorAligner",
    "SpanRule",
    "StrategyParams",
    "TimeGrid",
    "UnionSpan",
    "span_registry",
    "strategy_registry",
]
