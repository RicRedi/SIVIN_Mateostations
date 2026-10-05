r"""Sampling check: gaps, irregular and non-positive sampling intervals.

The sensors sample about every 1830 s, but their clocks drift (MIGRATION_PLAN §2.7). An
interval :math:`\Delta t_i = t_i - t_{i-1}` is classified as

* **non-positive** if :math:`\Delta t_i \le 0` (cannot occur in a valid
  :class:`~sivin.core.schema.MeasurementSeries`, checked for raw arrays),
* a **gap** if :math:`\Delta t_i > k \, \Delta t_0`,
* **regular** if it is within :math:`\pm \varepsilon \, \Delta t_0` of a whole multiple
  :math:`n \Delta t_0` (:math:`n \ge 1`; :math:`n \ge 2` means missed samples),
* **irregular** otherwise.

Irregular and non-positive intervals flag their later sample ``TIMESTAMP_SUSPECT``
(informative); gaps produce events only, because no sample is wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from pydantic import Field

from sivin.core.defaults import DEFAULT_SAMPLING_INTERVAL_S
from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck, check_registry
from sivin.quality.events import EventKind, QualityEvent, Severity
from sivin.quality.samples import S_PER_H, FloatArray, SampleArrays

logger = logging.getLogger(__name__)

BoolArray = npt.NDArray[np.bool_]


class SamplingSettings(CheckSettings):
    """Settings of :class:`SamplingCheck`."""

    expected_interval_s: float = Field(
        DEFAULT_SAMPLING_INTERVAL_S,
        gt=0,
        description=(
            "Nominal sampling interval Δt0 in seconds. Set from time.expected_interval_s by "
            "the configuration (WP-1.7); default 1830 s, the median step of the first real "
            "export."
        ),
    )
    gap_factor: float = Field(
        3.0,
        gt=1,
        description=(
            "An interval longer than gap_factor x Δt0 (dimensionless factor k) is a gap. "
            "Project default [to be tuned on real data]."
        ),
    )
    tolerance_fraction: float = Field(
        0.25,
        gt=0,
        lt=0.5,
        description=(
            "Allowed deviation ε of an interval from a whole multiple of Δt0, as a fraction of "
            "Δt0 (dimensionless). Project default chosen to tolerate clock drift [to be tuned]."
        ),
    )


@dataclass(frozen=True, slots=True)
class IntervalClasses:
    """Classification of the sampling intervals of a series.

    Each array has one entry per sample; entry ``i`` describes the interval ending at sample
    ``i`` (entry 0 is always ``False``).

    Attributes
    ----------
    non_positive, gap, irregular : numpy.ndarray of bool
        The interval is ≤ 0, longer than the gap threshold, or irregular.
    """

    non_positive: BoolArray
    gap: BoolArray
    irregular: BoolArray


def classify_intervals(t_s: FloatArray, settings: SamplingSettings) -> IntervalClasses:
    """Classify the intervals between consecutive sample times.

    Parameters
    ----------
    t_s : numpy.ndarray of float
        Sample times in seconds (any epoch), in recorded order.
    settings : SamplingSettings
        Expected interval, gap factor and tolerance.

    Returns
    -------
    IntervalClasses
        Masks aligned with ``t_s``.
    """
    dt_s = np.concatenate(([np.nan], np.diff(t_s)))
    expected_s = settings.expected_interval_s
    with np.errstate(invalid="ignore"):
        non_positive = dt_s <= 0
        gap = dt_s > settings.gap_factor * expected_s
        multiple = np.maximum(np.rint(dt_s / expected_s), 1.0)
        off_grid = np.abs(dt_s - multiple * expected_s) > settings.tolerance_fraction * expected_s
    irregular = off_grid & ~non_positive & ~gap & np.isfinite(dt_s)
    return IntervalClasses(
        non_positive=np.asarray(non_positive, dtype=np.bool_),
        gap=np.asarray(gap, dtype=np.bool_),
        irregular=np.asarray(irregular, dtype=np.bool_),
    )


@check_registry.register
class SamplingCheck(QualityCheck[SamplingSettings]):
    """Report gaps and irregular sampling (see the module docstring for the rules)."""

    check_id = "sampling"
    settings_model = SamplingSettings

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Check the sampling intervals.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        CheckOutcome
            ``TIMESTAMP_SUSPECT`` on the later sample of irregular or non-positive intervals;
            one ``gap`` event per gap and one summary event per kind of irregularity.
        """
        samples = SampleArrays.of(series)
        classes = classify_intervals(samples.t_s, self.settings)
        events = [self._gap_event(samples, int(i)) for i in np.flatnonzero(classes.gap)]
        events += self._summary(samples, classes.irregular, EventKind.IRREGULAR_SAMPLING)
        events += self._summary(samples, classes.non_positive, EventKind.NON_POSITIVE_INTERVAL)
        logger.debug(
            "Sensor %s: %d gap(s), %d irregular interval(s).",
            series.sensor_id,
            int(classes.gap.sum()),
            int(classes.irregular.sum()),
        )
        return CheckOutcome.from_mask(
            classes.irregular | classes.non_positive, QcFlag.TIMESTAMP_SUSPECT, events
        )

    def _gap_event(self, samples: SampleArrays, position: int) -> QualityEvent:
        duration_h = (samples.t_s[position] - samples.t_s[position - 1]) / S_PER_H
        return QualityEvent(
            kind=EventKind.GAP,
            t_utc=samples.timestamp(position - 1),
            end_utc=samples.timestamp(position),
            detail=(
                f"no sample for {duration_h:.1f} h "
                f"(expected every {self.settings.expected_interval_s:.0f} s)"
            ),
            origin=self.check_id,
        )

    def _summary(
        self, samples: SampleArrays, mask: BoolArray, kind: EventKind
    ) -> list[QualityEvent]:
        positions = np.flatnonzero(mask)
        if positions.size == 0:
            return []
        return [
            QualityEvent(
                kind=kind,
                t_utc=samples.timestamp(int(positions[0])),
                end_utc=samples.timestamp(int(positions[-1])),
                detail=f"{positions.size} interval(s) of type {kind.value}",
                severity=Severity.WARNING,
                origin=self.check_id,
            )
        ]
