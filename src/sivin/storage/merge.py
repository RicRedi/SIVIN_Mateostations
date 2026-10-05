"""Merging of an incoming series into the stored rows of one partition."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Self

import numpy as np
import pandas as pd

from sivin.core.schema import Column, MeasurementSeries
from sivin.storage.conflicts import ConflictPolicy, RowConflict, StoredRow

logger = logging.getLogger(__name__)

MAX_LOGGED_CONFLICTS: Final = 20
"""Conflicts logged one by one per merge; further ones are only counted in a summary line.

A changed rounding of the provider's export could make every row of a year conflict; this cap
keeps the log readable in that case.
"""

_VALUE_COLUMNS: Final = (Column.TEMP, Column.RH)


@dataclass(frozen=True, slots=True)
class AppendCounts:
    """Row counts of one append (or one merged partition).

    Attributes
    ----------
    new_rows : int
        Incoming rows with a timestamp not stored before; written.
    identical_skipped : int
        Incoming rows equal to the stored row of the same timestamp (``temp_c`` and ``rh_pct``
        equal, ``NaN`` equal to ``NaN``; ``source`` is not compared); not written.
    conflicting_rows : int
        Incoming rows with a stored timestamp but different values; decided by the policy.
    replaced_rows : int
        Conflicting rows where the policy kept the incoming row (a subset of
        ``conflicting_rows``).
    """

    new_rows: int = 0
    identical_skipped: int = 0
    conflicting_rows: int = 0
    replaced_rows: int = 0

    def __add__(self, other: AppendCounts) -> AppendCounts:
        return AppendCounts(
            new_rows=self.new_rows + other.new_rows,
            identical_skipped=self.identical_skipped + other.identical_skipped,
            conflicting_rows=self.conflicting_rows + other.conflicting_rows,
            replaced_rows=self.replaced_rows + other.replaced_rows,
        )

    @property
    def changes_data(self) -> bool:
        """``True`` if the merge adds or replaces at least one row."""
        return self.new_rows > 0 or self.replaced_rows > 0

    def to_dict(self) -> dict[str, int]:
        """Return the counts as a plain mapping (for JSON).

        Returns
        -------
        dict of str to int
            Field name to count.
        """
        return {
            "new_rows": self.new_rows,
            "identical_skipped": self.identical_skipped,
            "conflicting_rows": self.conflicting_rows,
            "replaced_rows": self.replaced_rows,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> Self:
        """Build counts from :meth:`to_dict` output.

        Parameters
        ----------
        data : dict of str to int
            Field name to count.

        Returns
        -------
        AppendCounts
            The counts.
        """
        return cls(**data)


@dataclass(frozen=True, slots=True)
class MergeOutcome:
    """Result of :meth:`SeriesMerger.merge`.

    Attributes
    ----------
    series : MeasurementSeries
        The merged rows, ascending, ``qc = 0``, always with a ``source`` column.
    counts : AppendCounts
        What happened to the incoming rows.
    """

    series: MeasurementSeries
    counts: AppendCounts


class SeriesMerger:
    """Merges incoming rows into stored rows, deduplicating on ``timestamp_utc``.

    * timestamp not stored yet → the row is added,
    * same timestamp, same ``temp_c`` and ``rh_pct`` → the stored row is kept unchanged
      (including its ``source``), so re-importing an export changes nothing,
    * same timestamp, different values → a :class:`RowConflict` decided by the policy and logged
      with both values.

    QC flags of the incoming series are dropped: raw files hold no flags.

    Parameters
    ----------
    policy : ConflictPolicy
        Decides conflicts.
    """

    __slots__ = ("_policy",)

    def __init__(self, policy: ConflictPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> ConflictPolicy:
        """The conflict policy."""
        return self._policy

    def merge(self, stored: MeasurementSeries, incoming: MeasurementSeries) -> MergeOutcome:
        """Merge ``incoming`` into ``stored``.

        Parameters
        ----------
        stored : MeasurementSeries
            Rows already in the store.
        incoming : MeasurementSeries
            Rows to append.

        Returns
        -------
        MergeOutcome
            The merged series and the counts.

        Raises
        ------
        ValueError
            If the two series belong to different sensors.
        MeasurementConflictError
            If the policy refuses a conflict.
        """
        if stored.sensor_id != incoming.sensor_id:
            raise ValueError(
                f"Cannot merge sensor {incoming.sensor_id} into sensor {stored.sensor_id}."
            )
        old = _indexed(stored)
        new = _indexed(incoming)
        is_shared = new.index.isin(old.index)
        shared = new.index[is_shared]
        same = _same_values(old.loc[shared], new.loc[shared])
        conflicts = [
            self._conflict(stored, timestamp, old.loc[timestamp], new.loc[timestamp])
            for timestamp in shared[~same]
        ]
        replaced = self._decide(conflicts)
        merged = old.copy()
        merged.loc[replaced] = new.loc[replaced]
        added = new.loc[~is_shared]
        if not added.empty:
            merged = pd.concat([merged, added]).sort_index()
        counts = AppendCounts(
            new_rows=len(added),
            identical_skipped=int(same.sum()),
            conflicting_rows=len(conflicts),
            replaced_rows=len(replaced),
        )
        return MergeOutcome(_series(stored, merged), counts)

    def _decide(self, conflicts: list[RowConflict]) -> pd.DatetimeIndex:
        kept_incoming = []
        for number, conflict in enumerate(conflicts, start=1):
            keeps_incoming = self._policy.keeps_incoming(conflict)
            if keeps_incoming:
                kept_incoming.append(conflict.timestamp_utc)
            if number <= MAX_LOGGED_CONFLICTS:
                logger.warning(
                    "Conflict, %s; kept the %s row (policy %s).",
                    conflict.describe(),
                    "incoming" if keeps_incoming else "stored",
                    self._policy.name,
                )
        if len(conflicts) > MAX_LOGGED_CONFLICTS:
            logger.warning(
                "%d further conflict(s) not logged individually (policy %s).",
                len(conflicts) - MAX_LOGGED_CONFLICTS,
                self._policy.name,
            )
        return pd.DatetimeIndex(kept_incoming, dtype="datetime64[ns, UTC]")

    @staticmethod
    def _conflict(
        stored: MeasurementSeries, timestamp: pd.Timestamp, old: pd.Series, new: pd.Series
    ) -> RowConflict:
        return RowConflict(
            sensor_id=stored.sensor_id,
            timestamp_utc=timestamp,
            existing=_row(old),
            incoming=_row(new),
        )


def _indexed(series: MeasurementSeries) -> pd.DataFrame:
    """Return value and source columns indexed by timestamp; a missing source becomes ``""``."""
    frame = series.frame
    if Column.SOURCE not in frame.columns:
        frame[Column.SOURCE] = pd.Series("", index=frame.index, dtype="str")
    columns = [str(Column.TEMP), str(Column.RH), str(Column.SOURCE)]
    return frame.set_index(str(Column.TIMESTAMP))[columns]


def _same_values(old: pd.DataFrame, new: pd.DataFrame) -> np.ndarray:
    """Row-wise equality of the measured values; ``NaN`` equals ``NaN``."""
    same = np.ones(len(old), dtype=bool)
    for column in _VALUE_COLUMNS:
        a = old[column].to_numpy()
        b = new[column].to_numpy()
        same &= (a == b) | (np.isnan(a) & np.isnan(b))
    return same


def _row(values: pd.Series) -> StoredRow:
    return StoredRow(
        temp_c=float(values[Column.TEMP]),
        rh_pct=float(values[Column.RH]),
        source=str(values[Column.SOURCE]),
    )


def _series(template: MeasurementSeries, frame: pd.DataFrame) -> MeasurementSeries:
    return MeasurementSeries.from_records(
        template.sensor_id,
        pd.DatetimeIndex(frame.index),
        frame[Column.TEMP].to_numpy(),
        frame[Column.RH].to_numpy(),
        source=frame[Column.SOURCE].astype("str").tolist(),
    )
