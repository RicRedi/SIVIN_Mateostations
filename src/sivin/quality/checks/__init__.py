"""Quality checks (MIGRATION_PLAN §2.7).

Importing this package registers every built-in check with :data:`check_registry`:
``missing``, ``range``, ``spike``, ``step``, ``persistence`` and ``sampling``.
"""

from sivin.quality.checks.base import (
    CheckOutcome,
    CheckRegistry,
    CheckSettings,
    QualityCheck,
    check_registry,
)
from sivin.quality.checks.battery import BatteryCheck, BatterySettings
from sivin.quality.checks.missing import MissingRule, MissingValueCheck, MissingValueSettings
from sivin.quality.checks.persistence import PersistenceCheck, PersistenceSettings
from sivin.quality.checks.precip import (
    CounterSteps,
    PrecipCounterCheck,
    PrecipCounterSettings,
    PrecipRangeCheck,
    PrecipRangeSettings,
)
from sivin.quality.checks.range_check import RangeCheck, RangeSettings, runs_of
from sivin.quality.checks.sampling import SamplingCheck, SamplingSettings, classify_intervals
from sivin.quality.checks.spike import SpikeCheck, SpikeSettings
from sivin.quality.checks.step import StepCheck, StepSettings

__all__ = [
    "BatteryCheck",
    "BatterySettings",
    "CheckOutcome",
    "CheckRegistry",
    "CheckSettings",
    "CounterSteps",
    "MissingRule",
    "MissingValueCheck",
    "MissingValueSettings",
    "PersistenceCheck",
    "PersistenceSettings",
    "PrecipCounterCheck",
    "PrecipCounterSettings",
    "PrecipRangeCheck",
    "PrecipRangeSettings",
    "QualityCheck",
    "RangeCheck",
    "RangeSettings",
    "SamplingCheck",
    "SamplingSettings",
    "SpikeCheck",
    "SpikeSettings",
    "StepCheck",
    "StepSettings",
    "check_registry",
    "classify_intervals",
    "runs_of",
]
