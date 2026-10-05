"""Configuration mappings whose keys and settings models come from a registry.

Three parts of the configuration name registered classes and carry their settings as plain
mappings, because the classes are only known through their registries: the settings of the
quality checks (``quality.check_settings``), the parameters of the alignment strategy
(``alignment.params``) and the parameters of the climate indices (``analytics.indices``).
Each :class:`RegisteredSettings` subclass validates one of them **when the configuration is
loaded**, with the settings model of the registered class, so an unknown key fails at start-up
with its full key path. It also writes the shared ``time`` values into them and replaces each
mapping by the complete settings (defaults included), which is what ``sivin config show``
prints.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from pydantic import BaseModel, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

import sivin.analytics.disease
import sivin.analytics.ripening
import sivin.analytics.thermal  # noqa: F401  (the three imports register the indices)
from sivin.alignment.config import AlignmentConfig
from sivin.alignment.strategies import strategy_registry
from sivin.analytics.base import index_registry
from sivin.analytics.thermal.phenology import GSR_CULTIVAR_PRESETS
from sivin.config.shared import Location, SharedValues
from sivin.quality.checks.base import check_registry
from sivin.quality.pipeline import QualityPipelineSettings

logger = logging.getLogger(__name__)

CONFIG_VALUE_ERROR: Final = "config_value"
"""Pydantic error type of a problem found in a registered settings mapping."""


def report(location: Location, message: str, given: object) -> InitErrorDetails:
    """Return one configuration problem as a pydantic error at ``location``.

    Parameters
    ----------
    location : tuple
        Key path of the offending value.
    message : str
        What is wrong.
    given : object
        The offending value.

    Returns
    -------
    InitErrorDetails
        Error details for :meth:`pydantic.ValidationError.from_exception_data`.
    """
    return InitErrorDetails(
        type=PydanticCustomError(CONFIG_VALUE_ERROR, "{message}", {"message": message}),
        loc=location,
        input=given,
    )


def validated_dump(
    model: type[BaseModel],
    raw: Mapping[str, Any],
    location: Location,
    problems: list[InitErrorDetails],
) -> dict[str, Any] | None:
    """Validate ``raw`` with ``model`` and return the complete settings as JSON-like data.

    Parameters
    ----------
    model : type[pydantic.BaseModel]
        The settings model.
    raw : Mapping
        Unvalidated settings.
    location : tuple
        Key path of ``raw`` in the configuration.
    problems : list of InitErrorDetails
        Receives the validation errors, with their key paths prefixed by ``location``.

    Returns
    -------
    dict or None
        ``model.model_dump(mode="json")`` of the validated settings, ``None`` if invalid.
    """
    try:
        return model.model_validate(raw).model_dump(mode="json", by_alias=True)
    except ValidationError as error:
        problems.extend(
            report(location + tuple(issue["loc"]), issue["msg"], issue.get("input"))
            for issue in error.errors(include_url=False)
        )
        return None


class RegisteredSettings(ABC):
    """Validates and completes one registry-backed mapping of the raw configuration.

    Attributes
    ----------
    location : tuple of str
        Key path of the mapping, e.g. ``("quality", "check_settings")``.
    keyed : bool
        ``True`` if the mapping holds one settings mapping per registered name (checks,
        indices), ``False`` if it holds the settings of one chosen class (strategy).
    """

    location: ClassVar[tuple[str, ...]]
    keyed: ClassVar[bool] = True

    @abstractmethod
    def models(self) -> tuple[tuple[str, type[BaseModel]], ...]:
        """Return every registered name with its settings model, sorted by name.

        Returns
        -------
        tuple of (str, type[pydantic.BaseModel])
            For the documentation and the JSON schema of the configuration.
        """

    @abstractmethod
    def resolve(
        self,
        config: dict[str, Any],
        shared: SharedValues,
        problems: list[InitErrorDetails],
    ) -> None:
        """Replace the mapping inside ``config`` (in place) by its complete settings.

        Leaves the mapping alone when the keys it depends on (e.g. the check lists) are
        themselves invalid; the model validation of the section reports those.

        Parameters
        ----------
        config : dict
            The whole raw configuration (top-level keys = sections), changed in place.
        shared : SharedValues
            Values of the ``time`` section to write into the settings.
        problems : list of InitErrorDetails
            Receives every problem with its key path.
        """


def _section(config: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Return a top-level section of the raw configuration as a new dict, if it is a mapping."""
    value = config.get(name, {})
    if not isinstance(value, Mapping):
        return None
    section = dict(value)
    config[name] = section
    return section


