"""``sivin report``: the summary of a pipeline run (job summary of the scheduled workflow)."""

from __future__ import annotations

from typing import Annotated

import typer

from sivin.app.outcome import Outcome
from sivin.cli.common import finish, handled, state_of
from sivin.cli.console import console

FORMAT_HELP = "Output format: markdown (GitHub job summary) or text."


def report(
    ctx: typer.Context,
    output_format: Annotated[str, typer.Option("--format", help=FORMAT_HELP)] = "text",
    run: Annotated[
        str,
        typer.Option("--run", help="'latest', or a UTC date YYYY-MM-DD (its last run)."),
    ] = "latest",
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Ignore run records that started before this ISO 8601 time (UTC without "
            "offset); pass the start of the run you summarise.",
        ),
    ] = None,
    outcome: Annotated[
        int | None,
        typer.Option("--outcome", help="Exit code of the summarised command, shown on top."),
    ] = None,
) -> None:
    """Summarise a run: files, rows per sensor, rejected files, failures and QC warnings.

    Reads the run log (data/runs) and the derived events; writes nothing. Credentials are
    replaced by *** in the output. Exit code 0, 2 for invalid options, 3 outside a project
    or with an invalid configuration.
    """
    from sivin.app.summary import RunOutcome, RunSelection, RunSelectionError
    from sivin.app.summary_formats import summary_format_registry

    if output_format not in summary_format_registry:
        known = ", ".join(summary_format_registry.names())
        raise typer.BadParameter(f"Unknown format {output_format!r}; use one of: {known}.")
    try:
        selection = RunSelection.parse(run, since)
    except RunSelectionError as error:
        raise typer.BadParameter(str(error), param_hint="--run/--since") from error
    with handled():
        service = state_of(ctx).services().summary_service()
        summary = service.summarise(selection, RunOutcome(outcome) if outcome is not None else None)
    console.echo(summary_format_registry.create(output_format).render(summary), nl=False)
    finish(Outcome.OK)
