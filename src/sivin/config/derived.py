"""Defaults computed from ``time.expected_interval_s`` (owner decision, WP-1.7 round 2).

Each of these fields is a multiple of the nominal sampling interval. Unless the configuration
sets it explicitly, it follows ``time.expected_interval_s``, so changing the interval keeps the
parameters consistent (e.g. a duration cap never falls below the nominal interval). The
factors are the ones the subsystems use for their own defaults.
"""

from __future__ import annotations

from sivin.alignment.strategies import MAX_GAP_FACTOR, LinearParams
from sivin.analytics.disease.sampling import DEFAULT_MAX_SAMPLE_DURATION_FACTOR, SamplingParams
from sivin.analytics.ripening.params import MAX_SAMPLE_DURATION_FACTOR, SampleDurationParams
from sivin.config.shared import DerivedValue
from sivin.quality.checks.precip import COUNTER_MAX_INTERVAL_FACTOR, PrecipCounterSettings
from sivin.quality.checks.spike import MAX_NEIGHBOUR_INTERVAL_FACTOR, SpikeSettings
from sivin.quality.checks.step import MAX_JUMP_INTERVAL_FACTOR, StepSettings

NOMINAL_FACTOR = 1.0
"""``spike.min_interval_s`` is the nominal interval itself."""


def interval_derived_defaults() -> tuple[DerivedValue, ...]:
    """Return every default that is a multiple of ``time.expected_interval_s``.

    Returns
    -------
    tuple of DerivedValue
        Model, field and factor of each.
    """
    return (
        DerivedValue(SamplingParams, "max_sample_duration_s", DEFAULT_MAX_SAMPLE_DURATION_FACTOR),
        DerivedValue(SampleDurationParams, "max_sample_duration_s", MAX_SAMPLE_DURATION_FACTOR),
        DerivedValue(LinearParams, "max_gap_s", MAX_GAP_FACTOR),
        DerivedValue(SpikeSettings, "min_interval_s", NOMINAL_FACTOR),
        DerivedValue(SpikeSettings, "max_interval_s", MAX_NEIGHBOUR_INTERVAL_FACTOR),
        DerivedValue(StepSettings, "max_interval_s", MAX_JUMP_INTERVAL_FACTOR),
        DerivedValue(PrecipCounterSettings, "max_interval_s", COUNTER_MAX_INTERVAL_FACTOR),
    )