def _names(value: object) -> tuple[str, ...] | None:
    """Return a list of names from raw data, or ``None`` if it is not a list of strings."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return tuple(value)


class CheckSettingsResolution(RegisteredSettings):
    """``quality.check_settings``: one settings mapping per enabled quality check."""

    location = ("quality", "check_settings")

    def models(self) -> tuple[tuple[str, type[BaseModel]], ...]:
        """Return the registered checks with their settings models."""
        return tuple(
            (name, check_registry.get(name).settings_model) for name in check_registry.ids()
        )

    def resolve(
        self,
        config: dict[str, Any],
        shared: SharedValues,
        problems: list[InitErrorDetails],
    ) -> None:
        """Complete the settings of every enabled check (see :class:`RegisteredSettings`)."""
        section = _section(config, "quality")
        if section is None:
            return
        fields = QualityPipelineSettings.model_fields
        screening = _names(section.get("screening_checks", fields["screening_checks"].default))
        deployed = _names(section.get("deployed_checks", fields["deployed_checks"].default))
        given = section.get("check_settings", {})
        if screening is None or deployed is None or not isinstance(given, Mapping):
            return
        enabled = [name for name in (*screening, *deployed) if name in check_registry]
        resolved: dict[str, Any] = {
            name: value for name, value in given.items() if name not in enabled
        }
        for name in enabled:
            raw = given.get(name, {})
            location: Location = ("quality", "check_settings", name)
            if not isinstance(raw, Mapping):
                problems.append(report(location, "must be a mapping of settings", raw))
                continue
            model = check_registry.get(name).settings_model
            settings = shared.apply(model, raw, location, problems)
            dumped = validated_dump(model, settings, location, problems)
            if dumped is not None:
                resolved[name] = dumped
        section["check_settings"] = resolved


class StrategyParamsResolution(RegisteredSettings):
    """``alignment.params``: the parameters of the chosen alignment strategy."""

    location = ("alignment", "params")
    keyed = False

    def models(self) -> tuple[tuple[str, type[BaseModel]], ...]:
        """Return the registered strategies with their parameter models."""
        return tuple(
            (name, strategy_registry.get(name).params_model) for name in strategy_registry.ids()
        )

    def resolve(
        self,
        config: dict[str, Any],
        shared: SharedValues,
        problems: list[InitErrorDetails],
    ) -> None:
        """Complete the strategy parameters (see :class:`RegisteredSettings`)."""
        section = _section(config, "alignment")
        if section is None:
            return
        strategy = section.get("strategy", AlignmentConfig.model_fields["strategy"].default)
        raw = section.get("params", {})
        if not isinstance(strategy, str) or strategy not in strategy_registry:
            return
        location: Location = ("alignment", "params")
        if not isinstance(raw, Mapping):
            problems.append(report(location, "must be a mapping of parameters", raw))
            return
        model = strategy_registry.get(strategy).params_model
        dumped = validated_dump(
            model, shared.apply(model, raw, location, problems), location, problems
        )
        if dumped is not None:
            section["params"] = dumped


@dataclass(frozen=True, slots=True)
class ParamPreset:
    """A named set of values that may replace one parameter of an index in the configuration.

    Attributes
    ----------
    index_id : str
        The index, e.g. ``"gsr"``.
    key : str
        The configuration key that names the preset, e.g. ``"preset"``.
    target : str
        The parameter the preset fills, e.g. ``"targets"``.
    choices : Mapping
        Preset name → value of the parameter.
    """

    index_id: str
    key: str
    target: str
    choices: Mapping[str, object]

    def expand(
        self, raw: Mapping[str, Any], location: Location, problems: list[InitErrorDetails]
    ) -> dict[str, Any]:
        """Replace the preset key of ``raw`` by the parameter it stands for.

        Parameters
        ----------
        raw : Mapping
            Raw parameters of the index.
        location : tuple
            Key path of ``raw``.
        problems : list of InitErrorDetails
            Receives an unknown preset and a preset given together with the parameter.

        Returns
        -------
        dict
            The parameters without the preset key.
        """
        out = dict(raw)
        if self.key not in out:
            return out
        name = out.pop(self.key)
        if self.target in out:
            problems.append(
                report((*location, self.key), f"give either {self.key} or {self.target}", name)
            )
        elif not isinstance(name, str) or name not in self.choices:
            known = ", ".join(sorted(self.choices)) or "none"
            problems.append(report((*location, self.key), f"unknown preset; known: {known}", name))
        else:
            out[self.target] = _plain_value(self.choices[name])
            logger.debug("Index %s: preset %r sets %s.", self.index_id, name, self.target)
        return out


def _plain_value(value: object) -> object:
    """Return preset values as plain data (models dumped, sequences as lists)."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple | list):
        return [_plain_value(item) for item in value]
    return value


