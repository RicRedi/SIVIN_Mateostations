"""Resolution of the raw configuration into the complete, consistent configuration.

:class:`ConfigResolver` runs before :class:`~sivin.config.model.SivinConfig` validates its
sections (a pydantic ``model_validator(mode="before")``), so every way of building a
configuration (the YAML file, ``SivinConfig()``, ``model_validate``) gives the same result:

1. the ``time`` section is validated on its own; if it is invalid, nothing else is resolved
   and the section validation reports it;
2. its values are written into every subsystem field of the same name
   (:class:`~sivin.config.shared.SharedValues`);
3. the registry-backed mappings are validated and completed
   (:mod:`sivin.config.registered`).

All problems are raised together as one :class:`pydantic.ValidationError` with the key path
of each offending value. Resolution is idempotent: resolving a resolved configuration
changes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_core import InitErrorDetails

from sivin.config.registered import RegisteredSettings, default_resolutions
from sivin.config.sections import TimeConfig
from sivin.config.shared import SharedValues, plain

TIME_SECTION = "time"
"""Key of the section whose values are shared."""


class ConfigResolver:
    """Write the shared ``time`` values into the subsystems and complete registered settings.

    Parameters
    ----------
    resolutions : sequence of RegisteredSettings, optional
        Registry-backed mappings to resolve; :func:`default_resolutions` when omitted.
    """

    __slots__ = ("_resolutions",)

    def __init__(self, resolutions: Sequence[RegisteredSettings] | None = None) -> None:
        self._resolutions = tuple(resolutions if resolutions is not None else default_resolutions())

    def resolve(self, model: type[BaseModel], data: object) -> object:
        """Return the resolved raw configuration of ``model``.

        Parameters
        ----------
        model : type[pydantic.BaseModel]
            The configuration model (:class:`~sivin.config.model.SivinConfig`).
        data : object
            Raw data: a mapping of sections (sections may be models). Anything else is
            returned unchanged for pydantic to reject.

        Returns
        -------
        object
            A new mapping with the shared values written in and the registered settings
            completed.

        Raises
        ------
        pydantic.ValidationError
            If a subsystem field contradicts the ``time`` section or a registered settings
            mapping is invalid (one error per problem, with its key path).
        """
        if not isinstance(data, Mapping):
            return data
        raw: dict[str, Any] = {str(key): plain(value) for key, value in data.items()}
        try:
            time = TimeConfig.model_validate(raw.get(TIME_SECTION, {}))
        except ValidationError:
            return raw
        shared = SharedValues.from_time(time)
        problems: list[InitErrorDetails] = []
        resolved = shared.apply(model, raw, (), problems, skip=(TIME_SECTION,))
        for resolution in self._resolutions:
            resolution.resolve(resolved, shared, problems)
        if problems:
            raise ValidationError.from_exception_data(model.__name__, problems)
        return resolved
