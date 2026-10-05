"""Helpers shared by the command modules: state, error handling, option parsing, exit codes."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import NoReturn

import typer

from sivin.app.outcome import Outcome, SetupError, UnknownIndexError
from sivin.cli.state import CliState
from sivin.core.ids import SensorId


def state_of(ctx: typer.Context) -> CliState:
    """Return the state the main callback stored in the context.

    Parameters
    ----------
    ctx : typer.Context
        Context of the running command.

    Returns
    -------
    CliState
        Global options and services.
    """
    state = ctx.find_root().obj
    if not isinstance(state, CliState):
        raise TypeError("The sivin callback did not run.")
    return state


@contextmanager
def handled() -> Iterator[None]:
    """Turn the errors of the application layer into exit codes and readable messages.

    A :class:`~sivin.app.outcome.SetupError` ends the command with exit code 3 and its
    message on standard error; an unknown index id is a usage error (exit code 2).

    Yields
    ------
    None
        The body runs inside the handler.
    """
    try:
        yield
    except SetupError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=int(Outcome.SETUP_ERROR)) from error
    except UnknownIndexError as error:
        raise typer.BadParameter(str(error), param_hint="--index") from error


def finish(outcome: Outcome) -> NoReturn:
    """End the command with the exit code of ``outcome``.

    Parameters
    ----------
    outcome : Outcome
        How the command ended.

    Raises
    ------
    typer.Exit
        Always.
    """
    raise typer.Exit(code=int(outcome))


def sensor_ids(values: Sequence[str] | None) -> list[SensorId] | None:
    """Parse ``--sensor`` values (any spelling of a sensor name).

    Parameters
    ----------
    values : sequence of str or None
        The option values.

    Returns
    -------
    list of SensorId or None
        ``None`` when the option was not given (= all sensors).

    Raises
    ------
    typer.BadParameter
        If a value names no sensor.
    """
    if not values:
        return None
    try:
        return [SensorId.parse(value) for value in values]
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--sensor") from error


def echo_failures(failures: Sequence[str]) -> None:
    """Print one line per failure to standard error.

    Parameters
    ----------
    failures : sequence of str
        Failure messages.
    """
    for failure in failures:
        typer.echo(f"FAILED {failure}", err=True)
