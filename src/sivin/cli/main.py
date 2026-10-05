"""The ``sivin`` application: global options and the registration of every command.

This package is the only place that configures logging and the only one that writes to the
console. Commands stay thin: they parse options, call an application service
(:mod:`sivin.app`) and print its report. Exit codes: :class:`sivin.app.outcome.Outcome`
(``docs/cli.md``).
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer

from sivin import __version__
from sivin.app.outcome import Outcome
from sivin.cli.commands.config import config_app
from sivin.cli.commands.fetch import fetch
from sivin.cli.commands.pipeline import indices, ingest, qc, run
from sivin.cli.commands.sensors import sensors_app
from sivin.cli.console import console
from sivin.cli.state import CliOverrides, CliState
from sivin.logging_setup import setup_logging
from sivin.redaction import SecretRedactor

app = typer.Typer(
    name="sivin",
    help="Vineyard weather stations: data collection, quality control and climate indices.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
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
        console.echo(f"sivin {__version__}")
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
    console.use(SecretRedactor.from_environment())
    try:
        setup_logging(log_level)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--log-level") from error
    overrides = ctx.obj if isinstance(ctx.obj, CliOverrides) else CliOverrides()
    ctx.obj = CliState(config_file=config, overrides=overrides)


def entry_point(args: Sequence[str] | None = None) -> None:
    """Run ``sivin`` (console script and ``python -m sivin``) with a last-resort error handler.

    An exception no command handles is a bug. Its full traceback is printed to standard error
    with the credentials redacted (the console's redactor and the current environment; Typer's
    own pretty tracebacks are disabled), and the process exits with
    :attr:`~sivin.app.outcome.Outcome.INTERNAL_ERROR` (5).

    Parameters
    ----------
    args : sequence of str, optional
        Command-line arguments; ``sys.argv[1:]`` when omitted.

    Raises
    ------
    SystemExit
        Always: the command's exit code, or 5 after an unexpected exception.
    """
    try:
        app(args=list(args) if args is not None else None)
    except Exception:
        text = SecretRedactor.from_environment().redact(traceback.format_exc())
        console.echo(f"Internal error (exit code 5); please report it:\n{text}", err=True)
        sys.exit(int(Outcome.INTERNAL_ERROR))
