"""Climate indices for viticulture: the :class:`ClimateIndex` extension point and its registry.

Concrete indices live in subpackages (``thermal``, ``ripening``, ``disease``, ``spatial``) that
are added by later workpackages.
"""

from sivin.analytics.base import (
    ClimateIndex,
    DailyLevels,
    IndexContext,
    IndexParams,
    IndexRegistry,
    IndexResult,
    SeasonDays,
    index_registry,
)

__all__ = [
    "ClimateIndex",
    "DailyLevels",
    "IndexContext",
    "IndexParams",
    "IndexRegistry",
    "IndexResult",
    "SeasonDays",
    "index_registry",
]
