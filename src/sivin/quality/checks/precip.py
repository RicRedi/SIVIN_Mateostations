"""Precipitation checks (WP-1.9): plausible range per interval and the cumulative counter.

The sensors report two precipitation columns (MIGRATION_PLAN §2.5): ``precip_mm``, the
precipitation in the interval since the previous sample, and ``precip_total_mm``, the device's
cumulative counter. In the first real export the interval value of a sample equals the increase
of the counter since the previous sample, up to 0.1 mm (MIGRATION_PLAN §0.6.1; e.g. sensor
77799986, 2025-12-19 14:07:16 local: interval 0.3 mm, counter 323.6 -> 324.0 mm).

**These checks never set row flags.** A :class:`~sivin.core.flags.QcFlag` belongs to the whole
row, and the exclusion mask would then also drop the temperature and humidity of that row,
although only the precipitation is wrong (owner decision Q9, 2026-10-05: the validity rule
concerns temperature and humidity only). Instead:

* :class:`PrecipRangeCheck` reports implausible values as ``precip_out_of_range`` events, and
  :meth:`PrecipRangeCheck.set_aside` returns the series with exactly those values replaced by
  ``NaN`` (:meth:`~sivin.core.schema.MeasurementSeries.with_values`). The row, its flags and its
  temperature and humidity stay as they are.
* :class:`PrecipCounterCheck` reports counter resets (``precip_counter_reset``, informative) and
  disagreements between interval values and counter increases (``precip_counter_mismatch``,
  warning). It changes no value: which of the two columns is wrong cannot be told from the
  data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from pydantic import Field, model_validator

from sivin.core.defaults import DEFAULT_SAMPLING_INTERVAL_S
from sivin.core.schema import QC_DTYPE, Column, MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck, check_registry
from sivin.quality.checks.range_check import runs_of
from sivin.quality.events import EventKind, QualityEvent, Severity
from sivin.quality.samples import NS_PER_S, FloatArray

logger = logging.getLogger(__name__)

BoolArray = npt.NDArray[np.bool_]

COUNTER_MAX_INTERVAL_FACTOR: Final = 1.5
"""Factor on the nominal sampling interval (dimensionless) up to which two consecutive samples
count as neighbours for the counter comparison (project choice: one regular step with jitter,
not two)."""


class PrecipRangeSettings(CheckSettings):
    """Settings of :class:`PrecipRangeCheck`."""

    precip_min_mm: float = Field(
        0.0,
        description=(
            "Lowest plausible precipitation of one sample interval in mm (physical limit: an "
            "amount of precipitation cannot be negative)."
        ),
    )
    precip_max_mm: float = Field(
        50.0,
        gt=0.0,
        description=(
            "Highest plausible precipitation of one sample interval (nominal 1830 s, about "
            "30 min) in mm. Project default [to be tuned]: far above the largest value of the "
            "first real export (0.9 mm) and meant to catch device or transfer errors, not "
            "heavy rain; not taken from literature."
        ),
    )

    @model_validator(mode="after")
    def _ordered(self) -> PrecipRangeSettings:
        if self.precip_min_mm >= self.precip_max_mm:
            raise ValueError("precip_min_mm must be lower than precip_max_mm")
        return self


@check_registry.register
class PrecipRangeCheck(QualityCheck[PrecipRangeSettings]):
    """Report precipitation values outside ``[precip_min_mm, precip_max_mm]`` per interval.

    Missing values are not reported. Consecutive implausible values (missing ones in between
    neither end nor extend a run) form one ``precip_out_of_range`` warning event from the first
    to the last of them. No row is flagged; :meth:`set_aside` removes the values themselves.
    """

    check_id = "precip_range"
    settings_model = PrecipRangeSettings

    def out_of_range(self, series: MeasurementSeries) -> BoolArray:
        """Tell which precipitation values are implausible.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        numpy.ndarray of bool
            ``True`` for every row whose ``precip_mm`` (mm) lies outside the range; ``False``
            for missing values.
        """
        precip_mm = series.frame[Column.PRECIP].to_numpy(dtype=np.float64)
        with np.errstate(invalid="ignore"):
            outside = (precip_mm < self.settings.precip_min_mm) | (
                precip_mm > self.settings.precip_max_mm
            )
        return np.asarray(outside, dtype=np.bool_)

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Report implausible precipitation (see the class docstring).

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        CheckOutcome
            No flags; one warning event per run of implausible values.
        """
        outside = self.out_of_range(series)
        precip_mm = series.frame[Column.PRECIP].to_numpy(dtype=np.float64)
        times = series.timestamps
        events = []
        for first, last in runs_of(outside, ~np.isnan(precip_mm)):
            run = precip_mm[first : last + 1][outside[first : last + 1]]
            events.append(
                QualityEvent(
                    kind=EventKind.PRECIP_OUT_OF_RANGE,
                    t_utc=times.iloc[first],
                    end_utc=times.iloc[last],
                    detail=(
                        f"{len(run)} precipitation value(s) outside "
                        f"[{self.settings.precip_min_mm:g}, {self.settings.precip_max_mm:g}] mm "
                        f"per interval (lowest {run.min():g} mm, highest {run.max():g} mm); "
                        "temperature and humidity are unaffected"
                    ),
                    severity=Severity.WARNING,
                    origin=self.check_id,
                )
            )
        logger.debug(
            "Sensor %s: %d precipitation value(s) out of range.",
            series.sensor_id,
            int(outside.sum()),
        )
        return CheckOutcome(flags=np.zeros(len(series), dtype=QC_DTYPE), events=tuple(events))

    def set_aside(self, series: MeasurementSeries) -> MeasurementSeries:
        """Return the series with the implausible precipitation values replaced by ``NaN``.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements (e.g. :attr:`~sivin.quality.pipeline.QualityResult.series`).

        Returns
        -------
        MeasurementSeries
            The same rows, flags and other columns; only ``precip_mm`` values outside the range
            are missing.
        """
        precip_mm = series.frame[Column.PRECIP].to_numpy(dtype=np.float64)
        return series.with_values(
            Column.PRECIP, np.where(self.out_of_range(series), np.nan, precip_mm)
        )


