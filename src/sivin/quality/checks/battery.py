"""Battery voltage check (WP-1.9): warn when a sensor's battery runs low.

A low battery says nothing about the measurements of that moment, so the check **never flags
rows**: it only reports ``low_battery`` warning events (owner decision Q9, 2026-10-05; a flag is
row-wide and would exclude temperature and humidity).

A voltage near the threshold flaps (0.1 V export resolution, daily temperature swings of the
battery), so the check uses **hysteresis**: a low episode starts at the first reading below
``low_battery_v`` and ends only when a reading reaches ``low_battery_v + recovery_margin_v``.
Readings in between keep the episode open, so a battery hovering around the threshold gives
one event instead of one per dip.
"""

from __future__ import annotations

import logging
from typing import Final

import numpy as np
import numpy.typing as npt
from pydantic import Field

from sivin.core.schema import QC_DTYPE, Column, MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck, check_registry
from sivin.quality.events import EventKind, QualityEvent, Severity

logger = logging.getLogger(__name__)

VOLTAGE_DECIMALS: Final = 6
"""Decimals (of 1 V) to which the recovery voltage is rounded, so that a sum such as
3.3 V + 0.1 V compares equal to a reading of 3.4 V; far below the 0.01 V export resolution."""


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
    recovery_margin_v: float = Field(
        0.1,
        ge=0.0,
        description=(
            "Hysteresis in V: a low battery episode ends only at a reading of at least "
            "low_battery_v + recovery_margin_v (default 3.4 V). 0.1 V is one step of the export "
            "resolution, so a reading that merely returns to the threshold does not end the "
            "episode. Project default [to be tuned]; 0 disables the hysteresis."
        ),
    )


def low_battery_episodes(
    battery_v: npt.NDArray[np.float64], low_v: float, recovery_v: float
) -> tuple[tuple[int, int], ...]:
    """Find low battery episodes with hysteresis.

    Parameters
    ----------
    battery_v : numpy.ndarray of float
        Battery voltages in V, in time order; ``NaN`` (missing) is skipped.
    low_v : float
        A reading below this voltage (V) starts an episode.
    recovery_v : float
        A reading at or above this voltage (V) ends the current episode; ``>= low_v``.

    Returns
    -------
    tuple of (int, int)
        ``(first, last)`` row positions of the first and the last reading below ``low_v`` of
        every episode, in time order.
    """
    episodes: list[tuple[int, int]] = []
    first: int | None = None
    last = 0
    for position in np.flatnonzero(~np.isnan(battery_v)).tolist():
        value = float(battery_v[position])
        if value < low_v:
            first = position if first is None else first
            last = position
        elif first is not None and value >= recovery_v:
            episodes.append((first, last))
            first = None
    if first is not None:
        episodes.append((first, last))
    return tuple(episodes)


@check_registry.register
class BatteryCheck(QualityCheck[BatterySettings]):
    """Report episodes of battery voltages below ``low_battery_v``, with hysteresis.

    Each episode (:func:`low_battery_episodes`) gives one ``low_battery`` warning event from
    its first to its last reading below the threshold, with their number and the lowest
    voltage. Missing voltages are skipped. No row is flagged.
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
            No flags; one warning event per low battery episode.
        """
        settings = self.settings
        battery_v = series.frame[Column.BATTERY].to_numpy(dtype=np.float64)
        with np.errstate(invalid="ignore"):
            low = battery_v < settings.low_battery_v
        times = series.timestamps
        events = []
        recovery_v = round(settings.low_battery_v + settings.recovery_margin_v, VOLTAGE_DECIMALS)
        for first, last in low_battery_episodes(battery_v, settings.low_battery_v, recovery_v):
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
