"""Ripening quality and risk indices (MIGRATION_PLAN §3.2, WP-2.2).

Importing this package registers the indices in :data:`sivin.analytics.base.index_registry`:
``cool_night``, ``dtr_ripening``, ``heat_hours``, ``tropical_days_nights``, ``frost``,
``winter_freeze``, ``dew_point`` and ``vpd``. The psychrometric formulas are plain functions in
:mod:`sivin.analytics.ripening.psychrometry`; duration-weighted hours come from
:class:`~sivin.analytics.ripening.durations.SampleDurations`.
"""

from sivin.analytics.ripening.characteristic_days import (
    CharacteristicDaysIndex,
    CharacteristicDaysParams,
    DayCategory,
)
from sivin.analytics.ripening.cool_night import CoolNightIndex, CoolNightParams
from sivin.analytics.ripening.dew_point import DewPointIndex, DewPointParams
from sivin.analytics.ripening.dtr import DtrRipeningIndex, DtrRipeningParams
from sivin.analytics.ripening.durations import SampleDurations, masked_values
from sivin.analytics.ripening.frost import FrostIndex, FrostParams
from sivin.analytics.ripening.heat_hours import HeatHoursIndex, HeatHoursParams
from sivin.analytics.ripening.params import PeriodParams, SampleDurationParams
from sivin.analytics.ripening.psychrometry import (
    ALDUCHOV_ESKRIDGE_1996,
    LEGACY_MAGNUS,
    MagnusCoefficients,
    dew_point_c,
    saturation_vapour_pressure_kpa,
    vapour_pressure_deficit_kpa,
)
from sivin.analytics.ripening.vpd import VpdIndex, VpdParams
from sivin.analytics.ripening.winter_freeze import WinterFreezeIndex, WinterFreezeParams

__all__ = [
    "ALDUCHOV_ESKRIDGE_1996",
    "LEGACY_MAGNUS",
    "CharacteristicDaysIndex",
    "CharacteristicDaysParams",
    "CoolNightIndex",
    "CoolNightParams",
    "DayCategory",
    "DewPointIndex",
    "DewPointParams",
    "DtrRipeningIndex",
    "DtrRipeningParams",
    "FrostIndex",
    "FrostParams",
    "HeatHoursIndex",
    "HeatHoursParams",
    "MagnusCoefficients",
    "PeriodParams",
    "SampleDurationParams",
    "SampleDurations",
    "VpdIndex",
    "VpdParams",
    "WinterFreezeIndex",
    "WinterFreezeParams",
    "dew_point_c",
    "masked_values",
    "saturation_vapour_pressure_kpa",
    "vapour_pressure_deficit_kpa",
]
