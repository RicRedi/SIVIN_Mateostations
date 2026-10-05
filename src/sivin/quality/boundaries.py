r"""Exact placement of a regime boundary: likelihood refinement and transport trimming.

* :class:`BoundaryRefiner` moves a boundary to the position with the largest
  level-and-variance likelihood-ratio gain (:mod:`sivin.quality.changepoint`) within a radius
  around its first estimate and within the stretch between its neighbouring boundaries. The
  change-point search works with a minimum segment duration; the refinement does not, so a
  boundary close to another change point is still placed exactly.
* :class:`TransportTrimmer` assigns a short hot or cold transient on the outdoor side of a
  boundary (the sensor in a car between office and vineyard) to the indoor side, so that it
  becomes ``PRE_DEPLOYMENT``: starting at the boundary, samples whose temperature lies outside
  both reference ranges, i.e. outside
  :math:`[\min(P_5^{in}, P_5^{out}) - m,\ \max(P_{95}^{in}, P_{95}^{out}) + m]`, are moved
  over, for at most the maximum transport duration. The outdoor reference is the day of
  outdoor data that follows the maximum transport duration, the indoor reference the day of
  indoor data next to the boundary.
"""

from __future__ import annotations

import logging

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from sivin.quality.changepoint import MIN_SEGMENT_SAMPLES, GaussianSegmentCost
from sivin.quality.regime import SPREAD_HIGH_PERCENTILE, SPREAD_LOW_PERCENTILE
from sivin.quality.samples import S_PER_DAY, S_PER_H, FloatArray

logger = logging.getLogger(__name__)


class TransportSettings(BaseModel):
    """Settings of :class:`TransportTrimmer` (project defaults)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_duration_s: float = Field(
        3 * S_PER_H,
        ge=0,
        description=(
            "Longest transport transient (s) moved to the indoor side; 0 disables trimming. "
            "Project default 3 h."
        ),
    )
    margin_c: float = Field(
        3.0,
        ge=0,
        description=(
            "Margin m (°C) around the indoor and outdoor reference ranges. Project default."
        ),
    )
    reference_s: float = Field(
        S_PER_DAY,
        gt=0,
        description="Length (s) of the outdoor reference stretch. Project default 1 day.",
    )
    min_reference_samples: int = Field(
        12,
        ge=2,
        description="Fewest samples (count) of the reference stretch; fewer disables trimming.",
    )


class BoundaryRefiner:
    """Move a boundary to the largest likelihood-ratio gain nearby (module docstring).

    Parameters
    ----------
    radius_s : float
        Largest distance (s) from the first estimate.
    variance_floors : tuple of float
        Variance floor per data column (°C², %²).
    """

    __slots__ = ("_radius_s", "_variance_floors")

    def __init__(self, radius_s: float, variance_floors: tuple[float, ...]) -> None:
        self._radius_s = radius_s
        self._variance_floors = variance_floors

    def refine(
        self,
        t_s: FloatArray,
        data: npt.NDArray[np.float64],
        position: int,
        low: int,
        high: int,
    ) -> int:
        """Return the refined boundary.

        Parameters
        ----------
        t_s : numpy.ndarray of float
            Sample times in seconds.
        data : numpy.ndarray of float, shape (n, d)
            Values per sample and variable.
        position : int
            First estimate (first sample of the new regime).
        low, high : int
            The boundary must stay within ``(low, high)``.

        Returns
        -------
        int
            The refined position, or ``position`` if there is no room to search.
        """
        # Measured from the samples on both sides, so that a gap at the boundary does not
        # shrink the search span to one side.
        start = max(low, int(np.searchsorted(t_s, t_s[position - 1] - self._radius_s)))
        end = min(high, int(np.searchsorted(t_s, t_s[position] + self._radius_s, side="right")))
        candidates = np.arange(MIN_SEGMENT_SAMPLES, end - start - MIN_SEGMENT_SAMPLES + 1)
        if candidates.size == 0:
            return position
        floors = np.array(self._variance_floors[: data.shape[1]])
        cost = GaussianSegmentCost(data[start:end], floors)
        gains = cost.split_gains(0, end - start, candidates)
        return start + int(candidates[int(np.argmax(gains))])


class TransportTrimmer:
    """Move a short transient next to a boundary to the indoor side (module docstring).

    Parameters
    ----------
    settings : TransportSettings, optional
        Settings; defaults when omitted.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: TransportSettings | None = None) -> None:
        self._settings = settings or TransportSettings()

    @property
    def guard_s(self) -> float:
        """Maximum transport duration (s): indoor windows keep this distance from a boundary."""
        return self._settings.max_duration_s

    def trim(
        self,
        t_s: FloatArray,
        temp_c: FloatArray,
        position: int,
        indoor_limit: int,
        outdoor_limit: int,
    ) -> int:
        """Return the boundary with the transport transient moved to the indoor side.

        Parameters
        ----------
        t_s : numpy.ndarray of float
            Sample times in seconds.
        temp_c : numpy.ndarray of float
            Temperatures in °C.
        position : int
            Boundary: first sample of the new regime.
        indoor_limit : int
            Far end of the indoor stretch: its first sample for a deployment, its exclusive end
            for a retrieval.
        outdoor_limit : int
            Far end of the outdoor stretch: its exclusive end for a deployment, its first
            sample for a retrieval.

        Returns
        -------
        int
            The adjusted boundary.
        """
        settings = self._settings
        if settings.max_duration_s == 0:
            return position
        deployment = indoor_limit < position
        sign = 1 if deployment else -1
        first = position if deployment else position - 1
        t_edge = t_s[first]
        outdoor = self._percentiles(
            t_s, temp_c, t_edge + sign * settings.max_duration_s, sign, outdoor_limit
        )
        indoor = self._percentiles(
            t_s, temp_c, t_s[position - 1 if deployment else position], -sign, indoor_limit
        )
        if outdoor is None or indoor is None:
            return position
        low = min(outdoor[0], indoor[0]) - settings.margin_c
        high = max(outdoor[1], indoor[1]) + settings.margin_c
        current = first
        inside = range(position, outdoor_limit) if deployment else range(outdoor_limit, position)
        while (
            current in inside
            and abs(t_s[current] - t_edge) < settings.max_duration_s
            and not low <= temp_c[current] <= high
        ):
            current += sign
        moved = current if deployment else current + 1
        if moved != position:
            logger.debug("Transport transient: boundary moved by %d sample(s).", moved - position)
        return moved

    def _percentiles(
        self, t_s: FloatArray, temp_c: FloatArray, t_from: float, sign: int, limit: int
    ) -> tuple[float, float] | None:
        """P5 and P95 of the reference stretch from ``t_from`` in direction ``sign``."""
        low_t, high_t = sorted((t_from, t_from + sign * self._settings.reference_s))
        start = int(np.searchsorted(t_s, low_t))
        end = int(np.searchsorted(t_s, high_t, side="right"))
        start, end = (start, min(end, limit)) if sign > 0 else (max(start, limit), end)
        if end - start < self._settings.min_reference_samples:
            return None
        p_low, p_high = np.percentile(
            temp_c[start:end], [SPREAD_LOW_PERCENTILE, SPREAD_HIGH_PERCENTILE]
        )
        return float(p_low), float(p_high)
