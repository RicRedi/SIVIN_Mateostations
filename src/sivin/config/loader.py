"""Reading ``config/sivin.yaml`` into a :class:`~sivin.config.model.SivinConfig`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import ValidationError

from sivin.config.model import SivinConfig

DEFAULT_CONFIG_FILE: Final = Path("config/sivin.yaml")
"""Location of the configuration file, relative to the project root."""


class ConfigError(ValueError):
    """Raised when the configuration file cannot be read or is invalid."""


def load_config(path: Path) -> SivinConfig:
    """Load, validate and resolve a YAML configuration file.

    Missing sections and keys take their defaults; an empty file gives the defaults.

    Parameters
    ----------
    path : pathlib.Path
        The YAML file.

    Returns
    -------
    SivinConfig
        The validated, resolved configuration.

    Raises
    ------
    ConfigError
        If the file cannot be read, is not valid YAML, is not a mapping, or violates the
        schema. The message names the path of every offending key, e.g. ``analytics.min_cov``.
    """
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigError(f"Cannot read configuration {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"Configuration {path} is not valid YAML: {error}") from error
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration {path} must be a mapping, got {type(raw).__name__}.")
    try:
        return SivinConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(f"Invalid configuration {path}:\n{describe(error)}") from error


def describe(error: ValidationError) -> str:
    """Return one line per problem, ``  <key.path>: <message>``.

    Parameters
    ----------
    error : pydantic.ValidationError
        Errors of a configuration model.

    Returns
    -------
    str
        The lines joined by line breaks.
    """
    return "\n".join(
        f"  {'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
        for issue in error.errors(include_url=False)
    )
