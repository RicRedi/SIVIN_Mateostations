r"""Robust features of a stretch of samples and the absolute "indoor-like" rules.

A sensor indoors (office, store, service) shows a small daily temperature range, a steady and
moderate relative humidity and a temperature a room can have. For a stretch of samples
:class:`RegimeClassifier` computes

* the median temperature :math:`\tilde T` (°C),
* the daily temperature spread :math:`s` (°C): the median over the stretch's consecutive 24-h
  windows (counted from its first sample; windows with fewer than ``min_window_samples``
  samples are skipped, and if none is left the whole stretch is one window) of
  :math:`P_{95} - P_{5}` of the temperature,
* the median relative humidity :math:`\tilde h` (%) and the daily humidity spread :math:`r` (%),
  computed like :math:`s`, if humidity is available,

and calls the stretch **indoor-like** if all absolute criteria hold:

.. math::

    T_{room,min} \le \tilde T \le T_{room,max}, \quad s \le s_{max}, \quad
    \tilde h \le h_{max}, \quad r \le r_{max}

(the humidity criteria only with humidity). These rules alone do not decide a transition; a
transition also needs a relative contrast to the neighbouring outdoor data
(:mod:`sivin.quality.contrast`).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sivin.quality.samples import S_PER_DAY, FloatArray

logger = logging.getLogger(__name__)

SPREAD_LOW_PERCENTILE = 5.0
"""Lower percentile of a daily spread (robust against a single spike)."""

SPREAD_HIGH_PERCENTILE = 95.0
"""Upper percentile of a daily spread (robust against a single spike)."""


class Regime(StrEnum):
    """Where the sensor is."""

    INDOOR = "indoor"
    """Office, store or transport: before deployment or during service."""
    OUTDOOR = "outdoor"
    """In the vineyard."""


class RegimeSettings(BaseModel):
    """Absolute indoor-like rules (all project defaults, to be tuned on real data)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    room_min_c: float = Field(
        5.0,
        description=(
            "Lowest median temperature (°C) of a room; covers unheated stores in winter. "
            "Project default [to be tuned on real data]."
        ),
    )
    room_max_c: float = Field(
        35.0,
        description=(
            "Highest median temperature (°C) of a room; covers hot offices in summer. "
            "Project default [to be tuned on real data]."
        ),
    )
    indoor_max_daily_spread_c: float = Field(
        4.0,
        ge=0,
        description=(
            "Largest daily temperature spread s_max (P95 - P5 per 24 h, °C) of an indoor "
            "stretch; an office with day-time heating stays below it. Project default "
            "[to be tuned on real data]."
        ),
    )
    indoor_max_rh_pct: float = Field(
        75.0,
        description=(
            "Largest median relative humidity h_max (%) of an indoor stretch; excludes fog and "
            "most overcast days. Project default [to be tuned on real data]."
        ),
    )
    indoor_max_rh_spread_pct: float = Field(
        8.0,
        ge=0,
        description=(
            "Largest daily relative-humidity spread r_max (P95 - P5 per 24 h, %) of an indoor "
            "stretch: indoor humidity is steady, outdoor humidity follows the daily "
            "temperature cycle even under overcast skies. Project default [to be tuned]."
        ),
    )
    min_window_samples: int = Field(
        12,
        ge=2,
        description=(
            "Fewest samples (count) a 24-h window needs to contribute a daily spread. Project "
            "default: a quarter of a day at the nominal 1825 s interval."
        ),
    )

    @model_validator(mode="after")
    def _ordered_band(self) -> RegimeSettings:
        if self.room_min_c > self.room_max_c:
            raise ValueError("room_min_c must not exceed room_max_c")
        return self


@dataclass(frozen=True, slots=True)
class WindowFeatures:
    """Robust features of a stretch of samples.

    Attributes
    ----------
    temp_median_c : float
        Median temperature in °C.
    daily_spread_c : float
        Median over 24-h windows of the P95 - P5 temperature spread, in °C.
    rh_median_pct : float or None
        Median relative humidity in %, ``None`` without humidity data.
    rh_daily_spread_pct : float or None
        Median over 24-h windows of the P95 - P5 humidity spread, in %; ``None`` without
        humidity data.
    n_samples : int
        Number of samples.
    """

    temp_median_c: float
    daily_spread_c: float
    rh_median_pct: float | None
    rh_daily_spread_pct: float | None
    n_samples: int


