"""Parameter building blocks shared by the ripening and risk indices.

* :data:`MonthDayValue` lets a parameter model hold a :class:`~sivin.core.season.MonthDay`
  written as ``"MM-DD"`` in the configuration.
* :class:`PeriodParams` is the base of every index parameter model with an index period.
* :class:`SampleDurationParams` configures
  :class:`~sivin.analytics.ripening.durations.SampleDurations`.
"""

from __future__ import annotations

from typing import Annotated, Final, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, model_validator

from sivin.analytics.base import IndexParams
from sivin.core.defaults import LEGACY_SAMPLING_INTERVAL_S
from sivin.core.season import MonthDay, Season

MAX_SAMPLE_DURATION_LIMIT_S: Final = 6 * 3600.0
"""Upper limit of ``max_sample_duration_s`` in seconds (6 h).

Shorter than the shortest local day (23 h), so a sample interval crosses at most one local
midnight; a sample that is followed by a longer gap is not meant to stand for it anyway.
"""

DEFAULT_MAX_SAMPLE_DURATION_S: Final = 2.5 * LEGACY_SAMPLING_INTERVAL_S
"""Default longest step to the next sample that still counts in full, in seconds (4562.5 s).

Project default ``[to be tuned]``: 2.5 times the nominal interval of 1825 s, so one missed
sample (a step of about 3650 s) plus clock drift is still bridged; a longer step is a data gap.
Same rule and default as the WP-2.3 copy (``sivin.analytics.disease.sampling``), so that the
later unification in core preserves behaviour.
"""


def _parse_month_day(value: object) -> object:
    """Turn ``"MM-DD"`` into a :class:`MonthDay`; leave anything else to pydantic."""
    if isinstance(value, str):
        month, separator, day = value.strip().partition("-")
        if not separator or not month.isdigit() or not day.isdigit():
            raise ValueError(f"expected a month-day as 'MM-DD', got {value!r}")
        return MonthDay(int(month), int(day))
    return value


MonthDayValue = Annotated[
    MonthDay,
    BeforeValidator(_parse_month_day),
    PlainSerializer(str, return_type=str),
]
"""A :class:`MonthDay` field that accepts ``"MM-DD"`` strings and serialises to them."""


class PeriodParams(IndexParams):
    """Parameters of an index computed over one period of the year (not crossing New Year).

    Subclasses redeclare both fields with their own default and its source.

    Raises
    ------
    pydantic.ValidationError
        If ``period_end`` is before ``period_start``.
    """

    period_start: MonthDayValue = Field(description="First day of the index period (MM-DD).")
    period_end: MonthDayValue = Field(description="Last day of the index period (MM-DD).")

    @model_validator(mode="after")
    def _period_within_year(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError(
                f"period {self.period_start}..{self.period_end} crosses New Year, "
                "which this index does not support"
            )
        return self

    @property
    def season(self) -> Season:
        """The index period as a :class:`~sivin.core.season.Season`."""
        return Season(self.period_start, self.period_end)


class SampleDurationParams(BaseModel):
    """How long a single raw sample is taken to last (for hour-based metrics).

    Each sample represents the time until the next sample of the series if that step is at
    most ``max_sample_duration_s``. If the step is longer (a data gap), the sample represents
    only ``nominal_interval_s`` and the rest of the gap is not counted. The last sample of the
    series also represents ``nominal_interval_s``.

    Raises
    ------
    pydantic.ValidationError
        If ``max_sample_duration_s < nominal_interval_s``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_sample_duration_s: float = Field(
        DEFAULT_MAX_SAMPLE_DURATION_S,
        gt=0.0,
        le=MAX_SAMPLE_DURATION_LIMIT_S,
        description=(
            "Longest step to the next sample (s) that the sample represents in full; a longer "
            "step is a gap and the sample counts only nominal_interval_s. Project default "
            "4562.5 s = 2.5 x 1825 s [to be tuned]."
        ),
    )
    nominal_interval_s: float = Field(
        LEGACY_SAMPLING_INTERVAL_S,
        gt=0.0,
        description=(
            "Time (s) represented by a sample followed by a gap and by the last sample of a "
            "series. Default: the nominal sampling interval of 1825 s (legacy configs)."
        ),
    )

    @model_validator(mode="after")
    def _cap_not_below_nominal(self) -> Self:
        if self.max_sample_duration_s < self.nominal_interval_s:
            raise ValueError("max_sample_duration_s must not be shorter than nominal_interval_s")
        return self