class PrecipCounterSettings(CheckSettings):
    """Settings of :class:`PrecipCounterCheck`."""

    tolerance_mm: float = Field(
        0.15,
        gt=0.0,
        description=(
            "Largest difference in mm between the interval precipitation of a sample and the "
            "increase of the counter since the previous sample that still counts as agreement; "
            "also the largest counter decrease that is not a reset. Both columns are exported "
            "with 0.1 mm resolution and the first real export shows differences of 0.1 mm "
            "(MIGRATION_PLAN §0.6.1). Project default [to be tuned]."
        ),
    )
    max_interval_s: float = Field(
        COUNTER_MAX_INTERVAL_FACTOR * DEFAULT_SAMPLING_INTERVAL_S,
        gt=0.0,
        description=(
            "Longest time between two consecutive samples in s for which the interval "
            "precipitation is compared with the counter increase (1.5 x the nominal interval "
            "of 1830 s). After a longer gap the counter also contains the precipitation of "
            "samples that are missing. Project default [to be tuned]."
        ),
    )


@dataclass(frozen=True, slots=True)
class CounterSteps:
    """Comparison of interval precipitation with the counter, per sample.

    Attributes
    ----------
    increase_mm : numpy.ndarray of float
        Counter value minus the previous present counter value in mm; ``NaN`` for the first
        present counter value and where the counter is missing.
    reset : numpy.ndarray of bool
        The counter decreased by more than the tolerance (device reset).
    compared : numpy.ndarray of bool
        The sample was compared: interval value and counter present, the previous row has a
        counter value, at most ``max_interval_s`` earlier, and the step is no reset.
    mismatch : numpy.ndarray of bool
        Compared samples whose interval value and counter increase differ by more than the
        tolerance.
    """

    increase_mm: FloatArray
    reset: BoolArray
    compared: BoolArray
    mismatch: BoolArray

    @classmethod
    def of(
        cls,
        t_s: FloatArray,
        precip_mm: FloatArray,
        precip_total_mm: FloatArray,
        settings: PrecipCounterSettings,
    ) -> CounterSteps:
        """Compare the two columns.

        Parameters
        ----------
        t_s : numpy.ndarray of float
            Sample times in s, increasing.
        precip_mm : numpy.ndarray of float
            Precipitation since the previous sample in mm (``NaN`` = missing).
        precip_total_mm : numpy.ndarray of float
            Cumulative counter in mm (``NaN`` = missing).
        settings : PrecipCounterSettings
            Tolerance and the longest compared interval.

        Returns
        -------
        CounterSteps
            The per-sample comparison.
        """
        n_rows = len(t_s)
        increase_mm = np.full(n_rows, np.nan, dtype=np.float64)
        present = np.flatnonzero(~np.isnan(precip_total_mm))
        increase_mm[present[1:]] = np.diff(precip_total_mm[present])
        with np.errstate(invalid="ignore"):
            reset = increase_mm < -settings.tolerance_mm
        neighbour = np.zeros(n_rows, dtype=np.bool_)
        neighbour[1:] = ~np.isnan(precip_total_mm[:-1]) & (np.diff(t_s) <= settings.max_interval_s)
        compared = neighbour & ~np.isnan(increase_mm) & ~np.isnan(precip_mm) & ~reset
        with np.errstate(invalid="ignore"):
            mismatch = compared & (np.abs(precip_mm - increase_mm) > settings.tolerance_mm)
        return cls(increase_mm, reset, compared, mismatch)


