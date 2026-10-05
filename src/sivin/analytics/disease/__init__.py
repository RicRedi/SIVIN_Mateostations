"""Grapevine disease models from temperature and humidity (MIGRATION_PLAN §3.3, WP-2.3).

Importing this package registers its indices in
:data:`sivin.analytics.base.index_registry`:

* ``powdery_mildew_gt`` — Gubler-Thomas powdery mildew risk index
  (:class:`PowderyMildewGublerThomas`, state machine :class:`GublerThomasModel`);
* ``botrytis_broome`` — Broome et al. (1995) Botrytis bunch rot infection model with wetness
  estimated from relative humidity (:class:`BotrytisBroome`, results ``estimated=True``).

Downy mildew is not modelled (no rainfall or leaf-wetness data); see
``docs/indices/downy_mildew.md``.
"""

from sivin.analytics.disease.botrytis import (
    BotrytisBroome,
    BotrytisBroomeParams,
    BroomeCoefficients,
    InfectionEvent,
    RiskBand,
    WetnessPeriod,
    WetnessPeriodDetector,
    logistic,
)
from sivin.analytics.disease.gubler_thomas import (
    DayAssessment,
    GublerThomasModel,
    GublerThomasParams,
    GublerThomasState,
    Phase,
    RiskClass,
    fahrenheit_to_celsius,
)
from sivin.analytics.disease.period import SeasonWindow
from sivin.analytics.disease.powdery_mildew import (
    PowderyMildewDayAssessor,
    PowderyMildewGublerThomas,
)
from sivin.analytics.disease.result import DiseaseIndex
from sivin.analytics.disease.sampling import (
    RunFinder,
    SampleDurations,
    SampleRun,
    SampleTiming,
    SamplingParams,
)

__all__ = [
    "BotrytisBroome",
    "BotrytisBroomeParams",
    "BroomeCoefficients",
    "DayAssessment",
    "DiseaseIndex",
    "GublerThomasModel",
    "GublerThomasParams",
    "GublerThomasState",
    "InfectionEvent",
    "Phase",
    "PowderyMildewDayAssessor",
    "PowderyMildewGublerThomas",
    "RiskBand",
    "RiskClass",
    "RunFinder",
    "SampleDurations",
    "SampleRun",
    "SampleTiming",
    "SamplingParams",
    "SeasonWindow",
    "WetnessPeriod",
    "WetnessPeriodDetector",
    "fahrenheit_to_celsius",
    "logistic",
]
