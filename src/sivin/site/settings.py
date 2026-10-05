"""Settings of the static site export (configuration section ``site``)."""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sivin.quality.events import EventKind

SECONDS_PER_HOUR: Final = 3600
"""Seconds in one hour (unit conversion)."""

DEFAULT_STALE_AFTER_H: Final = 36
"""Hours after which the last valid sample of a sensor counts as stale.

Project default: the pipeline runs once a day at 06:00 local time (owner decision Q5,
2026-10-05), so a healthy sensor's last sample is at most about 24 h old when the site is
generated; 36 h tolerates one late or failed daily run before the map greys the sensor out.
"""

DEFAULT_STALE_AFTER_S: Final = float(DEFAULT_STALE_AFTER_H * SECONDS_PER_HOUR)
""":data:`DEFAULT_STALE_AFTER_H` in seconds (129 600 s)."""

DEFAULT_PUBLISHED_EVENTS: Final = (
    EventKind.OFF_SITE,
    EventKind.DEPLOYMENT,
    EventKind.RETRIEVAL,
    EventKind.STEP,
    EventKind.LOW_BATTERY,
    EventKind.UNLOGGED_OFF_SITE,
)
"""QC event kinds written to ``events/<sensor_id>.json`` by default (``docs/site.md``)."""


class SiteSettings(BaseModel):
    """Settings of :class:`~sivin.site.builder.SiteBuilder` (configuration section ``site``).

    The output directory is ``<paths.site_dir>/data`` (MIGRATION_PLAN §2.6); the time zone,
    the nominal interval and the exclusion masks come from ``time`` and ``analytics``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stale_after_s: float = Field(
        DEFAULT_STALE_AFTER_S,
        gt=0,
        description=(
            "Age in seconds of a sensor's last valid sample, relative to generated_at, above "
            "which latest.json marks it stale (default 36 h = 129600 s: one daily run at 06:00 "
            "plus a missed or late run; project default)."
        ),
    )
    events: tuple[EventKind, ...] = Field(
        DEFAULT_PUBLISHED_EVENTS,
        description=(
            "QC event kinds (no unit) published in events/<sensor_id>.json. 'off_site' is the "
            "off-site log period, 'deployment'/'retrieval'/'step' are point markers, "
            "'low_battery' and 'unlogged_off_site' are advisory intervals (docs/site.md). The "
            "other kinds (gap, irregular_sampling, precip_*, ...) stay in the derived events."
        ),
    )

    @field_validator("events")
    @classmethod
    def _unique(cls, kinds: tuple[EventKind, ...]) -> tuple[EventKind, ...]:
        if len(set(kinds)) != len(kinds):
            raise ValueError(f"event kinds listed twice: {[str(kind) for kind in kinds]}")
        return kinds
