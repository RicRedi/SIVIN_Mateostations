"""Merging of an incoming series into the stored rows of one partition, column by column."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from typing import Final, Self

import numpy as np
import numpy.typing as npt
import pandas as pd

from sivin.core.schema import Column, MeasurementSeries
from sivin.storage.conflicts import ConflictDecision, ConflictPolicy, ValueConflict

logger = logging.getLogger(__name__)

DEFAULT_MAX_RECORDED_CONFLICTS: Final = 100
"""Conflicts kept (and logged one by one) per append; further ones are only counted.

A changed rounding of the provider's export could make every value of a year conflict; the cap
keeps the log, the append result and the run log small in that case. Project default.
"""

VALUE_COLUMNS: Final = (Column.TEMP, Column.RH)
"""Measured columns, merged independently of each other."""


@dataclass(frozen=True, slots=True)
class AppendCounts:
    """Counts of one append (or one merged partition).

    Row counts refer to incoming rows, value counts to single ``temp_c`` / ``rh_pct`` values of
    incoming rows whose timestamp is already stored.

    Attributes
    ----------
    new_rows : int
        Incoming rows with a timestamp not stored before; written.
    identical_skipped : int
        Incoming rows whose values all equal the stored row (``NaN`` equals ``NaN``; ``source``
        is not compared); nothing written.
    filled_values : int
        Stored missing values filled in from the import; written.
    ignored_missing_values : int
        Values missing in the import but present in the store; the stored value is kept.
    conflicting_values : int
        Values present in both with different numbers; decided by the policy.
    replaced_values : int
        Conflicting values where the policy kept the incoming value (subset of
        ``conflicting_values``); written.
    """

    new_rows: int = 0
    identical_skipped: int = 0
    filled_values: int = 0
    ignored_missing_values: int = 0
    conflicting_values: int = 0
    replaced_values: int = 0

    def __add__(self, other: AppendCounts) -> AppendCounts:
        return AppendCounts(
            **{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)}
        )

    @property
    def changes_data(self) -> bool:
        """``True`` if the merge adds a row or changes a stored value."""
        return self.new_rows > 0 or self.filled_values > 0 or self.replaced_values > 0

    def to_dict(self) -> dict[str, int]:
        """Return the counts as a plain mapping (for JSON).

        Returns
        -------
        dict of str to int
            Field name to count.
        """
        return {f.name: int(getattr(self, f.name)) for f in fields(self)}

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
        What happened to the incoming rows and values.
    conflicts : tuple of ConflictDecision
        The first ``max_recorded_conflicts`` decided conflicts, by time and column.
    """

    series: MeasurementSeries
    counts: AppendCounts
    conflicts: tuple[ConflictDecision, ...] = field(default=())


