"""Settings of the off-site log (proposed configuration section ``offsite_log``)."""

from __future__ import annotations

from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from sivin.core.defaults import DEFAULT_TIMEZONE
from sivin.registry.offsite.local_time import LocalTimeReader


class OffSiteLogSettings(BaseModel):
    """Settings of the off-site log (proposed configuration section ``offsite_log``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: Path = Field(
        Path("sensors/offsite_log.yaml"),
        description="The off-site log (path, relative to the project root).",
    )
    timezone: str = Field(
        DEFAULT_TIMEZONE,
        description=(
            "IANA zone of local times in the log (no unit); the vineyards' zone "
            "(MIGRATION_PLAN §2.8)."
        ),
    )

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        LocalTimeReader(value)
        return value
