"""Configuration of the measurement store and the factory that builds it from it.

Proposed as the ``storage`` section of ``config/sivin.yaml``; wiring it into
:class:`~sivin.config.SivinConfig` is left to the integration workpackage. The store directory
itself is ``paths.data_dir``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sivin.storage.conflicts import DEFAULT_CONFLICT_POLICY, conflict_policy_registry
from sivin.storage.merge import DEFAULT_MAX_RECORDED_CONFLICTS
from sivin.storage.partitioning import YearPartitioning, partitioning_registry
from sivin.storage.store import MeasurementStore


class StorageConfig(BaseModel):
    """Measurement-store settings (proposed section ``storage``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conflict_policy: str = Field(
        DEFAULT_CONFLICT_POLICY,
        description=(
            "What to keep when an imported row has the timestamp of a stored row but different "
            "values (name, no unit): 'prefer_newest' (the last appended value wins, default "
            "per MIGRATION_PLAN WP-1.4), 'prefer_existing' (use for back-fills of older "
            "exports) or 'raise'. A missing value never conflicts with a present one."
        ),
    )
    max_recorded_conflicts: int = Field(
        DEFAULT_MAX_RECORDED_CONFLICTS,
        ge=0,
        description=(
            "Conflicts per append kept with both values in the append result and the run log "
            "and logged one by one per partition file (count); further ones are only counted. "
            "Project default."
        ),
    )
    partitioning: str = Field(
        YearPartitioning.name,
        description=(
            "How a sensor's rows are split into files (name, no unit): 'year' = one file per "
            "UTC calendar year (MIGRATION_PLAN §2.5)."
        ),
    )

    @field_validator("conflict_policy")
    @classmethod
    def _known_policy(cls, value: str) -> str:
        if value not in conflict_policy_registry:
            raise ValueError(
                f"unknown conflict policy {value!r}; known: "
                f"{', '.join(conflict_policy_registry.names())}"
            )
        return value

    @field_validator("partitioning")
    @classmethod
    def _known_partitioning(cls, value: str) -> str:
        if value not in partitioning_registry:
            raise ValueError(
                f"unknown partitioning {value!r}; known: {', '.join(partitioning_registry.names())}"
            )
        return value


def build_store(root: Path, config: StorageConfig) -> MeasurementStore:
    """Build a :class:`MeasurementStore` from its configuration.

    Parameters
    ----------
    root : pathlib.Path
        Store directory, e.g. ``ProjectPaths.resolve(config.paths.data_dir)``.
    config : StorageConfig
        Store settings.

    Returns
    -------
    MeasurementStore
        A store with the configured conflict policy, conflict cap and partitioning and the
        CSV codec.
    """
    return MeasurementStore(
        root,
        partitioning=partitioning_registry.create(config.partitioning),
        conflict_policy=conflict_policy_registry.create(config.conflict_policy),
        max_recorded_conflicts=config.max_recorded_conflicts,
    )