class SeriesMerger:
    """Merges incoming rows into stored rows on ``timestamp_utc``, column by column.

    * timestamp not stored yet → the row is added;
    * for each of ``temp_c`` and ``rh_pct`` of a stored timestamp:

      - equal values, or both missing → nothing changes;
      - stored missing, incoming present → the value is filled in;
      - stored present, incoming missing → the stored value is kept (a missing value never
        overwrites a measurement);
      - both present and different → a :class:`ValueConflict` decided by the policy and
        logged with both values.

    A row's ``source`` becomes the incoming source when at least one of its values is taken
    from the import; otherwise the stored source is kept, so re-importing an export under a
    new name changes nothing. QC flags of the incoming series are dropped.

    Parameters
    ----------
    policy : ConflictPolicy
        Decides conflicts.
    max_recorded_conflicts : int, optional
        Conflicts kept in the outcome and logged one by one; further ones are counted only.
    """

    __slots__ = ("_max_recorded", "_policy")

    def __init__(
        self, policy: ConflictPolicy, max_recorded_conflicts: int = DEFAULT_MAX_RECORDED_CONFLICTS
    ) -> None:
        if max_recorded_conflicts < 0:
            raise ValueError(
                f"max_recorded_conflicts must not be negative, got {max_recorded_conflicts}."
            )
        self._policy = policy
        self._max_recorded = max_recorded_conflicts

    @property
    def policy(self) -> ConflictPolicy:
        """The conflict policy."""
        return self._policy

    @property
    def max_recorded_conflicts(self) -> int:
        """Number of conflicts kept and logged one by one per merge."""
        return self._max_recorded

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
            The merged series, the counts and the recorded conflicts.

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
        shared = _SharedRows(stored, old.loc[new.index[is_shared]], new.loc[is_shared])
        merged = old.copy()
        took_incoming = np.zeros(len(shared.timestamps), dtype=bool)
        differs = np.zeros(len(shared.timestamps), dtype=bool)
        counts = AppendCounts()
        decisions: list[ConflictDecision] = []
        for column in VALUE_COLUMNS:
            values = _ColumnMerge(shared.old[column].to_numpy(), shared.new[column].to_numpy())
            keep_incoming, column_decisions = self._decide(shared, str(column), values)
            merged.loc[shared.timestamps, column] = np.where(
                keep_incoming, values.incoming, values.stored
            )
            took_incoming |= keep_incoming
            differs |= values.fill | values.ignored | values.conflict
            decisions += column_decisions
            counts += values.counts(keep_incoming)
        replaced_sources = shared.timestamps[took_incoming]
        merged.loc[replaced_sources, Column.SOURCE] = shared.new.loc[
            replaced_sources, Column.SOURCE
        ]
        added = new.loc[~is_shared]
        if not added.empty:
            merged = pd.concat([merged, added]).sort_index()
        counts += AppendCounts(new_rows=len(added), identical_skipped=int((~differs).sum()))
        decisions.sort(key=lambda d: (d.conflict.timestamp_utc, d.conflict.column))
        self._log(decisions)
        recorded = tuple(decisions[: self._max_recorded])
        return MergeOutcome(_series(stored, merged), counts, recorded)

    def _decide(
        self, shared: _SharedRows, column: str, values: _ColumnMerge
    ) -> tuple[npt.NDArray[np.bool_], list[ConflictDecision]]:
        """Return which shared values to take from the import, and the decided conflicts."""
        keep_incoming = values.fill.copy()
        decisions = []
        for position in (int(index) for index in np.flatnonzero(values.conflict)):
            conflict = ValueConflict(
                sensor_id=shared.sensor_id,
                timestamp_utc=shared.timestamps[position],
                column=column,
                stored_value=float(values.stored[position]),
                incoming_value=float(values.incoming[position]),
                stored_source=str(shared.old[Column.SOURCE].iloc[position]),
                incoming_source=str(shared.new[Column.SOURCE].iloc[position]),
            )
            keep_incoming[position] = self._policy.keeps_incoming(conflict)
            decisions.append(
                ConflictDecision(conflict, bool(keep_incoming[position]), self._policy.name)
            )
        return keep_incoming, decisions

    def _log(self, decisions: list[ConflictDecision]) -> None:
        for decision in decisions[: self._max_recorded]:
            logger.warning(
                "Conflict, %s; kept the %s value (policy %s).",
                decision.conflict.describe(),
                "incoming" if decision.kept_incoming else "stored",
                decision.policy,
            )
        if len(decisions) > self._max_recorded:
            logger.warning(
                "%d further conflict(s) not logged individually (policy %s).",
                len(decisions) - self._max_recorded,
                self._policy.name,
            )


class _SharedRows:
    """Stored and incoming rows of the timestamps present in both, aligned by position."""

    __slots__ = ("new", "old", "sensor_id", "timestamps")

    def __init__(self, stored: MeasurementSeries, old: pd.DataFrame, new: pd.DataFrame) -> None:
        self.sensor_id = stored.sensor_id
        self.timestamps = pd.DatetimeIndex(new.index)
        self.old = old
        self.new = new


@dataclass(frozen=True, slots=True)
class _ColumnMerge:
    """Classification of the shared values of one column (boolean masks per shared row)."""

    stored: npt.NDArray[np.float64]
    incoming: npt.NDArray[np.float64]

    @property
    def fill(self) -> npt.NDArray[np.bool_]:
        return np.isnan(self.stored) & ~np.isnan(self.incoming)

    @property
    def ignored(self) -> npt.NDArray[np.bool_]:
        return ~np.isnan(self.stored) & np.isnan(self.incoming)

    @property
    def conflict(self) -> npt.NDArray[np.bool_]:
        both = ~np.isnan(self.stored) & ~np.isnan(self.incoming)
        different: npt.NDArray[np.bool_] = both & (self.stored != self.incoming)
        return different

    def counts(self, keep_incoming: npt.NDArray[np.bool_]) -> AppendCounts:
        return AppendCounts(
            filled_values=int(self.fill.sum()),
            ignored_missing_values=int(self.ignored.sum()),
            conflicting_values=int(self.conflict.sum()),
            replaced_values=int((keep_incoming & self.conflict).sum()),
        )


def _indexed(series: MeasurementSeries) -> pd.DataFrame:
    """Return value and source columns indexed by timestamp; a missing source becomes ``""``."""
    frame = series.frame
    if Column.SOURCE not in frame.columns:
        frame[Column.SOURCE] = pd.Series("", index=frame.index, dtype="str")
    columns = [str(Column.TEMP), str(Column.RH), str(Column.SOURCE)]
    return frame.set_index(str(Column.TIMESTAMP))[columns]


def _series(template: MeasurementSeries, frame: pd.DataFrame) -> MeasurementSeries:
    return MeasurementSeries.from_records(
        template.sensor_id,
        pd.DatetimeIndex(frame.index),
        frame[Column.TEMP].to_numpy(),
        frame[Column.RH].to_numpy(),
        source=frame[Column.SOURCE].astype("str").tolist(),
    )
