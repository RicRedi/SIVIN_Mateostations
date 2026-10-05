"""Step check (:attr:`~sivin.core.flags.QcFlag.STEP`): a sudden persistent level shift.

A jump between two consecutive samples is a step when the level after it stays shifted: the
median of a window after the jump differs from the median of a window before it by at least a
fraction of the jump, in the same direction. A spike (which returns) therefore is not a step,
and neither is a gradual change such as a cold front, whose single-interval jumps are small.
Informative flag (not excluded from indices). Thresholds are project defaults.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping

import numpy as np
from pydantic import Field

from sivin.core.defaults import LEGACY_SAMPLING_INTERVAL_S
from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck, check_registry
from sivin.quality.events import EventKind, QualityEvent
from sivin.quality.samples import S_PER_H, FloatArray, SampleArrays, Variable

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_S = 3 * S_PER_H
"""Length of the windows compared before and after a jump: 3 h (project default)."""


class StepSettings(CheckSettings):
    """Settings of :class:`StepCheck`."""

    temp_min_jump_c: float = Field(
        5.0,
        gt=0,
        description=(
            "Smallest temperature change between two consecutive samples (°C) that is examined "
            "as a step. Project default for 30-min data [to be tuned on real data]."
        ),
    )
    rh_min_jump_pct: float = Field(
        25.0,
        gt=0,
        description=(
            "Smallest relative-humidity change between two consecutive samples (%) that is "
            "examined as a step. Project default [to be tuned on real data]."
        ),
    )
    window_s: float = Field(
        DEFAULT_WINDOW_S,
        gt=0,
        description="Length (s) of the windows before and after a jump. Project default 3 h.",
    )
    min_window_samples: int = Field(
        3,
        ge=1,
        description="Fewest valid samples (count) each window needs. Project default.",
    )
    persistence_fraction: float = Field(
        0.5,
        gt=0,
        le=1,
        description=(
            "Share (0-1, dimensionless) of the jump that the median level after it must keep "
            "relative to the median level before it. Project default."
        ),
    )
    max_interval_s: float = Field(
        3 * LEGACY_SAMPLING_INTERVAL_S,
        gt=0,
        description=(
            "Jumps across a longer interval (s) are not examined (the level may have changed "
            "during the gap). Project default: three nominal intervals."
        ),
    )

    def min_jumps(self) -> Mapping[Variable, float]:
        """Return the jump threshold per variable.

        Returns
        -------
        Mapping
            Variable → threshold in the unit of the variable (°C, %).
        """
        return {Variable.TEMP: self.temp_min_jump_c, Variable.RH: self.rh_min_jump_pct}


@check_registry.register
class StepCheck(QualityCheck[StepSettings]):
    r"""Flag persistent level shifts and report them as ``step`` events.

    For consecutive valid samples :math:`k-1, k` with :math:`|x_k - x_{k-1}| \ge J` and
    :math:`t_k - t_{k-1} \le \Delta t_{max}`, let :math:`m^-` be the median over
    :math:`[t_{k-1} - W, t_{k-1}]` and :math:`m^+` the median over :math:`[t_k, t_k + W]`.
    Sample :math:`k` is a step if :math:`\operatorname{sign}(m^+ - m^-) =
    \operatorname{sign}(x_k - x_{k-1})` and :math:`|m^+ - m^-| \ge f |x_k - x_{k-1}|`.
    """

    check_id = "step"
    settings_model = StepSettings

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Flag steps.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        CheckOutcome
            ``STEP`` on the first sample after each step, and one ``step`` event per step.
        """
        samples = SampleArrays.of(series)
        mask = np.zeros(len(samples), dtype=np.bool_)
        events: list[QualityEvent] = []
        for variable, min_jump in self.settings.min_jumps().items():
            for position, shift in self._steps(samples.t_s, samples.values(variable), min_jump):
                mask[position] = True
                events.append(
                    QualityEvent(
                        kind=EventKind.STEP,
                        t_utc=samples.timestamp(position),
                        detail=f"{variable.value} level step {shift:+.1f} {variable.unit}",
                        origin=self.check_id,
                    )
                )
        logger.debug("Sensor %s: %d step(s).", series.sensor_id, len(events))
        return CheckOutcome.from_mask(mask, QcFlag.STEP, events)

    def _steps(
        self, t_s: FloatArray, values: FloatArray, min_jump: float
    ) -> Iterator[tuple[int, float]]:
        """Yield ``(row position, median shift)`` of every step of one variable."""
        settings = self.settings
        valid = np.flatnonzero(np.isfinite(values))
        x = values[valid]
        t = t_s[valid]
        jumps = np.diff(x)
        candidates = np.flatnonzero(
            (np.abs(jumps) >= min_jump) & (np.diff(t) <= settings.max_interval_s)
        )
        for k in candidates + 1:
            before = x[np.searchsorted(t, t[k - 1] - settings.window_s, side="left") : k]
            after = x[k : np.searchsorted(t, t[k] + settings.window_s, side="right")]
            if min(before.size, after.size) < settings.min_window_samples:
                continue
            jump = x[k] - x[k - 1]
            shift = float(np.median(after) - np.median(before))
            if shift * jump > 0 and abs(shift) >= settings.persistence_fraction * abs(jump):
                yield int(valid[k]), shift
