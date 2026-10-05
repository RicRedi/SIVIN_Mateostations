"""The ``sivin`` application: global options and the registration of every command.

This package is the only place that configures logging and the only one that writes to the
console. Commands stay thin: they parse options, call an application service
(:mod:`sivin.app`) and print its report. Exit codes: :class:`sivin.app.outcome.Outcome`
(``docs/cli.md``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from sivin import __version__
from sivin.cli.commands.config import config_app
from sivin.cli.commands.fetch import fetch
from sivin.cli.commands.pipeline import indices, ingest, qc, run
from sivin.cli.commands.sensors import sensors_app
from sivin.cli.state import CliOverrides, CliState
from sivin.logging_setup import setup_logging

app = typer.Typer(
    name="sivin",
    help="Vineyard weather stations: data collection, quality control and climate indices.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(config_app, name="config")
app.add_typer(sensors_app, name="sensors")
app.command("fetch")(fetch)
app.command("ingest")(ingest)
app.command("qc")(qc)
app.command("indices")(indices)
app.command("run")(run)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"sivin {__version__}")
        raise typer.Exit


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Configuration file. Default: config/sivin.yaml in the project root.",
            dir_okay=False,
        ),
    ] = None,
    log_level: Annotated[
        str, typer.Option("--log-level", help="DEBUG, INFO, WARNING, ERROR or CRITICAL.")
    ] = "INFO",
) -> None:
    """Vineyard weather stations: data collection, quality control and climate indices."""
    try:
        setup_logging(log_level)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--log-level") from error
    overrides = ctx.obj if isinstance(ctx.obj, CliOverrides) else CliOverrides()
    ctx.obj = CliState(config_file=config, overrides=overrides)
