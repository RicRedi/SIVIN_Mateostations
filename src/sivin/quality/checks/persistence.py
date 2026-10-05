"""Persistence check (:attr:`~sivin.core.flags.QcFlag.STUCK`): a value that does not change.

Methodology after the persistence (minimum required variability) test of Zahumenský (2004):
a value that stays within a tiny band for longer than a duration indicates a stuck sensor.
The tolerances and durations are project defaults for ~30 min data.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from pydantic import Field

from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck, check_registry
from sivin.quality.samples import S_PER_H, FloatArray, SampleArrays, Variable

logger = logging.getLogger(__name__)


class PersistenceSettings(CheckSettings):
    """Settings of :class:`PersistenceCheck`."""

    temp_tolerance_c: float = Field(
        0.05,
        ge=0,
        description=(
            "Largest temperature range (max - min, °C) of a run that still counts as unchanged; "
            "half of an assumed 0.1 °C resolution. Project default [to be verified against "
            "the sensor resolution]."
        ),
    )
    temp_min_duration_s: float = Field(
        6 * S_PER_H,
        gt=0,
        description=(
            "Shortest duration (s) of an unchanged temperature run that is flagged. Project "
            "default 6 h for 30-min data [to be tuned on real data]."
        ),
    )
    rh_tolerance_pct: float = Field(
        0.5,
        ge=0,
        description=(
            "Largest relative-humidity range (%) of a run that still counts as unchanged; half "
            "of an assumed 1 % resolution. Project default [to be verified]."
        ),
    )
    rh_min_duration_s: float = Field(
        12 * S_PER_H,
        gt=0,
        description=(
            "Shortest duration (s) of an unchanged humidity run that is flagged. Project "
            "default 12 h [to be tuned on real data]."
        ),
    )
    rh_saturation_pct: float | None = Field(
        99.0,
        description=(
            "Humidity runs entirely at or above this value (%) are not flagged: saturated air "
            "(fog, dew) legitimately keeps the reading at its maximum for many hours. Null "
            "disables the exemption. Project default [to be tuned on real data]."
        ),
    )


@dataclass(frozen=True, slots=True)
class _Rule:
    """Persistence rule of one variable."""

    tolerance: float
    min_duration_s: float
    exempt_at_or_above: float | None


@check_registry.register
class PersistenceCheck(QualityCheck[PersistenceSettings]):
    """Flag runs of unchanged values.

    Valid (non-``NaN``) values are scanned left to right; a run grows while
    ``max - min <= tolerance``. A run whose first and last sample are at least the minimum
    duration apart gets ``STUCK`` on all its samples. Humidity runs at saturation are exempt.
    """

    check_id = "persistence"
    settings_model = PersistenceSettings

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Flag stuck values.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        CheckOutcome
            ``STUCK`` on the samples of every long unchanged run; no events.
        """
        samples = SampleArrays.of(series)
        mask = np.zeros(len(samples), dtype=np.bool_)
        for variable, rule in self._rules().items():
            mask |= _stuck(samples.t_s, samples.values(variable), rule)
        logger.debug("Sensor %s: %d stuck sample(s).", series.sensor_id, int(mask.sum()))
        return CheckOutcome.from_mask(mask, QcFlag.STUCK)

    def _rules(self) -> Mapping[Variable, _Rule]:
        settings = self.settings
        return {
            Variable.TEMP: _Rule(settings.temp_tolerance_c, settings.temp_min_duration_s, None),
            Variable.RH: _Rule(
                settings.rh_tolerance_pct, settings.rh_min_duration_s, settings.rh_saturation_pct
            ),
        }


def _stuck(t_s: FloatArray, values: FloatArray, rule: _Rule) -> npt.NDArray[np.bool_]:
    mask = np.zeros(values.shape, dtype=np.bool_)
    valid = np.flatnonzero(np.isfinite(values))
    x = values[valid]
    t = t_s[valid]
    for first, last in _runs(x, rule.tolerance):
        if t[last] - t[first] < rule.min_duration_s:
            continue
        if rule.exempt_at_or_above is not None and x[first : last + 1].min() >= (
            rule.exempt_at_or_above
        ):
            continue
        mask[valid[first : last + 1]] = True
    return mask


def _runs(x: FloatArray, tolerance: float) -> Iterator[tuple[int, int]]:
    """Yield ``(first, last)`` positions of maximal left-to-right runs within ``tolerance``."""
    first = 0
    n_values = x.size
    while first < n_values:
        low = high = x[first]
        last = first
        while last + 1 < n_values:
            candidate = x[last + 1]
            new_low, new_high = min(low, candidate), max(high, candidate)
            if new_high - new_low > tolerance:
                break
            low, high, last = new_low, new_high, last + 1
        yield first, last
        first = last + 1
