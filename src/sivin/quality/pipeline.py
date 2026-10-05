"""The quality-control pipeline: checks, the off-site log and deployment detection in order.

Order (MIGRATION_PLAN §2.7, §2.8):

1. **Screening checks** on the whole series (default ``missing``, ``sampling``, ``range``):
   they find what is wrong regardless of where the sensor is, and the detector ignores samples
   they excluded (``MISSING``, ``OUT_OF_RANGE``) so that a gross error cannot fake a
   transition.
2. **Off-site log** (if the pipeline has one): :class:`~sivin.quality.checks.offsite.OffSiteCheck`
   sets ``PRE_DEPLOYMENT`` on every sample inside a logged period and reports each period as an
   ``off_site`` event. The log is the source of truth for ``PRE_DEPLOYMENT``.
3. **Deployment detection** on the whole series. In the default ``advisory`` mode it only warns
   about indoor-like periods the log does not cover; in ``enforce`` mode it also sets
   ``PRE_DEPLOYMENT`` on detected indoor samples.
4. **Deployed checks** (default ``spike``, ``step``, ``persistence``) separately on every
   continuous stretch without ``PRE_DEPLOYMENT`` from steps 2-3. Off-site data are not checked
   against outdoor expectations, and the jump at a deployment is never reported as a spike or
   step.

All flags are OR-ed into the ``qc`` column (existing flags are kept).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import sivin.quality.checks  # noqa: F401  (registers the built-in checks)
from sivin.core.flags import QcFlag
from sivin.core.schema import QC_DTYPE, Column, MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckRegistry, QualityCheck, check_registry
from sivin.quality.checks.offsite import OffSiteCheck
from sivin.quality.deployment import (
    DeploymentDetector,
    DeploymentResult,
    DeploymentSettings,
    true_ranges,
)
from sivin.quality.events import QualityEvent
from sivin.registry.offsite import OffSiteLog

logger = logging.getLogger(__name__)


class QualityPipelineSettings(BaseModel):
    """Settings of :class:`QualityPipeline` (proposed configuration section ``quality``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    screening_checks: tuple[str, ...] = Field(
        ("missing", "sampling", "range"),
        description="Registry names of the checks run on the whole series, in this order.",
    )
    deployed_checks: tuple[str, ...] = Field(
        ("spike", "step", "persistence"),
        description=(
            "Registry names of the checks run on every outdoor stretch after deployment "
            "detection, in this order."
        ),
    )
    check_settings: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Settings per check name (keys and units as in each check's settings model); "
            "omitted checks use their defaults."
        ),
    )
    detect_deployment: bool = Field(
        True,
        description=(
            "Run deployment detection (advisory by default, see deployment.mode); if false, "
            "only the off-site log decides which samples are off site."
        ),
    )
    deployment: DeploymentSettings = Field(
        default_factory=DeploymentSettings, description="Deployment detector settings."
    )

    @field_validator("screening_checks", "deployed_checks")
    @classmethod
    def _known_checks(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        unknown = [name for name in names if name not in check_registry]
        if unknown:
            raise ValueError(
                f"unknown checks {unknown}; registered: {', '.join(check_registry.ids())}"
            )
        if len(set(names)) != len(names):
            raise ValueError(f"checks listed twice: {names}")
        return names

    @model_validator(mode="after")
    def _settings_for_enabled_checks(self) -> QualityPipelineSettings:
        enabled = {*self.screening_checks, *self.deployed_checks}
        stray = sorted(set(self.check_settings) - enabled)
        if stray:
            raise ValueError(f"check_settings given for checks that are not enabled: {stray}")
        return self


@dataclass(frozen=True)
class QualityResult:
    """Outcome of :meth:`QualityPipeline.run`.

    Attributes
    ----------
    series : MeasurementSeries
        The input series with all QC flags OR-ed into ``qc``.
    events : tuple of QualityEvent
        All events of all stages, in time order.
    flag_counts : Mapping[QcFlag, int]
        Number of rows carrying each single flag in the final ``qc`` column (read-only).
    deployment : DeploymentResult or None
        Details of deployment detection; ``None`` if it was disabled.
    """

    series: MeasurementSeries
    events: tuple[QualityEvent, ...]
    flag_counts: Mapping[QcFlag, int] = field(default_factory=dict)
    deployment: DeploymentResult | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "flag_counts", MappingProxyType(dict(self.flag_counts)))


