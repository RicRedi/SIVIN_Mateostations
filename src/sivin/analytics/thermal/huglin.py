"""Huglin heliothermal index (``huglin``)."""

from __future__ import annotations

import logging
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.thermal.base import STATUS_KEY, ClassifiedSumParams, ThermalIndex
from sivin.analytics.thermal.classification import ClassBound, IntervalClassification
from sivin.analytics.thermal.formulas import huglin_daily
from sivin.core.season import Season

logger = logging.getLogger(__name__)

HUGLIN_BASE_TEMP_C: Final = 10.0
"""Base temperature of the Huglin index in °C (Huglin, 1978)."""

NO_COEFFICIENT: Final = "latitude coefficient K unavailable (latitude unknown or outside table)"
"""Status detail when K cannot be determined and no override is set."""


class LatitudeBand(BaseModel):
    """Latitude band ``(min_lat_deg, max_lat_deg]`` with its day-length coefficient K.

    Attributes
    ----------
    min_lat_deg, max_lat_deg : float
        Exclusive lower and inclusive upper latitude in degrees north (bands are tabulated
        as e.g. 48°01'-50° N).
    k : float
        Day-length coefficient, dimensionless.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_lat_deg: float = Field(description="Exclusive lower latitude in degrees north.")
    max_lat_deg: float = Field(description="Inclusive upper latitude in degrees north.")
    k: float = Field(gt=0.0, description="Day-length coefficient K, dimensionless.")

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.max_lat_deg <= self.min_lat_deg:
            raise ValueError(
                f"Latitude band upper {self.max_lat_deg} must exceed lower {self.min_lat_deg}."
            )
        return self

    def contains(self, latitude_deg: float) -> bool:
        """Tell whether ``min_lat_deg < latitude_deg <= max_lat_deg``.

        Parameters
        ----------
        latitude_deg : float
            Latitude in degrees north.

        Returns
        -------
        bool
            Whether the latitude is in this band.
        """
        return self.min_lat_deg < latitude_deg <= self.max_lat_deg


TONIETTO_CARBONNEAU_K_BANDS: Final = (
    LatitudeBand(min_lat_deg=40.0, max_lat_deg=42.0, k=1.02),
    LatitudeBand(min_lat_deg=42.0, max_lat_deg=44.0, k=1.03),
    LatitudeBand(min_lat_deg=44.0, max_lat_deg=46.0, k=1.04),
    LatitudeBand(min_lat_deg=46.0, max_lat_deg=48.0, k=1.05),
    LatitudeBand(min_lat_deg=48.0, max_lat_deg=50.0, k=1.06),
)
"""K by 2° latitude band, 40-50° N, after Tonietto and Carbonneau (2004) [to be verified]:
the range K = 1.02-1.06 for 40-50° is the published one; the bands are upper-inclusive as
commonly tabulated (40°01'-42° -> 1.02, ..., 48°01'-50° -> 1.06), exact edges not verified.
Linear interpolation of K, used by some authors, is not implemented."""

HUGLIN_CLASS_BOUNDS: Final = (
    ("very_cool", 1500.0),
    ("cool", 1800.0),
    ("temperate", 2100.0),
    ("temperate_warm", 2400.0),
    ("warm", 3000.0),
)
"""Huglin classes HI-3 ... HI+2 with inclusive upper bounds in °C·d (Tonietto and Carbonneau,
2004); values above 3000 are ``very_warm`` (HI+3)."""

HUGLIN_TOP_CLASS: Final = "very_warm"
"""Label of the class above the last bound (HI+3, > 3000 °C·d)."""


def huglin_classes() -> IntervalClassification:
    """Return the Huglin classes of Tonietto and Carbonneau (2004).

    Returns
    -------
    IntervalClassification
        Six classes; a value equal to a bound belongs to the lower class.
    """
    return IntervalClassification(
        bounds=tuple(ClassBound(label=label, upper=upper) for label, upper in HUGLIN_CLASS_BOUNDS),
        top_label=HUGLIN_TOP_CLASS,
    )


class HuglinParams(ClassifiedSumParams):
    """Parameters of :class:`HuglinIndex`."""

    base_temp_c: float = Field(
        HUGLIN_BASE_TEMP_C, description="Base temperature in °C (Huglin, 1978)."
    )
    period: Season = Field(
        default_factory=Season.huglin,
        description="Accumulation period, April 1 - September 30 (Huglin, 1978).",
    )
    k_bands: tuple[LatitudeBand, ...] = Field(
        TONIETTO_CARBONNEAU_K_BANDS,
        description=(
            "Day-length coefficient K (dimensionless) by latitude band in degrees north, "
            "after Tonietto and Carbonneau (2004) [to be verified]."
        ),
    )
    k_override: float | None = Field(
        None,
        gt=0.0,
        description=(
            "Fixed K (dimensionless) used instead of the latitude lookup; the legacy "
            "vineyard_analyst used 1.05."
        ),
    )
    classes: IntervalClassification = Field(
        default_factory=huglin_classes,
        description="Huglin classes in °C·d, inclusive upper bounds (Tonietto and Carbonneau, "
        "2004).",
    )

    def coefficient(self, latitude_deg: float | None) -> float | None:
        """Return K for a latitude: the override, else the band containing the latitude.

        Parameters
        ----------
        latitude_deg : float or None
            Latitude in degrees north.

        Returns
        -------
        float or None
            K, or ``None`` if there is no override and the latitude is unknown or in no band.
        """
        if self.k_override is not None:
            return self.k_override
        if latitude_deg is None:
            return None
        return next((band.k for band in self.k_bands if band.contains(latitude_deg)), None)


@index_registry.register
class HuglinIndex(ThermalIndex[HuglinParams]):
    r"""Huglin heliothermal index :math:`\sum K \max(0, ((T_{mean}-10) + (T_{max}-10))/2)`.

    Incomplete days contribute nothing, so the sum is biased low when days are missing
    (``details["n_missing_days"]``). The class is assigned only to a complete season with at
    most ``max_missing_days`` missing days.
    """

    index_id = "huglin"
    unit = "°C·d"
    params_model = HuglinParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Compute the Huglin index of ``ctx.year``.

        Parameters
        ----------
        ctx : IndexContext
            Data and metadata of one sensor and one season year; ``latitude_deg`` selects K.

        Returns
        -------
        IndexResult
            Value in °C·d, class (see class docstring), cumulative curve and ``k``.
        """
        selection = self._season_days(ctx, self.params.period)
        k = self.params.coefficient(ctx.latitude_deg)
        if k is None:
            logger.warning(
                "huglin for sensor %s: %s (latitude %s).",
                ctx.sensor_id,
                NO_COEFFICIENT,
                ctx.latitude_deg,
            )
            return self._result(ctx, selection, None, details={STATUS_KEY: NO_COEFFICIENT})
        mean_temp_c = self._mean_temp_c(selection)
        if mean_temp_c.empty:
            return self._empty_result(ctx, selection)
        max_temp_c = selection.days.frame["temp_max"].loc[mean_temp_c.index]
        contribution = huglin_daily(mean_temp_c, max_temp_c, self.params.base_temp_c, k)
        cumulative = contribution.cumsum().rename("cumulative_c_d")
        value_c_d = float(cumulative.iloc[-1])
        label = self.params.sum_class(self.params.classes, value_c_d, selection)
        return self._result(
            ctx, selection, value_c_d, classification=label, daily=cumulative, details={"k": k}
        )
