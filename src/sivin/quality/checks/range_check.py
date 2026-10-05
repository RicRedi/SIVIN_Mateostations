"""Plausible-value (range) check (:attr:`~sivin.core.flags.QcFlag.OUT_OF_RANGE`).

Methodology after Zahumenský (2004): a value outside fixed physical limits or outside
climatological limits of the site is flagged. The numeric limits below are project defaults,
not values quoted from that guideline.
"""

from __future__ import annotations

import logging

import numpy as np
import numpy.typing as npt
from pydantic import Field, model_validator

from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck, check_registry
from sivin.quality.samples import SampleArrays

logger = logging.getLogger(__name__)


class RangeSettings(CheckSettings):
    """Settings of :class:`RangeCheck`."""

    temp_physical_min_c: float = Field(
        -50.0,
        description=(
            "Lowest physically plausible air temperature in °C. Project default "
            "[to be verified against the sensor data sheet]."
        ),
    )
    temp_physical_max_c: float = Field(
        60.0,
        description=(
            "Highest physically plausible air temperature in °C. Project default "
            "[to be verified against the sensor data sheet]."
        ),
    )
    temp_climate_min_c: float | None = Field(
        -30.0,
        description=(
            "Lowest climatologically plausible air temperature in South Moravia in °C; null "
            "disables the climatological lower limit. Project default [to be verified against "
            "station records of the region]."
        ),
    )
    temp_climate_max_c: float | None = Field(
        42.0,
        description=(
            "Highest climatologically plausible air temperature in South Moravia in °C; null "
            "disables the climatological upper limit. Project default [to be verified against "
            "station records of the region]."
        ),
    )
    rh_min_pct: float = Field(
        0.0, description="Lowest possible relative humidity in % (physical limit)."
    )
    rh_max_pct: float = Field(
        100.0, description="Highest possible relative humidity in % (physical limit)."
    )

    @property
    def temp_min_c(self) -> float:
        """Effective lower temperature limit in °C (the narrower of physical and climate)."""
        if self.temp_climate_min_c is None:
            return self.temp_physical_min_c
        return max(self.temp_physical_min_c, self.temp_climate_min_c)

    @property
    def temp_max_c(self) -> float:
        """Effective upper temperature limit in °C (the narrower of physical and climate)."""
        if self.temp_climate_max_c is None:
            return self.temp_physical_max_c
        return min(self.temp_physical_max_c, self.temp_climate_max_c)

    @model_validator(mode="after")
    def _ordered(self) -> RangeSettings:
        if self.temp_min_c > self.temp_max_c:
            raise ValueError("the temperature limits leave no valid range")
        if self.rh_min_pct > self.rh_max_pct:
            raise ValueError("rh_min_pct must not exceed rh_max_pct")
        return self


@check_registry.register
class RangeCheck(QualityCheck[RangeSettings]):
    """Flag values outside physical or climatological limits.

    Temperature is flagged outside the intersection of the physical and the climatological
    limits (:attr:`RangeSettings.temp_min_c`, :attr:`RangeSettings.temp_max_c`). Humidity is
    flagged outside ``[rh_min_pct, rh_max_pct]``. ``NaN`` values are not flagged here.
    """

    check_id = "range"
    settings_model = RangeSettings

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Flag out-of-range values.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        CheckOutcome
            ``OUT_OF_RANGE`` on rows with a temperature or humidity outside the limits.
        """
        settings = self.settings
        samples = SampleArrays.of(series)
        temp_out = _outside(samples.temp_c, settings.temp_min_c, settings.temp_max_c)
        rh_out = _outside(samples.rh_pct, settings.rh_min_pct, settings.rh_max_pct)
        mask = temp_out | rh_out
        logger.debug("Sensor %s: %d value(s) out of range.", series.sensor_id, int(mask.sum()))
        return CheckOutcome.from_mask(mask, QcFlag.OUT_OF_RANGE)


def _outside(values: npt.NDArray[np.float64], low: float, high: float) -> npt.NDArray[np.bool_]:
    """Tell which values lie outside ``[low, high]``; ``NaN`` is not outside."""
    with np.errstate(invalid="ignore"):
        return np.asarray((values < low) | (values > high), dtype=np.bool_)
