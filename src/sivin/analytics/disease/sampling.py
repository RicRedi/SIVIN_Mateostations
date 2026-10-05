"""Time represented by irregular samples, and runs of samples that meet a condition.

The sensors sample about every 1825 s, but not exactly, and samples can be missing. Hour-based
quantities (consecutive hours in a temperature band, wetness duration) are therefore computed
from the **time each sample represents**, never from the number of rows:

* a sample represents the time until the next sample;
* if the next sample is further away than ``max_duration_s``, the time in between is a data gap:
  the sample represents only the nominal interval and the gap is not counted;
* the last sample of a series represents the nominal interval.

A *run* is a sequence of valid samples that meet a condition without a data gap in between.
Runs may bridge short interruptions (valid samples that do not meet the condition) of a total
duration up to a limit; invalid samples (missing or excluded by QC) and data gaps always end a
run, because nothing is known about them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sivin.core.defaults import LEGACY_SAMPLING_INTERVAL_S

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR: Final = 3600.0
"""Seconds in one hour."""

DEFAULT_MAX_SAMPLE_DURATION_FACTOR: Final = 2.5
"""Default ``max_sample_duration_s`` in multiples of the nominal interval.

Project default, not from literature: one missing sample (a step of about two nominal
intervals, plus clock drift) is still bridged, two or more missing samples are a gap.
"""

_NS_PER_S: Final = 1e9


class SamplingParams(BaseModel):
    """How long a sample counts (shared parameter block of the disease models)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nominal_interval_s: float = Field(
        LEGACY_SAMPLING_INTERVAL_S,
        gt=0.0,
        description=(
            "Nominal sampling interval in seconds (s). Duration of the last sample of a series "
            "and of a sample followed by a data gap. Default 1825 s from the legacy "
            "configuration (sivin.core.defaults.LEGACY_SAMPLING_INTERVAL_S)."
        ),
    )
    max_sample_duration_s: float = Field(
        DEFAULT_MAX_SAMPLE_DURATION_FACTOR * LEGACY_SAMPLING_INTERVAL_S,
        gt=0.0,
        description=(
            "Longest step to the next sample in seconds (s) that still counts as continuous "
            "data; a longer step is a data gap. Default 2.5 x 1825 s = 4562.5 s (project "
            "default: bridges one missing sample), to be tuned on real data."
        ),
    )

    @model_validator(mode="after")
    def _cap_not_below_nominal(self) -> SamplingParams:
        if self.max_sample_duration_s < self.nominal_interval_s:
            raise ValueError("max_sample_duration_s must not be shorter than nominal_interval_s")
        return self

    def durations(self) -> SampleDurations:
        """Build the :class:`SampleDurations` calculator for these parameters.

        Returns
        -------
        SampleDurations
            Calculator with the nominal interval and the gap limit of this block.
        """
        return SampleDurations(
            nominal_interval_s=self.nominal_interval_s,
            max_duration_s=self.max_sample_duration_s,
        )


@dataclass(frozen=True, slots=True)
class SampleTiming:
    """Duration of each sample and whether the next sample follows without a data gap.

    Attributes
    ----------
    durations_s : numpy.ndarray of float
        Time in seconds that each sample represents.
    followed : numpy.ndarray of bool
        ``True`` if the next sample follows within ``max_duration_s``; ``False`` for the last
        sample and before a data gap.
    """

    durations_s: npt.NDArray[np.float64]
    followed: npt.NDArray[np.bool_]

    def __len__(self) -> int:
        return len(self.durations_s)

    def subset(self, positions: npt.NDArray[np.intp]) -> SampleTiming:
        """Return the timing of selected samples (e.g. the samples of one day).

        Parameters
        ----------
        positions : numpy.ndarray of int
            Increasing positions of the selected samples.

        Returns
        -------
        SampleTiming
            Durations and no-gap flags of the selected samples. A run found in the subset
            never extends beyond its last sample.
        """
        return SampleTiming(self.durations_s[positions], self.followed[positions])


