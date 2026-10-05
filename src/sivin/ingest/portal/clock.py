"""Time source of the portal client, injectable so tests run without real waiting."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    """A monotonic time source that can pause."""

    def monotonic(self) -> float:
        """Return a monotonic time in seconds (arbitrary origin)."""
        ...

    def sleep(self, duration_s: float) -> None:
        """Pause for ``duration_s`` seconds."""
        ...


class SystemClock:
    """The real clock: :func:`time.monotonic` and :func:`time.sleep`."""

    def monotonic(self) -> float:
        """Return :func:`time.monotonic` in seconds.

        Returns
        -------
        float
            Monotonic time (s).
        """
        return time.monotonic()

    def sleep(self, duration_s: float) -> None:
        """Sleep for ``duration_s`` seconds.

        Parameters
        ----------
        duration_s : float
            Pause (s).
        """
        time.sleep(duration_s)
