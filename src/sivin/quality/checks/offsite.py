"""Samples recorded off site per the off-site log: ``PRE_DEPLOYMENT`` (MIGRATION_PLAN §2.8).

The off-site log is the source of truth for :attr:`~sivin.core.flags.QcFlag.PRE_DEPLOYMENT`
(owner decision of 2026-10-05). The check needs the log as a collaborator, so it is not
registered with :data:`~sivin.quality.checks.base.check_registry` (which builds checks from
settings only): :class:`~sivin.quality.pipeline.QualityPipeline` creates it when it is given a
log.
"""

from __future__ import annotations

import logging
from typing import Final

from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck
from sivin.quality.events import EventKind, EventSource, QualityEvent
from sivin.registry.offsite import OffSiteLog, OffSitePeriod

logger = logging.getLogger(__name__)

ORIGIN: Final = "offsite"
"""``origin`` of the events produced by :class:`OffSiteCheck`."""


class OffSiteSettings(CheckSettings):
    """Settings of :class:`OffSiteCheck` (none yet; the log itself is the configuration)."""


class OffSiteCheck(QualityCheck[OffSiteSettings]):
    """Flag the samples recorded inside a logged off-site period.

    A sample gets ``PRE_DEPLOYMENT`` exactly when ``from <= t < to`` for a period of its
    sensor (``to`` missing = still off site). Every period that overlaps the time span of the
    series is reported as one ``off_site`` event (source ``log``) carrying the whole period,
    also the part outside the series.

    Parameters
    ----------
    log : OffSiteLog
        The validated off-site log.
    settings : OffSiteSettings, optional
        Settings; defaults when omitted.
    """

    check_id = "offsite"
    settings_model = OffSiteSettings

    def __init__(self, log: OffSiteLog, settings: OffSiteSettings | None = None) -> None:
        super().__init__(settings)
        self._log = log

    @property
    def log(self) -> OffSiteLog:
        """The off-site log."""
        return self._log

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Flag off-site samples and report the logged periods.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements of one sensor.

        Returns
        -------
        CheckOutcome
            ``PRE_DEPLOYMENT`` on samples inside a period and one ``off_site`` event per
            period overlapping ``[first sample, last sample]``.
        """
        mask = self._log.mask(series)
        events: tuple[QualityEvent, ...] = ()
        if not series.is_empty:
            times = series.timestamps
            first, last = times.iloc[0], times.iloc[-1]
            events = tuple(
                _event(period)
                for period in self._log.periods_for(series.sensor_id)
                if period.overlaps(first, last)
            )
        logger.debug(
            "Sensor %s: %d off-site sample(s) in %d logged period(s).",
            series.sensor_id,
            int(mask.sum()),
            len(events),
        )
        return CheckOutcome.from_mask(mask, QcFlag.PRE_DEPLOYMENT, events)


def _event(period: OffSitePeriod) -> QualityEvent:
    """The ``off_site`` event of one logged period."""
    return QualityEvent(
        kind=EventKind.OFF_SITE,
        t_utc=period.start_ts,
        end_utc=period.end_ts,
        detail=period.detail,
        source=EventSource.LOG,
        origin=ORIGIN,
    )
