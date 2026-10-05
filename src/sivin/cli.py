"""Command-line entry point ``sivin``.

This is the only module that configures logging and the only one that writes to the console.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
import yaml

from sivin import __version__
from sivin.logging_setup import setup_logging
from sivin.paths import ProjectPaths, ProjectRootNotFoundError

if TYPE_CHECKING:
    from sivin.config import SivinConfig

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="sivin",
    help="Vineyard weather stations: data collection, quality control and climate indices.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Inspect the configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"sivin {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
    log_level: Annotated[
        str, typer.Option("--log-level", help="DEBUG, INFO, WARNING, ERROR or CRITICAL.")
    ] = "INFO",
) -> None:
    """Vineyard weather stations: data collection, quality control and climate indices."""
    try:
        setup_logging(log_level)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--log-level") from error


@config_app.command("show")
def config_show(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Configuration file. Default: config/sivin.yaml in the project root.",
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Print the resolved configuration (file values merged with defaults) as YAML."""
    from sivin.config import ConfigError

    try:
        resolved = _load(config)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        yaml.safe_dump(resolved.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        nl=False,
    )


def _load(config: Path | None) -> SivinConfig:
    from sivin.config import DEFAULT_CONFIG_FILE, SivinConfig, load_config

    if config is not None:
        return load_config(config)
    try:
        default_file = ProjectPaths.discover().resolve(DEFAULT_CONFIG_FILE)
    except ProjectRootNotFoundError:
        logger.info("Not inside the project; using the default configuration.")
        return SivinConfig.default()
    if not default_file.is_file():
        logger.info("%s not found; using the default configuration.", default_file)
        return SivinConfig.default()
    return load_config(default_file)
