"""Missing values (:attr:`~sivin.core.flags.QcFlag.MISSING`)."""

from __future__ import annotations

import logging
from enum import StrEnum

import numpy as np
from pydantic import Field

from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.checks.base import CheckOutcome, CheckSettings, QualityCheck, check_registry
from sivin.quality.samples import SampleArrays, Variable

logger = logging.getLogger(__name__)


class MissingRule(StrEnum):
    """When a row counts as missing."""

    ALL = "all"
    """Every checked variable is missing."""
    ANY = "any"
    """At least one checked variable is missing."""


class MissingValueSettings(CheckSettings):
    """Settings of :class:`MissingValueCheck`."""

    variables: tuple[Variable, ...] = Field(
        (Variable.TEMP, Variable.RH),
        min_length=1,
        description="Variables whose NaN values count as missing (column names, no unit).",
    )
    rule: MissingRule = Field(
        MissingRule.ALL,
        description=(
            "'all': flag a row only when every checked variable is NaN; 'any': flag it when one "
            "is. Project default 'all', because the qc field is shared by both variables "
            "(MIGRATION_PLAN §2.5) and 'any' would exclude a valid temperature whenever only "
            "the humidity is missing. A single NaN value is ignored by the aggregates anyway."
        ),
    )


@check_registry.register
class MissingValueCheck(QualityCheck[MissingValueSettings]):
    """Flag rows without a measured value.

    A value is missing when it is ``NaN``. The row gets ``MISSING`` according to
    :attr:`MissingValueSettings.rule`.
    """

    check_id = "missing"
    settings_model = MissingValueSettings

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Flag missing values.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements.

        Returns
        -------
        CheckOutcome
            ``MISSING`` on rows without values; no events.
        """
        samples = SampleArrays.of(series)
        missing = np.vstack([np.isnan(samples.values(v)) for v in self.settings.variables])
        combine = np.all if self.settings.rule is MissingRule.ALL else np.any
        mask = np.asarray(combine(missing, axis=0), dtype=np.bool_)
        logger.debug("Sensor %s: %d missing row(s).", series.sensor_id, int(mask.sum()))
        return CheckOutcome.from_mask(mask, QcFlag.MISSING)