@check_registry.register
class PrecipCounterCheck(QualityCheck[PrecipCounterSettings]):
    """Check the interval precipitation against the cumulative counter.

    For two neighbouring samples (both with a counter value, at most ``max_interval_s`` apart)
    the interval value of the later one should equal the counter increase within
    ``tolerance_mm``. A counter **decrease** by more than the tolerance is a device reset: an
    informative ``precip_counter_reset`` event, not an error, and that step is not compared.
    Runs of disagreeing samples form one ``precip_counter_mismatch`` warning event each. No row
    is flagged and no value is changed (module docstring).
    """

    check_id = "precip_counter"
    settings_model = PrecipCounterSettings

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Compare interval values with the counter (see the class docstring).

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        CheckOutcome
            No flags; reset and mismatch events.
        """
        frame = series.frame
        times = series.timestamps
        t_s = times.to_numpy(dtype="datetime64[ns]").view(np.int64) / NS_PER_S
        precip_mm = frame[Column.PRECIP].to_numpy(dtype=np.float64)
        total_mm = frame[Column.PRECIP_TOTAL].to_numpy(dtype=np.float64)
        steps = CounterSteps.of(t_s, precip_mm, total_mm, self.settings)
        events = [
            QualityEvent(
                kind=EventKind.PRECIP_COUNTER_RESET,
                t_utc=times.iloc[position],
                detail=(
                    f"precipitation counter decreased by {-steps.increase_mm[position]:.3g} mm "
                    f"to {total_mm[position]:g} mm (device reset)"
                ),
                severity=Severity.INFO,
                origin=self.check_id,
            )
            for position in np.flatnonzero(steps.reset)
        ]
        for first, last in runs_of(steps.mismatch, steps.compared):
            run = steps.mismatch[first : last + 1]
            difference_mm = np.abs(precip_mm - steps.increase_mm)[first : last + 1][run]
            events.append(
                QualityEvent(
                    kind=EventKind.PRECIP_COUNTER_MISMATCH,
                    t_utc=times.iloc[first],
                    end_utc=times.iloc[last],
                    detail=(
                        f"{int(run.sum())} interval precipitation value(s) differ from the "
                        f"counter increase by more than {self.settings.tolerance_mm:g} mm "
                        f"(largest difference {difference_mm.max():.3g} mm)"
                    ),
                    severity=Severity.WARNING,
                    origin=self.check_id,
                )
            )
        logger.debug(
            "Sensor %s: %d counter reset(s), %d of %d compared interval(s) disagree.",
            series.sensor_id,
            int(steps.reset.sum()),
            int(steps.mismatch.sum()),
            int(steps.compared.sum()),
        )
        return CheckOutcome(flags=np.zeros(len(series), dtype=QC_DTYPE), events=tuple(events))