PARAM_PRESETS: Final = (
    ParamPreset(index_id="gsr", key="preset", target="targets", choices=GSR_CULTIVAR_PRESETS),
)
"""Presets accepted in ``analytics.indices`` (``gsr.preset``: the cultivar sugar targets of
:data:`~sivin.analytics.thermal.phenology.GSR_CULTIVAR_PRESETS`, WP-L.1)."""


class IndexParamsResolution(RegisteredSettings):
    """``analytics.indices``: the parameters of every registered climate index.

    Parameters
    ----------
    presets : sequence of ParamPreset, optional
        Presets accepted in the configuration; :data:`PARAM_PRESETS` by default.
    """

    location = ("analytics", "indices")

    def __init__(self, presets: Sequence[ParamPreset] = PARAM_PRESETS) -> None:
        self._presets = {preset.index_id: preset for preset in presets}

    def models(self) -> tuple[tuple[str, type[BaseModel]], ...]:
        """Return the registered indices with their parameter models."""
        return tuple(
            (index_id, index_registry.get(index_id).params_model)
            for index_id in index_registry.ids()
        )

    def resolve(
        self,
        config: dict[str, Any],
        shared: SharedValues,
        problems: list[InitErrorDetails],
    ) -> None:
        """Complete the parameters of every index (see :class:`RegisteredSettings`)."""
        section = _section(config, "analytics")
        if section is None:
            return
        given = section.get("indices", {})
        if not isinstance(given, Mapping):
            return
        for index_id in given:
            if index_id not in index_registry:
                problems.append(
                    report(
                        ("analytics", "indices", index_id),
                        f"unknown index; registered: {', '.join(index_registry.ids())}",
                        given[index_id],
                    )
                )
        resolved: dict[str, Any] = {}
        for index_id in index_registry.ids():
            location: Location = ("analytics", "indices", index_id)
            raw = given.get(index_id, {})
            if not isinstance(raw, Mapping):
                problems.append(report(location, "must be a mapping of parameters", raw))
                continue
            preset = self._presets.get(index_id)
            if preset is not None:
                raw = preset.expand(raw, location, problems)
            model = index_registry.get(index_id).params_model
            dumped = validated_dump(
                model, shared.apply(model, raw, location, problems), location, problems
            )
            if dumped is not None:
                resolved[index_id] = dumped
        section["indices"] = resolved


def default_resolutions() -> tuple[RegisteredSettings, ...]:
    """Return the resolutions of the registry-backed mappings of the configuration.

    Returns
    -------
    tuple of RegisteredSettings
        ``quality.check_settings``, ``alignment.params`` and ``analytics.indices``.
    """
    return (CheckSettingsResolution(), StrategyParamsResolution(), IndexParamsResolution())
