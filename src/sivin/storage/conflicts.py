"""What happens when a stored and an incoming row share a timestamp but differ in value."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Final

import pandas as pd

from sivin.core.ids import SensorId
from sivin.storage.errors import MeasurementConflictError
from sivin.storage.registry import NamedRegistry


@dataclass(frozen=True, slots=True)
class StoredRow:
    """The measured values and origin of one row.

    Attributes
    ----------
    temp_c : float
        Air temperature in °C; ``NaN`` = missing.
    rh_pct : float
        Relative humidity in %; ``NaN`` = missing.
    source : str
        Name of the source file; empty when unknown.
    """

    temp_c: float
    rh_pct: float
    source: str

    def describe(self) -> str:
        """Return a short human-readable form for log messages.

        Returns
        -------
        str
            E.g. ``"temp_c=12.3, rh_pct=81.0 (export_a.csv)"``.
        """
        return f"temp_c={self.temp_c}, rh_pct={self.rh_pct} ({self.source or 'unknown source'})"


@dataclass(frozen=True, slots=True)
class RowConflict:
    """A stored and an incoming row with the same timestamp and different measured values.

    Attributes
    ----------
    sensor_id : SensorId
        The sensor of both rows.
    timestamp_utc : pandas.Timestamp
        The shared UTC timestamp.
    existing : StoredRow
        The row already in the store.
    incoming : StoredRow
        The row being appended (the newer import).
    """

    sensor_id: SensorId
    timestamp_utc: pd.Timestamp
    existing: StoredRow
    incoming: StoredRow

    def describe(self) -> str:
        """Return a one-line description with both values for log messages.

        Returns
        -------
        str
            Sensor, timestamp, stored and incoming values.
        """
        return (
            f"sensor {self.sensor_id} at {self.timestamp_utc.isoformat()}: "
            f"stored {self.existing.describe()} vs incoming {self.incoming.describe()}"
        )


class ConflictPolicy(ABC):
    """Extension point: decides which of two conflicting rows the store keeps."""

    name: ClassVar[str]
    """Registry name of the policy, used in the configuration."""

    @abstractmethod
    def keeps_incoming(self, conflict: RowConflict) -> bool:
        """Decide one conflict.

        Parameters
        ----------
        conflict : RowConflict
            The two rows.

        Returns
        -------
        bool
            ``True`` to replace the stored row by the incoming one, ``False`` to keep it.

        Raises
        ------
        MeasurementConflictError
            If the policy refuses to decide.
        """


conflict_policy_registry: Final = NamedRegistry[ConflictPolicy](ConflictPolicy)
"""Registered conflict policies, keyed by :attr:`ConflictPolicy.name`."""

DEFAULT_CONFLICT_POLICY: Final = "prefer_newest"
"""Name of the default policy: the newer import wins (MIGRATION_PLAN §4, WP-1.4)."""


@conflict_policy_registry.register("prefer_newest")
class PreferNewest(ConflictPolicy):
    """The incoming row (the newer import) replaces the stored one. Default policy."""

    name: ClassVar[str] = "prefer_newest"

    def keeps_incoming(self, conflict: RowConflict) -> bool:
        """Always keep the incoming row.

        Parameters
        ----------
        conflict : RowConflict
            The two rows.

        Returns
        -------
        bool
            ``True``.
        """
        return True


@conflict_policy_registry.register("prefer_existing")
class PreferExisting(ConflictPolicy):
    """The stored row is kept; the incoming value is discarded."""

    name: ClassVar[str] = "prefer_existing"

    def keeps_incoming(self, conflict: RowConflict) -> bool:
        """Always keep the stored row.

        Parameters
        ----------
        conflict : RowConflict
            The two rows.

        Returns
        -------
        bool
            ``False``.
        """
        return False


@conflict_policy_registry.register("raise")
class RaiseOnConflict(ConflictPolicy):
    """Refuse to decide: the append fails and nothing is written."""

    name: ClassVar[str] = "raise"

    def keeps_incoming(self, conflict: RowConflict) -> bool:
        """Raise on every conflict.

        Parameters
        ----------
        conflict : RowConflict
            The two rows.

        Returns
        -------
        bool
            Never returns.

        Raises
        ------
        MeasurementConflictError
            Always, naming both values.
        """
        raise MeasurementConflictError(f"Conflicting measurement for {conflict.describe()}.")
