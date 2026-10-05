"""Exceptions raised by the measurement store."""

from __future__ import annotations


class StoreError(Exception):
    """Base class of all measurement-store errors."""


class StoreFormatError(StoreError, ValueError):
    """Raised when a stored file does not follow the documented file format.

    The message names the file and, where possible, the line number. A file that fails this
    check is never overwritten by the store; it must be repaired by hand (see
    ``docs/storage.md``).
    """


class MeasurementConflictError(StoreError):
    """Raised by :class:`~sivin.storage.conflicts.RaiseOnConflict` on the first conflict.

    A conflict is a stored row and an incoming row with the same ``timestamp_utc`` but different
    measured values. Nothing is written when this is raised.
    """
