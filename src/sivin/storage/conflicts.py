"""What happens when a stored and an incoming value of the same timestamp differ.

Merging is column by column (see :class:`~sivin.storage.merge.SeriesMerger`): a missing value
never competes with a present one. A *conflict* is therefore always two **present**, different
values of the same column and timestamp; only these reach a :class:`ConflictPolicy`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Final, Self

import pandas as pd

from sivin.core.ids import SensorId
from sivin.storage.errors import MeasurementConflictError
from sivin.storage.registry import NamedRegistry


@dataclass(frozen=True, slots=True)
class ValueConflict:
    """Two present, different values of one column at the same timestamp.

    Attributes
    ----------
    sensor_id : SensorId
        The sensor.
    timestamp_utc : pandas.Timestamp
        The shared UTC timestamp.
    column : str
        ``"temp_c"`` (°C) or ``"rh_pct"`` (%).
    stored_value, incoming_value : float
        The value in the store and the value being appended, in the column's unit.
    stored_source, incoming_source : str
        Source file names of the two rows; empty when unknown.
    """

    sensor_id: SensorId
    timestamp_utc: pd.Timestamp
    column: str
    stored_value: float
    incoming_value: float
    stored_source: str
    incoming_source: str

    def describe(self) -> str:
        """Return a one-line description with both values for log messages.

        Returns
        -------
        str
            Sensor, timestamp, column, stored and incoming values and sources.
        """
        return (
            f"sensor {self.sensor_id} at {self.timestamp_utc.isoformat()}, {self.column}: "
            f"stored {self.stored_value} ({self.stored_source or 'unknown source'}) vs "
            f"incoming {self.incoming_value} ({self.incoming_source or 'unknown source'})"
        )


@dataclass(frozen=True, slots=True)
class ConflictDecision:
    """A conflict and how the policy decided it; kept in the append result and the run log.

    Attributes
    ----------
    conflict : ValueConflict
        The two values.
    kept_incoming : bool
        ``True`` if the incoming value replaced the stored one.
    policy : str
        Registry name of the deciding policy.
    """

    conflict: ValueConflict
    kept_incoming: bool
    policy: str

    def to_dict(self) -> dict[str, Any]:
        """Return the decision as JSON-compatible data.

        Returns
        -------
        dict
            Flat mapping; the timestamp as ISO 8601 UTC with ``Z``, ``kept`` is
            ``"incoming"`` or ``"stored"``.
        """
        conflict = self.conflict
        return {
            "sensor_id": str(conflict.sensor_id),
            "timestamp_utc": conflict.timestamp_utc.isoformat().replace("+00:00", "Z"),
            "column": conflict.column,
            "stored_value": conflict.stored_value,
            "incoming_value": conflict.incoming_value,
            "stored_source": conflict.stored_source,
            "incoming_source": conflict.incoming_source,
            "kept": "incoming" if self.kept_incoming else "stored",
            "policy": self.policy,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build a decision from :meth:`to_dict` output.

        Parameters
        ----------
        data : Mapping
            Parsed JSON object.

        Returns
        -------
        ConflictDecision
            The decision.

        Raises
        ------
        KeyError, TypeError, ValueError
            If a field is missing or invalid.
        """
        if data["kept"] not in ("incoming", "stored"):
            raise ValueError(f"'kept' must be 'incoming' or 'stored', got {data['kept']!r}.")
        conflict = ValueConflict(
            sensor_id=SensorId(data["sensor_id"]),
            timestamp_utc=pd.Timestamp(data["timestamp_utc"]).tz_convert("UTC"),
            column=str(data["column"]),
            stored_value=float(data["stored_value"]),
            incoming_value=float(data["incoming_value"]),
            stored_source=str(data["stored_source"]),
            incoming_source=str(data["incoming_source"]),
        )
        return cls(conflict, data["kept"] == "incoming", str(data["policy"]))


class ConflictPolicy(ABC):
    """Extension point: decides which of two conflicting present values the store keeps."""

    name: ClassVar[str]
    """Registry name of the policy, used in the configuration (the only place it is set)."""

    @abstractmethod
    def keeps_incoming(self, conflict: ValueConflict) -> bool:
        """Decide one conflict.

        Parameters
        ----------
        conflict : ValueConflict
            The two values.

        Returns
        -------
        bool
            ``True`` to replace the stored value by the incoming one, ``False`` to keep it.

        Raises
        ------
        MeasurementConflictError
            If the policy refuses to decide.
        """


conflict_policy_registry: Final = NamedRegistry[ConflictPolicy](ConflictPolicy)
"""Registered conflict policies, keyed by :attr:`ConflictPolicy.name`."""

DEFAULT_CONFLICT_POLICY: Final = "prefer_newest"
"""Name of the default policy: the last appended value wins (MIGRATION_PLAN §4, WP-1.4)."""


@conflict_policy_registry.register
class PreferNewest(ConflictPolicy):
    """The value appended last wins. Default policy.

    "Newest" means **import order**, not the age of the export: the pipeline appends exports in
    the order it downloads them, so the latest download wins. A back-fill of an older export
    (e.g. the legacy hand-merged ``data.xlsx``) must use :class:`PreferExisting`, otherwise its
    values would replace those of newer exports.
    """

    name: ClassVar[str] = "prefer_newest"

    def keeps_incoming(self, conflict: ValueConflict) -> bool:
        """Always keep the incoming value.

        Parameters
        ----------
        conflict : ValueConflict
            The two values.

        Returns
        -------
        bool
            ``True``.
        """
        return True


@conflict_policy_registry.register
class PreferExisting(ConflictPolicy):
    """The stored value is kept; use this for back-fills of older exports."""

    name: ClassVar[str] = "prefer_existing"

    def keeps_incoming(self, conflict: ValueConflict) -> bool:
        """Always keep the stored value.

        Parameters
        ----------
        conflict : ValueConflict
            The two values.

        Returns
        -------
        bool
            ``False``.
        """
        return False


@conflict_policy_registry.register
class RaiseOnConflict(ConflictPolicy):
    """Refuse to decide: the append fails and nothing is written."""

    name: ClassVar[str] = "raise"

    def keeps_incoming(self, conflict: ValueConflict) -> bool:
        """Raise on every conflict.

        Parameters
        ----------
        conflict : ValueConflict
            The two values.

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