@dataclass(frozen=True, slots=True)
class SampleDurations:
    """Compute the time each sample of an irregular series represents.

    Parameters
    ----------
    nominal_interval_s : float
        Nominal sampling interval in seconds.
    max_duration_s : float
        Longest step to the next sample in seconds that is not a data gap.

    Raises
    ------
    ValueError
        If an interval is not positive or ``max_duration_s < nominal_interval_s``.
    """

    nominal_interval_s: float
    max_duration_s: float

    def __post_init__(self) -> None:
        if self.nominal_interval_s <= 0 or self.max_duration_s < self.nominal_interval_s:
            raise ValueError(
                "Need 0 < nominal_interval_s <= max_duration_s, got "
                f"{self.nominal_interval_s} and {self.max_duration_s}."
            )

    def measure(self, timestamps_utc: pd.Series) -> SampleTiming:
        """Measure the duration of every sample.

        Parameters
        ----------
        timestamps_utc : pandas.Series
            Strictly increasing timezone-aware timestamps (``MeasurementSeries.timestamps``).

        Returns
        -------
        SampleTiming
            Durations in seconds and the no-gap mask, aligned with the input.
        """
        times_ns = timestamps_utc.to_numpy(dtype="datetime64[ns]").astype(np.int64)
        if len(times_ns) == 0:
            return SampleTiming(np.empty(0, dtype=np.float64), np.empty(0, dtype=np.bool_))
        steps_s = np.diff(times_ns).astype(np.float64) / _NS_PER_S
        followed = np.append(steps_s <= self.max_duration_s, False)
        durations_s = np.full(len(times_ns), self.nominal_interval_s, dtype=np.float64)
        durations_s[:-1][followed[:-1]] = steps_s[followed[:-1]]
        return SampleTiming(durations_s=durations_s, followed=followed)


@dataclass(frozen=True, slots=True)
class SampleRun:
    """A run of samples meeting a condition (positions refer to the analysed arrays).

    Attributes
    ----------
    first : int
        Position of the first sample of the run.
    last : int
        Position of the last sample meeting the condition (inclusive).
    duration_s : float
        Time in seconds represented by the samples ``first..last``, including bridged
        interruptions.
    interruption_s : float
        Part of ``duration_s`` in seconds spent in bridged interruptions.
    """

    first: int
    last: int
    duration_s: float
    interruption_s: float

    @property
    def duration_h(self) -> float:
        """Duration of the run in hours."""
        return self.duration_s / SECONDS_PER_HOUR


class RunFinder:
    """Find runs of valid samples that meet a condition.

    Parameters
    ----------
    max_interruption_s : float, optional
        Longest total duration in seconds of consecutive valid samples that do not meet the
        condition and are still bridged; ``0`` (default) bridges nothing.

    Raises
    ------
    ValueError
        If ``max_interruption_s`` is negative.
    """

    __slots__ = ("_max_interruption_s",)

    def __init__(self, max_interruption_s: float = 0.0) -> None:
        if max_interruption_s < 0:
            raise ValueError(f"max_interruption_s must not be negative, got {max_interruption_s}.")
        self._max_interruption_s = max_interruption_s

    def find(
        self,
        timing: SampleTiming,
        condition: npt.NDArray[np.bool_],
        valid: npt.NDArray[np.bool_],
    ) -> list[SampleRun]:
        """Return all runs, in time order.

        Parameters
        ----------
        timing : SampleTiming
            Durations and gaps of the samples.
        condition : numpy.ndarray of bool
            Whether each sample meets the condition (only read where ``valid``).
        valid : numpy.ndarray of bool
            Whether each sample is usable (present and not excluded by QC).

        Returns
        -------
        list of SampleRun
            The runs; empty if no valid sample meets the condition.

        Raises
        ------
        ValueError
            If the arrays differ in length.
        """
        if not len(timing) == len(condition) == len(valid):
            raise ValueError("timing, condition and valid must have the same length.")
        builder = _RunBuilder(self._max_interruption_s)
        for position in range(len(timing)):
            if not valid[position]:
                builder.close()
            elif condition[position]:
                builder.extend(position, float(timing.durations_s[position]))
            else:
                builder.interrupt(float(timing.durations_s[position]))
            if not timing.followed[position]:
                builder.close()
        builder.close()
        return builder.runs


class _RunBuilder:
    """Mutable helper of :meth:`RunFinder.find` (local to one call)."""

    __slots__ = ("_current", "_max_interruption_s", "_pending_s", "runs")

    def __init__(self, max_interruption_s: float) -> None:
        self._max_interruption_s = max_interruption_s
        self._current: SampleRun | None = None
        self._pending_s = 0.0
        self.runs: list[SampleRun] = []

    def extend(self, position: int, duration_s: float) -> None:
        current = self._current
        if current is None:
            self._current = SampleRun(position, position, duration_s, 0.0)
        else:
            self._current = SampleRun(
                first=current.first,
                last=position,
                duration_s=current.duration_s + self._pending_s + duration_s,
                interruption_s=current.interruption_s + self._pending_s,
            )
        self._pending_s = 0.0

    def interrupt(self, duration_s: float) -> None:
        if self._current is None:
            return
        self._pending_s += duration_s
        if self._pending_s > self._max_interruption_s:
            self.close()

    def close(self) -> None:
        if self._current is not None:
            self.runs.append(self._current)
        self._current = None
        self._pending_s = 0.0