class QualityPipeline:
    """Run screening checks, the off-site log, detection and deployed checks (module docstring).

    Parameters
    ----------
    screening : sequence of QualityCheck
        Checks run on the whole series, in order.
    deployed : sequence of QualityCheck
        Checks run on each stretch without ``PRE_DEPLOYMENT``, in order.
    detector : DeploymentDetector or None
        The deployment detector; ``None`` skips detection.
    off_site_log : OffSiteLog or None, optional
        The off-site log, the source of truth for ``PRE_DEPLOYMENT``; ``None`` = no periods
        (every sample counts as recorded in the vineyard unless the detector enforces).
    """

    __slots__ = ("_deployed", "_detector", "_off_site", "_screening")

    def __init__(
        self,
        screening: Sequence[QualityCheck[Any]],
        deployed: Sequence[QualityCheck[Any]],
        detector: DeploymentDetector | None,
        off_site_log: OffSiteLog | None = None,
    ) -> None:
        self._screening = tuple(screening)
        self._deployed = tuple(deployed)
        self._detector = detector
        self._off_site = None if off_site_log is None else OffSiteCheck(off_site_log)

    @classmethod
    def from_settings(
        cls,
        settings: QualityPipelineSettings,
        registry: CheckRegistry = check_registry,
        off_site_log: OffSiteLog | None = None,
    ) -> QualityPipeline:
        """Build a pipeline from its settings.

        Parameters
        ----------
        settings : QualityPipelineSettings
            Enabled checks, their settings and the detector settings.
        registry : CheckRegistry, optional
            Where the check names are looked up.
        off_site_log : OffSiteLog or None, optional
            The off-site log (loaded with
            :class:`~sivin.registry.offsite.OffSiteLogStore`).

        Returns
        -------
        QualityPipeline
            The pipeline.

        Raises
        ------
        pydantic.ValidationError
            If the settings of a check do not fit its settings model.
        """

        def build(names: Sequence[str]) -> list[QualityCheck[Any]]:
            return [registry.create(name, settings.check_settings.get(name)) for name in names]

        detector = DeploymentDetector(settings.deployment) if settings.detect_deployment else None
        return cls(
            build(settings.screening_checks),
            build(settings.deployed_checks),
            detector,
            off_site_log,
        )

    def run(
        self,
        series: MeasurementSeries,
        known_deployments: Sequence[datetime | pd.Timestamp] = (),
    ) -> QualityResult:
        """Run quality control on one series.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements of one sensor.
        known_deployments : sequence of datetime, optional
            Known deployment times (timezone-aware), e.g. ``placement.from`` of the registry;
            passed to the detector.

        Returns
        -------
        QualityResult
            Flagged series, events, flag counts and deployment details.
        """
        flags = np.zeros(len(series), dtype=QC_DTYPE)
        events: list[QualityEvent] = []
        for check in self._screening:
            _collect(check.check(series), flags, events)
        if self._off_site is not None:
            _collect(self._off_site.check(series), flags, events)
        deployment = None
        if self._detector is not None:
            logged = (
                () if self._off_site is None else self._off_site.log.periods_for(series.sensor_id)
            )
            deployment = self._detector.detect(series.with_flags(flags), known_deployments, logged)
            _collect(deployment.outcome(), flags, events)
        off_site = (flags & np.int32(QcFlag.PRE_DEPLOYMENT)) != 0
        for check in self._deployed:
            for start, stop in true_ranges(~off_site):
                outcome = check.check(_rows(series, start, stop))
                _collect(outcome, flags[start:stop], events)
        flagged = series.with_flags(flags)
        result = QualityResult(
            series=flagged,
            events=tuple(sorted(events, key=lambda event: event.t_utc)),
            flag_counts=_flag_counts(flagged),
            deployment=deployment,
        )
        logger.info(
            "Sensor %s: quality control done, %d event(s), flags %s.",
            series.sensor_id,
            len(result.events),
            {flag.name: count for flag, count in result.flag_counts.items() if count},
        )
        return result


def _collect(
    outcome: CheckOutcome, flags: np.ndarray[Any, np.dtype[np.int32]], events: list[QualityEvent]
) -> None:
    """OR the outcome's flags into ``flags`` (in place) and append its events."""
    np.bitwise_or(flags, outcome.flags, out=flags)
    events.extend(outcome.events)


def _rows(series: MeasurementSeries, start: int, stop: int) -> MeasurementSeries:
    """Return rows ``[start, stop)`` of a series."""
    times = series.timestamps
    return series.between(times.iloc[start], times.iloc[stop - 1])


def _flag_counts(series: MeasurementSeries) -> dict[QcFlag, int]:
    qc = series.frame[Column.QC].to_numpy()
    single_flags = [flag for flag in QcFlag if flag and not flag & (flag - 1)]
    return {flag: int(np.count_nonzero(qc & int(flag))) for flag in single_flags}
