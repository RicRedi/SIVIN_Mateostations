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
        12 * S_PER_H,
        gt=0,
        description=(
            "Shortest duration (s) of an unchanged temperature run that is flagged. Project "
            "default 12 h for 30-min data, longer than calm isothermal nights "
            "[to be tuned on real data]."
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
        97.0,
        description=(
            "Relative humidity (%) at or above which the air counts as saturated. A run "
            "(temperature or humidity) in which at least saturation_share of the samples are "
            "saturated is not flagged: in fog or an inversion both readings legitimately stay "
            "constant for many hours. Null disables the exemption. Project default "
            "[to be tuned on real data]."
        ),
    )
    saturation_share: float = Field(
        0.5,
        gt=0,
        le=1,
        description=(
            "Share (0-1, dimensionless) of saturated samples that exempts a run. Project default."
        ),
    )


@dataclass(frozen=True, slots=True)
class _Rule:
    """Persistence rule of one variable."""

    tolerance: float
    min_duration_s: float
    saturation_share: float


@check_registry.register
class PersistenceCheck(QualityCheck[PersistenceSettings]):
    """Flag runs of unchanged values.

    Valid (non-``NaN``) values are scanned left to right; a run grows while
    ``max - min <= tolerance``. A run whose first and last sample are at least the minimum
    duration apart gets ``STUCK`` on all its samples, unless at least ``saturation_share`` of
    its samples have saturated humidity (fog, inversion), for either variable.
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
        saturation = self.settings.rh_saturation_pct
        with np.errstate(invalid="ignore"):
            saturated = (
                np.zeros(len(samples), dtype=np.bool_)
                if saturation is None
                else np.asarray(samples.rh_pct >= saturation, dtype=np.bool_)
            )
        mask = np.zeros(len(samples), dtype=np.bool_)
        for variable, rule in self._rules().items():
            mask |= _stuck(samples.t_s, samples.values(variable), saturated, rule)
        logger.debug("Sensor %s: %d stuck sample(s).", series.sensor_id, int(mask.sum()))
        return CheckOutcome.from_mask(mask, QcFlag.STUCK)

    def _rules(self) -> Mapping[Variable, _Rule]:
        settings = self.settings
        share = settings.saturation_share
        return {
            Variable.TEMP: _Rule(settings.temp_tolerance_c, settings.temp_min_duration_s, share),
            Variable.RH: _Rule(settings.rh_tolerance_pct, settings.rh_min_duration_s, share),
        }


def _stuck(
    t_s: FloatArray, values: FloatArray, saturated: npt.NDArray[np.bool_], rule: _Rule
) -> npt.NDArray[np.bool_]:
    mask = np.zeros(values.shape, dtype=np.bool_)
    valid = np.flatnonzero(np.isfinite(values))
    x = values[valid]
    t = t_s[valid]
    for first, last in _runs(x, rule.tolerance):
        if t[last] - t[first] < rule.min_duration_s:
            continue
        rows = valid[first : last + 1]
        if saturated[rows].mean() >= rule.saturation_share:
            continue
        mask[rows] = True
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
