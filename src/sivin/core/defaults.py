"""Project-wide default values shared by the configuration and the analytics.

This module imports nothing heavy, so :mod:`sivin.config` (and with it ``sivin --version``)
stays light.
"""

from __future__ import annotations

from typing import Final

DEFAULT_TIMEZONE: Final = "Europe/Prague"
"""Time zone of the vineyards (South Moravia, Czech Republic)."""

LEGACY_SAMPLING_INTERVAL_S: Final = 1825.0
"""Nominal sampling interval of the sensors in seconds.

Taken from the legacy configurations and ``sampl_freq_basic.py``, whose example timestamps are
30 min 25 s (1825 s) apart.
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
