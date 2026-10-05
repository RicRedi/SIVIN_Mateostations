"""Spike check (:attr:`~sivin.core.flags.QcFlag.SPIKE`): an isolated departure that returns.

Methodology after the step (rate-of-change) test of Zahumenský (2004), applied in both
directions: a sample departs from its predecessor *and* from its successor by more than the
allowed change, with opposite signs. Thresholds are rates scaled by the actual interval, so
irregular sampling is handled. The numeric rates are project defaults for ~30 min data.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import numpy as np
import numpy.typing as npt
from pydantic import Field

from sivin.core.defaults import DEFAULT_SAMPLING_INTERVAL_S
from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck, check_registry
from sivin.quality.samples import S_PER_H, FloatArray, SampleArrays, Variable

logger = logging.getLogger(__name__)

DEFAULT_MAX_NEIGHBOUR_INTERVAL_S = 3 * DEFAULT_SAMPLING_INTERVAL_S
"""Neighbours farther apart than three nominal intervals are not used (project default)."""


class SpikeSettings(CheckSettings):
    """Settings of :class:`SpikeCheck`."""

    temp_max_rate_c_per_h: float = Field(
        8.0,
        gt=0,
        description=(
            "Largest plausible temperature change rate in °C/h towards and away from a sample; "
            "about 4 °C per 30 min interval. Project default for 30-min data [to be tuned on "
            "real data]; methodology Zahumenský (2004)."
        ),
    )
    rh_max_rate_pct_per_h: float = Field(
        40.0,
        gt=0,
        description=(
            "Largest plausible relative-humidity change rate in %/h; about 20 % per 30 min "
            "interval. Project default [to be tuned on real data]; methodology Zahumenský (2004)."
        ),
    )
    min_interval_s: float = Field(
        DEFAULT_SAMPLING_INTERVAL_S,
        gt=0,
        description=(
            "Intervals shorter than this (s) are scaled as if they were this long, so that "
            "closely spaced samples do not get tiny thresholds. Default: nominal interval 1830 s."
        ),
    )
    max_interval_s: float = Field(
        DEFAULT_MAX_NEIGHBOUR_INTERVAL_S,
        gt=0,
        description=(
            "A neighbour farther away than this (s) cannot confirm a spike (the series may have "
            "changed during the gap). Project default: three nominal intervals."
        ),
    )

    def max_rates_per_h(self) -> Mapping[Variable, float]:
        """Return the rate limit per variable.

        Returns
        -------
        Mapping
            Variable → limit in unit/h (°C/h, %/h).
        """
        return {Variable.TEMP: self.temp_max_rate_c_per_h, Variable.RH: self.rh_max_rate_pct_per_h}


@check_registry.register
class SpikeCheck(QualityCheck[SpikeSettings]):
    r"""Flag isolated departures that return to the previous level.

    For each sample :math:`i` with valid neighbours :math:`i-1` and :math:`i+1` (``NaN`` values
    are skipped) let :math:`d^- = x_i - x_{i-1}`, :math:`d^+ = x_{i+1} - x_i` and
    :math:`\Delta t^\pm` the intervals in hours. The sample is a spike if
    :math:`d^- d^+ < 0`, :math:`|d^\pm| > r \max(\Delta t^\pm, \Delta t_{min})` and
    :math:`\Delta t^\pm \le \Delta t_{max}`, where :math:`r` is the rate limit of the variable.
    A row gets ``SPIKE`` if any variable spikes.
    """

    check_id = "spike"
    settings_model = SpikeSettings

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Flag spikes.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        CheckOutcome
            ``SPIKE`` on the departing samples; no events.
        """
        samples = SampleArrays.of(series)
        mask = np.zeros(len(samples), dtype=np.bool_)
        for variable, rate_per_h in self.settings.max_rates_per_h().items():
            mask |= self._spikes(samples.t_s, samples.values(variable), rate_per_h)
        logger.debug("Sensor %s: %d spike(s).", series.sensor_id, int(mask.sum()))
        return CheckOutcome.from_mask(mask, QcFlag.SPIKE)

    def _spikes(
        self, t_s: FloatArray, values: FloatArray, rate_per_h: float
    ) -> npt.NDArray[np.bool_]:
        mask = np.zeros(values.shape, dtype=np.bool_)
        valid = np.flatnonzero(np.isfinite(values))
        if valid.size < 3:
            return mask
        x = values[valid]
        dt_s = np.diff(t_s[valid])
        change = np.diff(x)
        limit = rate_per_h * np.maximum(dt_s, self.settings.min_interval_s) / S_PER_H
        large = (np.abs(change) > limit) & (dt_s <= self.settings.max_interval_s)
        reverses = change[:-1] * change[1:] < 0
        is_spike = large[:-1] & large[1:] & reverses
        mask[valid[1:-1][is_spike]] = True
        return mask
