"""Project-wide default values shared by the configuration and the analytics.

This module imports nothing heavy, so :mod:`sivin.config` (and with it ``sivin --version``)
stays light.
"""

from __future__ import annotations

from typing import Final

DEFAULT_TIMEZONE: Final = "Europe/Prague"
"""Time zone of the vineyards (South Moravia, Czech Republic)."""

LEGACY_SAMPLING_INTERVAL_S: Final = 1825.0
"""Sampling interval of the sensors in seconds as estimated by the legacy scripts.

Taken from the legacy configurations and ``sampl_freq_basic.py``, whose example timestamps are
30 min 25 s (1825 s) apart. Superseded by :data:`DEFAULT_SAMPLING_INTERVAL_S`, which is measured
on a real export; kept because several subsystems still derive their defaults from it.
"""

DEFAULT_SAMPLING_INTERVAL_S: Final = 1830.0
"""Nominal sampling interval of the sensors in seconds (``time.expected_interval_s``).

Median step between consecutive timestamps of the first real export,
``MeteoData_8615620_77799986_VUT_20260301_223842.csv`` (sensor 77799986, 3520 rows,
2025-07-30 to 2026-03-01; MIGRATION_PLAN §0.6.1). The legacy estimate was 1825 s
(:data:`LEGACY_SAMPLING_INTERVAL_S`).
"""

DEFAULT_MIN_DAILY_COVERAGE: Final = 0.9
"""Share of a day (0-1) that valid samples must cover for the day to count as complete.

Project default, not taken from literature; to be tuned on real data
(``analytics.min_daily_coverage`` in the configuration).
"""

DEFAULT_MIN_SEASON_COVERAGE: Final = 0.9
"""Share (0-1) of the days of an index period that must be complete for a complete result.

Project default, not taken from literature; to be tuned on real data
(``analytics.min_season_coverage`` in the configuration).
"""
