"""Logging configuration; called only by the command-line entry point (:mod:`sivin.cli`)."""

from __future__ import annotations

import logging
from typing import Final

LOG_FORMAT: Final = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
"""Format of every log record."""

LOG_DATE_FORMAT: Final = "%Y-%m-%dT%H:%M:%S%z"
"""ISO 8601 timestamp format of log records (local time with UTC offset)."""


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger to write to standard error.

    Parameters
    ----------
    level : str, optional
        Level name (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``), case-insensitive.

    Raises
    ------
    ValueError
        If the level name is unknown.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper())
    if numeric_level is None:
        raise ValueError(f"Unknown log level {level!r}.")
    logging.basicConfig(level=numeric_level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, force=True)
