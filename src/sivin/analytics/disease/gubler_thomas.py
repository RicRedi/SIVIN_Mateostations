"""Gubler-Thomas (UC Davis) powdery mildew risk index as a day-by-day state machine.

The model only sees one :class:`DayAssessment` per day (was the day favourable for the fungus,
did a heat period occur); turning raw samples into assessments is the job of
:class:`~sivin.analytics.disease.powdery_mildew.PowderyMildewDayAssessor`.

Rules (Gubler et al., 1999; UC IPM powdery mildew risk assessment), with the interpretation
choices of this project marked as such (see ``docs/indices/powdery_mildew_gt.md``):

* **Waiting for onset.** The index starts after ``onset_days`` (3) consecutive favourable days,
  a favourable day having at least 6 consecutive hours with temperatures of 70-85 °F
  (21.1-29.4 °C). On the onset day the index is set to ``onset_index_points`` (60 = 3 x 20,
  interpretation: the three onset days earn their points). A non-favourable day resets the
  streak; heat is not evaluated before onset.
* **Active.** Each favourable day adds 20 points, each non-favourable day subtracts 10 points,
  and a day with temperatures of at least 95 °F (35 °C) for at least 15 minutes subtracts
  another 10 points (interpretation: the heat penalty is independent of the hours rule, so a
  favourable heat day nets +10). The index stays within 0-100.
* **Undetermined day** (not enough data to decide whether it was favourable): the streak or the
  index is carried unchanged (project rule); a heat period that *was* observed still subtracts
  its points.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from typing import Final, Self

from pydantic import Field, model_validator

from sivin.analytics.base import IndexParams
from sivin.analytics.disease.period import SeasonWindow
from sivin.analytics.disease.sampling import SamplingParams

logger = logging.getLogger(__name__)

FAVOURABLE_BAND_MIN_F: Final = 70.0
"""Lower bound of the favourable temperature band in °F (Gubler et al., 1999; UC IPM)."""

FAVOURABLE_BAND_MAX_F: Final = 85.0
"""Upper bound of the favourable temperature band in °F (Gubler et al., 1999; UC IPM)."""

HEAT_THRESHOLD_F: Final = 95.0
"""Temperature in °F whose occurrence for 15 minutes lowers the index (Gubler et al., 1999)."""

_FAHRENHEIT_OFFSET: Final = 32.0
_FAHRENHEIT_PER_KELVIN: Final = 1.8


def fahrenheit_to_celsius(temp_f: float) -> float:
    """Convert a temperature from degrees Fahrenheit to degrees Celsius.

    Parameters
    ----------
    temp_f : float
        Temperature in °F.

    Returns
    -------
    float
        Temperature in °C, ``(temp_f - 32) / 1.8``.
    """
    return (temp_f - _FAHRENHEIT_OFFSET) / _FAHRENHEIT_PER_KELVIN


class RiskClass(StrEnum):
    """Risk classes of the index (UC IPM: low 0-30, moderate 40-50, high 60-100)."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class GublerThomasParams(IndexParams):
    """Parameters of the Gubler-Thomas powdery mildew risk index (``powdery_mildew_gt``)."""

    band_min_temp_c: float = Field(
        fahrenheit_to_celsius(FAVOURABLE_BAND_MIN_F),
        description="Lower bound (inclusive) of the favourable band in °C; 70 °F (Gubler 1999).",
    )
    band_max_temp_c: float = Field(
        fahrenheit_to_celsius(FAVOURABLE_BAND_MAX_F),
        description="Upper bound (inclusive) of the favourable band in °C; 85 °F (Gubler 1999).",
    )
    min_favourable_run_h: float = Field(
        6.0,
        gt=0.0,
        description="Consecutive hours (h) in the band that make a day favourable (Gubler 1999).",
    )
    onset_days: int = Field(
        3, ge=1, description="Consecutive favourable days (d) that start the index (Gubler 1999)."
    )
    onset_index_points: int = Field(
        60,
        ge=0,
        description=(
            "Index value (points) on the onset day: 3 onset days x 20 points. Interpretation of "
            "this project [to be verified]."
        ),
    )
    favourable_day_points: int = Field(
        20, ge=0, description="Points added for a favourable day after onset (Gubler 1999)."
    )
    unfavourable_day_points: int = Field(
        10, ge=0, description="Points subtracted for a non-favourable day (Gubler 1999)."
    )
    heat_temp_c: float = Field(
        fahrenheit_to_celsius(HEAT_THRESHOLD_F),
        description="Heat threshold (inclusive) in °C; 95 °F (Gubler 1999).",
    )
    min_heat_duration_min: float = Field(
        15.0,
        ge=0.0,
        description="Minutes (min) at or above the heat threshold for the penalty (Gubler 1999).",
    )
    heat_points: int = Field(
        10, ge=0, description="Points subtracted for a heat day after onset (Gubler 1999)."
    )
    min_index_points: int = Field(0, description="Lower bound of the index (points), UC IPM.")
    max_index_points: int = Field(100, description="Upper bound of the index (points), UC IPM.")
    moderate_from_points: int = Field(
        40, description="Lowest index (points) of the class 'moderate' (UC IPM: 40-50)."
    )
    high_from_points: int = Field(
        60, description="Lowest index (points) of the class 'high' (UC IPM: 60-100)."
    )
    season: SeasonWindow = Field(
        default_factory=SeasonWindow,
        description=(
            "Model period (local dates). Default April 1 - October 31, a project default; the "
            "literature starts the index at budbreak."
        ),
    )
    sampling: SamplingParams = Field(
        default_factory=SamplingParams, description="Duration represented by each sample."
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not self.band_min_temp_c < self.band_max_temp_c:
            raise ValueError("band_min_temp_c must be below band_max_temp_c")
        if not (
            self.min_index_points
            <= self.moderate_from_points
            <= self.high_from_points
            <= self.max_index_points
        ):
            raise ValueError("need min <= moderate_from <= high_from <= max index points")
        if not self.min_index_points <= self.onset_index_points <= self.max_index_points:
            raise ValueError("onset_index_points must lie within the index bounds")
        return self


@dataclass(frozen=True, slots=True)
class DayAssessment:
    """What one local day means for the model.

    Attributes
    ----------
    day : datetime.date
        Local calendar date.
    favourable : bool or None
        ``True`` if the day had a long enough run in the favourable band, ``False`` if it did
        not and the data cover the day, ``None`` if this cannot be decided (too little data).
    heat : bool
        ``True`` if a heat period was observed.
    longest_run_h : float
        Longest observed run in the favourable band, in hours.
    """

    day: date
    favourable: bool | None
    heat: bool
    longest_run_h: float


class Phase(StrEnum):
    """State of the model."""

    WAITING_FOR_ONSET = "waiting_for_onset"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class GublerThomasState:
    """State of the model at the end of a day.

    Attributes
    ----------
    day : datetime.date or None
        The day this state belongs to (``None`` before the first day).
    phase : Phase
        Waiting for onset or active.
    streak_days : int
        Consecutive favourable days counted towards the onset (0 once active).
    index_points : int
        Index value in points (0 while waiting).
    onset_date : datetime.date or None
        Day the index started.
    """

    day: date | None
    phase: Phase
    streak_days: int
    index_points: int
    onset_date: date | None


class GublerThomasModel:
    """Day-by-day state machine of the Gubler-Thomas risk index.

    Parameters
    ----------
    params : GublerThomasParams
        Thresholds and points.
    """

    __slots__ = ("_params",)

    def __init__(self, params: GublerThomasParams) -> None:
        self._params = params

    def initial_state(self) -> GublerThomasState:
        """Return the state before the first day: waiting, no streak, index at its minimum.

        Returns
        -------
        GublerThomasState
            The initial state.
        """
        return GublerThomasState(
            day=None,
            phase=Phase.WAITING_FOR_ONSET,
            streak_days=0,
            index_points=self._params.min_index_points,
            onset_date=None,
        )

    def run(self, days: Iterable[DayAssessment]) -> list[GublerThomasState]:
        """Apply :meth:`step` to consecutive days.

        Parameters
        ----------
        days : iterable of DayAssessment
            Consecutive local days in increasing order.

        Returns
        -------
        list of GublerThomasState
            The state at the end of each day.
        """
        states: list[GublerThomasState] = []
        state = self.initial_state()
        for day in days:
            state = self.step(state, day)
            states.append(state)
        return states

    def step(self, state: GublerThomasState, day: DayAssessment) -> GublerThomasState:
        """Advance the model by one day.

        Parameters
        ----------
        state : GublerThomasState
            State at the end of the previous day.
        day : DayAssessment
            The new day.

        Returns
        -------
        GublerThomasState
            State at the end of ``day``.
        """
        if state.phase is Phase.WAITING_FOR_ONSET:
            return self._wait(state, day)
        return self._update_active(state, day)

    def classify(self, index_points: int) -> RiskClass:
        """Return the risk class of an index value.

        Parameters
        ----------
        index_points : int
            Index value in points.

        Returns
        -------
        RiskClass
            ``HIGH`` from ``high_from_points``, ``MODERATE`` from ``moderate_from_points``,
            otherwise ``LOW``.
        """
        if index_points >= self._params.high_from_points:
            return RiskClass.HIGH
        if index_points >= self._params.moderate_from_points:
            return RiskClass.MODERATE
        return RiskClass.LOW

    def _wait(self, state: GublerThomasState, day: DayAssessment) -> GublerThomasState:
        if day.favourable is None:
            return replace(state, day=day.day)
        if not day.favourable:
            return replace(state, day=day.day, streak_days=0)
        streak_days = state.streak_days + 1
        if streak_days < self._params.onset_days:
            return replace(state, day=day.day, streak_days=streak_days)
        logger.debug("Powdery mildew index starts on %s.", day.day)
        return GublerThomasState(
            day=day.day,
            phase=Phase.ACTIVE,
            streak_days=0,
            index_points=self._params.onset_index_points,
            onset_date=day.day,
        )

    def _update_active(self, state: GublerThomasState, day: DayAssessment) -> GublerThomasState:
        params = self._params
        change = 0
        if day.favourable is True:
            change += params.favourable_day_points
        elif day.favourable is False:
            change -= params.unfavourable_day_points
        if day.heat:
            change -= params.heat_points
        index_points = min(
            params.max_index_points,
            max(params.min_index_points, state.index_points + change),
        )
        return replace(state, day=day.day, index_points=index_points)
