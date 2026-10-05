r"""Relative confirmation of a transition (MIGRATION_PLAN §2.7, step 2).

A candidate boundary between an indoor-like stretch :math:`I` and an outdoor stretch :math:`O`
is compared on **local windows next to the boundary** (features of
:mod:`sivin.quality.regime`). Four relative criteria ("votes"):

.. math::

    \text{spread ratio:}\quad & s_O \ge k_s \max(s_I, s_0) \\
    \text{level difference:}\quad & |\tilde T_O - \tilde T_I| \ge \Delta T \\
    \text{humidity excess:}\quad & \tilde h_O - \tilde h_I \ge \Delta h \\
    \text{humidity spread ratio:}\quad & r_O \ge k_r \max(r_I, r_0)

(the humidity votes only with humidity). The transition is **confirmed** if

* :math:`I` is indoor-like and :math:`O` is not (absolute rules), and
* at least :math:`\min(V, \text{available votes})` votes hold.

Its **score** is the share of available votes that hold (0-1). It is a transparent heuristic
summary of the evidence, not a calibrated probability.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from sivin.quality.regime import IndoorAssessment

logger = logging.getLogger(__name__)


class ContrastSettings(BaseModel):
    """Relative criteria (all project defaults, to be tuned on real data)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_spread_ratio: float = Field(
        2.0,
        gt=1,
        description=(
            "Factor k_s (dimensionless) by which the outdoor daily temperature spread must "
            "exceed the indoor one. Project default."
        ),
    )
    spread_floor_c: float = Field(
        0.5,
        gt=0,
        description="Floor s_0 (°C) of the indoor daily spread in the ratio. Project default.",
    )
    min_level_difference_c: float = Field(
        5.0,
        gt=0,
        description="Median temperature difference ΔT (°C) that counts as a vote. Project default.",
    )
    min_rh_excess_pct: float = Field(
        15.0,
        gt=0,
        description=(
            "Amount Δh (%) by which the outdoor median humidity must exceed the indoor one. "
            "Project default."
        ),
    )
    min_rh_spread_ratio: float = Field(
        2.0,
        gt=1,
        description=(
            "Factor k_r (dimensionless) by which the outdoor daily humidity spread must exceed "
            "the indoor one. Project default."
        ),
    )
    rh_spread_floor_pct: float = Field(
        2.0,
        gt=0,
        description="Floor r_0 (%) of the indoor daily humidity spread in the ratio.",
    )
    min_votes: int = Field(
        2,
        ge=1,
        description=(
            "Votes V (count) needed to confirm a transition; capped at the number of available "
            "votes (2 without humidity). Project default."
        ),
    )
    window_s: float = Field(
        2 * 86_400.0,
        gt=0,
        description=(
            "Length (s) of the local windows on each side of a boundary. Project default 2 days."
        ),
    )
    min_window_samples: int = Field(
        24,
        ge=3,
        description=(
            "Fewest samples (count) each local window needs; fewer means not confirmable. "
            "Project default: half a day at 1825 s."
        ),
    )


@dataclass(frozen=True, slots=True)
class ContrastVerdict:
    """Outcome of comparing an indoor-like and an outdoor window.

    Attributes
    ----------
    indoor, outdoor : IndoorAssessment
        Absolute assessment of the two windows.
    votes : Mapping[str, bool]
        Relative criterion → met (read-only).
    confirmed : bool
        Whether the transition is confirmed.
    score : float
        Share (0-1, dimensionless) of available votes that hold; heuristic, not a probability.
    """

    indoor: IndoorAssessment
    outdoor: IndoorAssessment
    votes: Mapping[str, bool] = field(default_factory=dict)
    confirmed: bool = False
    score: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "votes", MappingProxyType(dict(self.votes)))

    def describe(self, outdoor_first: bool) -> str:
        """Return the numbers behind the verdict as text, "after" relative to "before".

        Parameters
        ----------
        outdoor_first : bool
            ``True`` for a retrieval (outdoor window before the boundary), ``False`` for a
            deployment.

        Returns
        -------
        str
            E.g. ``"indoor → outdoor: level -13.6 °C, daily spread x11.4, humidity +33 %,
            votes 4/4"``.
        """
        before, after = self.indoor.features, self.outdoor.features
        if outdoor_first:
            before, after = after, before
        ratio = max(after.daily_spread_c, _DISPLAY_FLOOR_C) / max(
            before.daily_spread_c, _DISPLAY_FLOOR_C
        )
        text = "outdoor → indoor" if outdoor_first else "indoor → outdoor"
        text += f": level {after.temp_median_c - before.temp_median_c:+.1f} °C"
        text += f", daily spread x{ratio:.1f}"
        if before.rh_median_pct is not None and after.rh_median_pct is not None:
            text += f", humidity {after.rh_median_pct - before.rh_median_pct:+.0f} %"
        text += f", votes {sum(self.votes.values())}/{len(self.votes)}"
        return text


_DISPLAY_FLOOR_C = 0.1
"""Smallest spread (°C) used in the displayed ratio (avoids division by zero)."""


class TransitionContrast:
    """Confirm a transition by relative and absolute criteria (module docstring).

    Parameters
    ----------
    settings : ContrastSettings, optional
        The relative criteria; defaults when omitted.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: ContrastSettings | None = None) -> None:
        self._settings = settings or ContrastSettings()

    @property
    def settings(self) -> ContrastSettings:
        """The relative criteria."""
        return self._settings

    def compare(self, indoor: IndoorAssessment, outdoor: IndoorAssessment) -> ContrastVerdict:
        """Compare an indoor-like window with an outdoor window.

        Parameters
        ----------
        indoor : IndoorAssessment
            The window on the supposed indoor side of the boundary.
        outdoor : IndoorAssessment
            The window on the supposed outdoor side.

        Returns
        -------
        ContrastVerdict
            Votes, confirmation and score.
        """
        votes = self._votes(indoor, outdoor)
        n_met = sum(votes.values())
        needed = min(self._settings.min_votes, len(votes))
        confirmed = indoor.indoor_like and not outdoor.indoor_like and n_met >= needed
        return ContrastVerdict(indoor, outdoor, votes, confirmed, n_met / len(votes))

    def _votes(self, indoor: IndoorAssessment, outdoor: IndoorAssessment) -> dict[str, bool]:
        settings = self._settings
        inside, outside = indoor.features, outdoor.features
        votes = {
            "spread_ratio": outside.daily_spread_c
            >= settings.min_spread_ratio * max(inside.daily_spread_c, settings.spread_floor_c),
            "level_difference": abs(outside.temp_median_c - inside.temp_median_c)
            >= settings.min_level_difference_c,
        }
        if inside.rh_median_pct is not None and outside.rh_median_pct is not None:
            votes["humidity_excess"] = (
                outside.rh_median_pct - inside.rh_median_pct >= settings.min_rh_excess_pct
            )
        if inside.rh_daily_spread_pct is not None and outside.rh_daily_spread_pct is not None:
            votes["humidity_spread_ratio"] = outside.rh_daily_spread_pct >= (
                settings.min_rh_spread_ratio
                * max(inside.rh_daily_spread_pct, settings.rh_spread_floor_pct)
            )
        return votes
