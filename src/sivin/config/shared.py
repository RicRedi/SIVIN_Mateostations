"""Values set once in ``time`` and copied into every subsystem that has its own field for them.

Several subsystems carry their own copy of a project-wide value, with a default of their own:
the nominal sampling interval (``ingest.parsers.expected_interval_s``, the ``sampling`` check,
the aligner's ``expected_interval_s``, the ``nominal_interval_s`` of the indices' sample
durations), the source time zone of the parsers and the display time zone of the deployment
detector. :class:`SharedValues` writes the value of the ``time`` section into every such field,
found **by field name** in the settings models, so a new subsystem with a field of the same
name is covered without a code change here. A field given explicitly with a different value is
an error that names its key path: there is only one place to set it.
"""

from __future__ import annotations

import types
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Self

from pydantic import BaseModel
from pydantic_core import InitErrorDetails, PydanticCustomError

from sivin.config.sections import TimeConfig

Location = tuple[str | int, ...]
"""Key path of a configuration value, e.g. ``("quality", "check_settings", "sampling")``."""

SHARED_VALUE_ERROR = "shared_value"
"""Pydantic error type of a field that contradicts the ``time`` section."""


@dataclass(frozen=True, slots=True)
class SharedValue:
    """One value of the ``time`` section and the subsystem field names that receive it.

    Attributes
    ----------
    field_names : frozenset of str
        Names of the settings fields that hold this value, e.g. ``expected_interval_s``.
    value : object
        The value (unit as in the ``time`` field).
    origin : str
        Key path of the source, e.g. ``"time.expected_interval_s"``.
    """

    field_names: frozenset[str]
    value: object
    origin: str


@dataclass(frozen=True, slots=True)
class SharedValues:
    """Write the ``time`` values into the raw data of settings models.

    Attributes
    ----------
    values : tuple of SharedValue
        The values and the field names they go to; a field name may appear only once.
    """

    values: tuple[SharedValue, ...]
    _by_name: Mapping[str, SharedValue] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_name: dict[str, SharedValue] = {}
        for shared in self.values:
            for name in shared.field_names:
                if name in by_name:
                    raise ValueError(f"Field name {name!r} is shared twice.")
                by_name[name] = shared
        object.__setattr__(self, "_by_name", types.MappingProxyType(by_name))

    @classmethod
    def from_time(cls, time: TimeConfig) -> Self:
        """Return the shared values of a ``time`` section.

        Parameters
        ----------
        time : TimeConfig
            The validated ``time`` section.

        Returns
        -------
        SharedValues
            ``expected_interval_s`` and ``nominal_interval_s`` (s) from
            ``time.expected_interval_s``, ``source_timezone`` and ``display_timezone``.
        """
        return cls(
            (
                SharedValue(
                    frozenset({"expected_interval_s", "nominal_interval_s"}),
                    time.expected_interval_s,
                    "time.expected_interval_s",
                ),
                SharedValue(
                    frozenset({"source_timezone"}), time.source_timezone, "time.source_timezone"
                ),
                SharedValue(
                    frozenset({"display_timezone"}),
                    time.display_timezone,
                    "time.display_timezone",
                ),
            )
        )

    def apply(
        self,
        model: type[BaseModel],
        raw: Mapping[str, Any],
        location: Location,
        problems: list[InitErrorDetails],
        *,
        skip: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Return ``raw`` with the shared values written into every matching field.

        Nested settings models are followed through their field annotations; a nested section
        that is absent from ``raw`` is filled from the field's default, so the shared value
        also reaches defaults.

        Parameters
        ----------
        model : type[pydantic.BaseModel]
            The settings model ``raw`` is meant for.
        raw : Mapping
            Unvalidated data of ``model`` (keys as in the configuration file).
        location : tuple
            Key path of ``raw`` in the configuration, for error messages.
        problems : list of InitErrorDetails
            Receives one error per explicit value that contradicts a shared value.
        skip : sequence of str, optional
            Field names of ``model`` to leave alone (e.g. ``time`` itself).

        Returns
        -------
        dict
            A new mapping; ``raw`` is not changed.
        """
        out = dict(raw)
        for name, info in model.model_fields.items():
            key = info.alias or name
            if name in skip:
                continue
            shared = self._by_name.get(name)
            if shared is not None:
                if key in out and out[key] != shared.value:
                    problems.append(_conflict((*location, key), out[key], shared))
                out[key] = shared.value
                continue
            nested = settings_model_of(info.annotation)
            if nested is None or not self.reaches(nested):
                continue
            if key in out:
                if isinstance(out[key], Mapping):
                    out[key] = self.apply(nested, out[key], (*location, key), problems)
            else:
                default = info.get_default(call_default_factory=True)
                if isinstance(default, nested):
                    out[key] = self.apply(nested, plain_mapping(default), (*location, key), [])
        return out

    def reaches(self, model: type[BaseModel]) -> bool:
        """Tell whether a settings model has a shared field, directly or in a nested model.

        Parameters
        ----------
        model : type[pydantic.BaseModel]
            A settings model.

        Returns
        -------
        bool
            ``True`` if :meth:`apply` would write into it.
        """
        for name, info in model.model_fields.items():
            if name in self._by_name:
                return True
            nested = settings_model_of(info.annotation)
            if nested is not None and nested is not model and self.reaches(nested):
                return True
        return False


def settings_model_of(annotation: object) -> type[BaseModel] | None:
    """Return the settings model a field holds, for ``Model``, ``Model | None`` and ``Annotated``.

    Parameters
    ----------
    annotation : object
        The field annotation.

    Returns
    -------
    type[pydantic.BaseModel] or None
        The single model class, or ``None`` for anything else (containers, plain types).
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType, typing.Annotated):
        found = {
            model
            for argument in typing.get_args(annotation)
            if (model := settings_model_of(argument)) is not None
        }
        return found.pop() if len(found) == 1 else None
    return None


def plain(value: object) -> object:
    """Return configuration data with models turned into mappings of their explicit keys.

    Parameters
    ----------
    value : object
        A mapping, a pydantic model or a plain value (nested freely).

    Returns
    -------
    object
        Models become ``model_dump(exclude_unset=True, by_alias=True)`` (only what was set
        explicitly, so defaults stay defaults), mappings become dicts; other values unchanged.
    """
    if isinstance(value, BaseModel):
        return plain_mapping(value)
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    return value


def plain_mapping(model: BaseModel) -> dict[str, Any]:
    """Return the explicitly set keys of a model as a mapping (see :func:`plain`).

    Parameters
    ----------
    model : pydantic.BaseModel
        A settings model.

    Returns
    -------
    dict
        ``model.model_dump(exclude_unset=True, by_alias=True)``.
    """
    return model.model_dump(exclude_unset=True, by_alias=True)


def _conflict(location: Location, given: object, shared: SharedValue) -> InitErrorDetails:
    return InitErrorDetails(
        type=PydanticCustomError(
            SHARED_VALUE_ERROR,
            "is set by {origin} ({value}); remove it here or change {origin}",
            {"origin": shared.origin, "value": str(shared.value)},
        ),
        loc=location,
        input=given,
    )
