"""Battery voltage check (WP-1.9): warn when a sensor's battery runs low.

A low battery says nothing about the measurements of that moment, so the check **never flags
rows**: it only reports ``low_battery`` warning events (owner decision Q9, 2026-10-05; a flag is
row-wide and would exclude temperature and humidity).
"""

from __future__ import annotations

import logging

import numpy as np
from pydantic import Field

from sivin.core.schema import QC_DTYPE, Column, MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck, check_registry
from sivin.quality.checks.range_check import runs_of
from sivin.quality.events import EventKind, QualityEvent, Severity

logger = logging.getLogger(__name__)


class BatterySettings(CheckSettings):
    """Settings of :class:`BatteryCheck`."""

    low_battery_v: float = Field(
        3.3,
        gt=0.0,
        description=(
            "Battery voltage in V below which a 'low battery' warning is reported. Project "
            "default [to be tuned]: the first real export reads 3.0-3.7 V; the voltage at "
            "which the device stops measuring is not known [to be verified against the "
            "device data sheet]."
        ),
    )


@check_registry.register
class BatteryCheck(QualityCheck[BatterySettings]):
    """Report runs of battery voltages below ``low_battery_v``.

    Consecutive low readings (missing values in between neither end nor extend a run) form one
    ``low_battery`` warning event from the first to the last of them, with the lowest voltage.
    Missing voltages are not reported. No row is flagged.
    """

    check_id = "battery"
    settings_model = BatterySettings

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Report low battery voltage (see the class docstring).

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        CheckOutcome
            No flags; one warning event per run of low readings.
        """
        battery_v = series.frame[Column.BATTERY].to_numpy(dtype=np.float64)
        with np.errstate(invalid="ignore"):
            low = battery_v < self.settings.low_battery_v
        times = series.timestamps
        events = []
        for first, last in runs_of(low, ~np.isnan(battery_v)):
            run = battery_v[first : last + 1][low[first : last + 1]]
            events.append(
                QualityEvent(
                    kind=EventKind.LOW_BATTERY,
                    t_utc=times.iloc[first],
                    end_utc=times.iloc[last],
                    detail=(
                        f"low battery: {len(run)} reading(s) below "
                        f"{self.settings.low_battery_v:g} V (lowest {run.min():g} V)"
                    ),
                    severity=Severity.WARNING,
                    origin=self.check_id,
                )
            )
        logger.debug("Sensor %s: %d low battery reading(s).", series.sensor_id, int(np.sum(low)))
        return CheckOutcome(flags=np.zeros(len(series), dtype=QC_DTYPE), events=tuple(events))