@dataclass(frozen=True, slots=True)
class IndoorAssessment:
    """Which absolute indoor criteria a stretch meets.

    Attributes
    ----------
    features : WindowFeatures
        The features.
    criteria : Mapping[str, bool]
        Criterion name → met (read-only).
    """

    features: WindowFeatures
    criteria: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "criteria", MappingProxyType(dict(self.criteria)))

    @property
    def indoor_like(self) -> bool:
        """``True`` if every criterion is met."""
        return all(self.criteria.values())

    @property
    def regime(self) -> Regime:
        """``INDOOR`` if indoor-like, else ``OUTDOOR``."""
        return Regime.INDOOR if self.indoor_like else Regime.OUTDOOR


class RegimeClassifier:
    """Compute window features and apply the absolute rules (module docstring).

    Parameters
    ----------
    settings : RegimeSettings, optional
        The rules; defaults when omitted.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: RegimeSettings | None = None) -> None:
        self._settings = settings or RegimeSettings()

    @property
    def settings(self) -> RegimeSettings:
        """The rules."""
        return self._settings

    def assess(
        self, t_s: FloatArray, temp_c: FloatArray, rh_pct: FloatArray | None
    ) -> IndoorAssessment:
        """Compute the features of a stretch and check the absolute rules.

        Parameters
        ----------
        t_s : numpy.ndarray of float
            Sample times in seconds, increasing.
        temp_c : numpy.ndarray of float
            Temperatures in °C, no ``NaN``, at least one value.
        rh_pct : numpy.ndarray of float or None
            Relative humidity in % (no ``NaN``), or ``None`` to use temperature only.

        Returns
        -------
        IndoorAssessment
            Features and criteria.
        """
        return self.assess_features(self.features(t_s, temp_c, rh_pct))

    def features(
        self, t_s: FloatArray, temp_c: FloatArray, rh_pct: FloatArray | None
    ) -> WindowFeatures:
        """Compute the features of a stretch.

        Parameters
        ----------
        t_s, temp_c, rh_pct
            As in :meth:`assess`.

        Returns
        -------
        WindowFeatures
            Medians and daily spreads.
        """
        return WindowFeatures(
            temp_median_c=float(np.median(temp_c)),
            daily_spread_c=self._daily_spread(t_s, temp_c),
            rh_median_pct=None if rh_pct is None else float(np.median(rh_pct)),
            rh_daily_spread_pct=None if rh_pct is None else self._daily_spread(t_s, rh_pct),
            n_samples=int(temp_c.size),
        )

    def assess_features(self, features: WindowFeatures) -> IndoorAssessment:
        """Check the absolute rules on given features.

        Parameters
        ----------
        features : WindowFeatures
            Features of a stretch.

        Returns
        -------
        IndoorAssessment
            Features and the result of every criterion.
        """
        settings = self._settings
        criteria = {
            "room_temperature": settings.room_min_c
            <= features.temp_median_c
            <= settings.room_max_c,
            "small_daily_spread": features.daily_spread_c <= settings.indoor_max_daily_spread_c,
        }
        if features.rh_median_pct is not None:
            criteria["moderate_humidity"] = features.rh_median_pct <= settings.indoor_max_rh_pct
        if features.rh_daily_spread_pct is not None:
            criteria["steady_humidity"] = (
                features.rh_daily_spread_pct <= settings.indoor_max_rh_spread_pct
            )
        return IndoorAssessment(features, criteria)

    def _daily_spread(self, t_s: FloatArray, values: FloatArray) -> float:
        window = ((t_s - t_s[0]) // S_PER_DAY).astype(np.int64)
        spreads = [
            _spread(values[window == w])
            for w in np.unique(window)
            if np.count_nonzero(window == w) >= self._settings.min_window_samples
        ]
        return float(np.median(spreads)) if spreads else _spread(values)


def _spread(values: FloatArray) -> float:
    low, high = np.percentile(values, [SPREAD_LOW_PERCENTILE, SPREAD_HIGH_PERCENTILE])
    return float(high - low)
