"""Configuration of the time alignment (proposed section ``alignment`` of ``config/sivin.yaml``).

Wiring this model into :class:`~sivin.config.SivinConfig` is left to the integration
workpackage (WP-1.7); until then it is used directly, e.g. by
:meth:`~sivin.alignment.aligner.SensorAligner.from_config`.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from sivin.alignment.grid import (
    DEFAULT_GRID_STEP_S,
    OverlapSpan,
    UnionSpan,
    span_registry,
    validate_step_s,
)
from sivin.alignment.strategies import NearestWithinTolerance, strategy_registry


def _empty_params() -> Mapping[str, Any]:
    return MappingProxyType({})


class AlignmentConfig(BaseModel):
    """How sensors are put on a common time grid.

    The parameters in ``params`` are validated against the parameter model of the chosen
    strategy, so a typo or a parameter of another strategy fails at start-up.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str = Field(
        NearestWithinTolerance.strategy_id,
        description=(
            "Registered alignment strategy (identifier, no unit): 'nearest_within_tolerance' "
            "or 'linear_interpolation'."
        ),
    )
    params: Mapping[str, Any] = Field(
        default_factory=_empty_params,
        description=(
            "Parameters of the strategy (read-only mapping), validated by the strategy's own "
            "model; units in the key names. nearest_within_tolerance: 'tolerance_s' (explicit "
            "override), 'expected_interval_s' (default 1825 s), 'margin_s' (default 20 s); "
            "linear_interpolation: 'max_gap_s' (default 2737.5 s). Empty = defaults."
        ),
    )
    grid_step_s: float = Field(
        DEFAULT_GRID_STEP_S,
        ge=1,
        allow_inf_nan=False,
        description=(
            "Grid step in seconds (at least 1 s, whole nanoseconds); default 1800 s "
            "(30 min, MIGRATION_PLAN §2.7)."
        ),
    )
    span: str = Field(
        UnionSpan.rule_id,
        description=(
            f"Span the grid covers (identifier, no unit): '{UnionSpan.rule_id}' (any sensor has "
            f"data) or '{OverlapSpan.rule_id}' (every sensor with data has data)."
        ),
    )

    @field_validator("params")
    @classmethod
    def _read_only_params(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return MappingProxyType(dict(value))

    @field_serializer("params")
    def _plain_params(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return dict(value)

    @field_validator("grid_step_s")
    @classmethod
    def _valid_step(cls, value: float) -> float:
        return validate_step_s(value)

    @field_validator("strategy")
    @classmethod
    def _known_strategy(cls, value: str) -> str:
        if value not in strategy_registry:
            raise ValueError(f"unknown strategy {value!r}; known: {list(strategy_registry.ids())}")
        return value

    @field_validator("span")
    @classmethod
    def _known_span(cls, value: str) -> str:
        if value not in span_registry:
            raise ValueError(f"unknown span rule {value!r}; known: {list(span_registry.ids())}")
        return value

    @model_validator(mode="after")
    def _valid_params(self) -> Self:
        try:
            strategy_registry.get(self.strategy).params_model.model_validate(self.params)
        except ValidationError as error:
            problems = "; ".join(
                f"params.{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
                for issue in error.errors()
            )
            raise ValueError(
                f"invalid parameters of strategy {self.strategy!r}: {problems}"
            ) from None
        return self
