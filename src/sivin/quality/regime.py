r"""Indoor / outdoor regime of a segment, from transparent rules.

A sensor in the office shows a temperature close to a comfort band, a small daily range and
low humidity; in the vineyard it follows the weather with a large daily range. For one segment
:class:`RegimeClassifier` computes three robust features

* the median temperature :math:`\tilde T` (°C) and its distance :math:`d` from the comfort band
  :math:`[T_{lo}, T_{hi}]`: :math:`d = \max(T_{lo} - \tilde T, \tilde T - T_{hi}, 0)`,
* the daily spread :math:`s` (°C): the median over the segment's consecutive 24-h windows
  (counted from its first sample; windows with fewer than ``min_window_samples`` samples are
  skipped, and if none is left the whole segment is one window) of :math:`P_{95} - P_{5}` of
  the temperature,
* the median relative humidity :math:`\tilde h` (%), if humidity is available,

turns each into a membership in "indoor" between 0 and 1 with a linear ramp

.. math::

    \mu_{band} = 1 - \operatorname{clip}(d / r_T, 0, 1), \quad
    \mu_{spread} = 1 - \operatorname{clip}((s - s_{max}) / r_s, 0, 1), \quad
    \mu_{rh} = 1 - \operatorname{clip}((\tilde h - h_{max}) / r_h, 0, 1),

and combines them with a logical AND (minimum): :math:`S = \min(\mu_{band}, \mu_{spread},
\mu_{rh})`. The segment is indoor if :math:`S \ge S_0`; the confidence of the label is
:math:`|2S - 1|`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sivin.quality.samples import S_PER_DAY, FloatArray

logger = logging.getLogger(__name__)

SPREAD_LOW_PERCENTILE = 5.0
"""Lower percentile of the daily spread (robust against a single spike)."""

SPREAD_HIGH_PERCENTILE = 95.0
"""Upper percentile of the daily spread (robust against a single spike)."""


class Regime(StrEnum):
    """Where the sensor is."""

    INDOOR = "indoor"
    """Office, store or transport: before deployment or during service."""
    OUTDOOR = "outdoor"
    """In the vineyard."""


class RegimeSettings(BaseModel):
    """Rules of :class:`RegimeClassifier` (all project defaults, to be tuned on real data)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    comfort_band_low_c: float = Field(
        18.0,
        description="Lower edge of the indoor comfort band T_lo in °C. Project default.",
    )
    comfort_band_high_c: float = Field(
        27.0,
        description="Upper edge of the indoor comfort band T_hi in °C. Project default.",
    )
    band_ramp_c: float = Field(
        4.0,
        gt=0,
        description=(
            "Distance r_T (°C) of the median temperature outside the comfort band at which the "
            "band membership reaches 0. Project default."
        ),
    )
    indoor_max_daily_spread_c: float = Field(
        3.0,
        ge=0,
        description=(
            "Daily spread s_max (P95 - P5 of temperature per 24 h, °C) up to which a segment "
            "fully looks indoor. Project default [to be tuned on real data]."
        ),
    )
    spread_ramp_c: float = Field(
        3.0,
        gt=0,
        description=(
            "Additional spread r_s (°C) above s_max at which the spread membership reaches 0. "
            "Project default."
        ),
    )
    indoor_max_rh_pct: float = Field(
        65.0,
        description=(
            "Median relative humidity h_max (%) up to which a segment fully looks indoor. "
            "Project default [to be tuned on real data]."
        ),
    )
    rh_ramp_pct: float = Field(
        15.0,
        gt=0,
        description=(
            "Additional humidity r_h (%) above h_max at which the humidity membership reaches "
            "0. Project default."
        ),
    )
    indoor_threshold: float = Field(
        0.5,
        gt=0,
        lt=1,
        description="Indoor score S_0 (0-1, dimensionless) at or above which a segment is indoor.",
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
        if self.comfort_band_low_c > self.comfort_band_high_c:
            raise ValueError("comfort_band_low_c must not exceed comfort_band_high_c")
        return self


@dataclass(frozen=True, slots=True)
class SegmentFeatures:
    """Robust features of one segment.

    Attributes
    ----------
    temp_median_c : float
        Median temperature in °C.
    daily_spread_c : float
        Median over 24-h windows of the P95 - P5 temperature spread, in °C.
    rh_median_pct : float or None
        Median relative humidity in %, ``None`` without humidity data.
    """

    temp_median_c: float
    daily_spread_c: float
    rh_median_pct: float | None


@dataclass(frozen=True, slots=True)
class RegimeVerdict:
    """The regime of one segment and why.

    Attributes
    ----------
    regime : Regime
        The label.
    indoor_score : float
        Score :math:`S` (0-1, dimensionless); 1 = clearly indoor.
    confidence : float
        :math:`|2S - 1|` (0-1, dimensionless).
    features : SegmentFeatures
        The features the label is based on.
    """

    regime: Regime
    indoor_score: float
    confidence: float
    features: SegmentFeatures


class RegimeClassifier:
    """Label a segment indoor or outdoor (rules in the module docstring).

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

    def classify(
        self, t_s: FloatArray, temp_c: FloatArray, rh_pct: FloatArray | None
    ) -> RegimeVerdict:
        """Classify one segment.

        Parameters
        ----------
        t_s : numpy.ndarray of float
            Sample times in seconds, increasing.
        temp_c : numpy.ndarray of float
            Temperatures in °C, no ``NaN``.
        rh_pct : numpy.ndarray of float or None
            Relative humidity in % (no ``NaN``), or ``None`` to classify on temperature only.

        Returns
        -------
        RegimeVerdict
            Label, score, confidence and features.
        """
        features = self.features(t_s, temp_c, rh_pct)
        score = self.indoor_score(features)
        regime = Regime.INDOOR if score >= self._settings.indoor_threshold else Regime.OUTDOOR
        return RegimeVerdict(regime, score, abs(2.0 * score - 1.0), features)

    def features(
        self, t_s: FloatArray, temp_c: FloatArray, rh_pct: FloatArray | None
    ) -> SegmentFeatures:
        """Compute the features of one segment.

        Parameters
        ----------
        t_s, temp_c, rh_pct
            As in :meth:`classify`.

        Returns
        -------
        SegmentFeatures
            Median temperature, daily spread and median humidity.
        """
        return SegmentFeatures(
            temp_median_c=float(np.median(temp_c)),
            daily_spread_c=self._daily_spread_c(t_s, temp_c),
            rh_median_pct=None if rh_pct is None else float(np.median(rh_pct)),
        )

    def indoor_score(self, features: SegmentFeatures) -> float:
        """Combine the memberships into the indoor score :math:`S`.

        Parameters
        ----------
        features : SegmentFeatures
            Features of a segment.

        Returns
        -------
        float
            :math:`S` in 0-1 (dimensionless).
        """
        settings = self._settings
        distance_c = max(
            settings.comfort_band_low_c - features.temp_median_c,
            features.temp_median_c - settings.comfort_band_high_c,
            0.0,
        )
        memberships = [
            _falling_ramp(distance_c, 0.0, settings.band_ramp_c),
            _falling_ramp(
                features.daily_spread_c, settings.indoor_max_daily_spread_c, settings.spread_ramp_c
            ),
        ]
        if features.rh_median_pct is not None:
            memberships.append(
                _falling_ramp(
                    features.rh_median_pct, settings.indoor_max_rh_pct, settings.rh_ramp_pct
                )
            )
        return min(memberships)

    def _daily_spread_c(self, t_s: FloatArray, temp_c: FloatArray) -> float:
        window = ((t_s - t_s[0]) // S_PER_DAY).astype(np.int64)
        spreads = [
            _spread(temp_c[window == w])
            for w in np.unique(window)
            if np.count_nonzero(window == w) >= self._settings.min_window_samples
        ]
        return float(np.median(spreads)) if spreads else _spread(temp_c)


def _spread(values: FloatArray) -> float:
    low, high = np.percentile(values, [SPREAD_LOW_PERCENTILE, SPREAD_HIGH_PERCENTILE])
    return float(high - low)


def _falling_ramp(value: float, full_until: float, width: float) -> float:
    """1 up to ``full_until``, falling linearly to 0 at ``full_until + width``."""
    return float(1.0 - np.clip((value - full_until) / width, 0.0, 1.0))
