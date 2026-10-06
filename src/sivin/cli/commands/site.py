"""``sivin build-site``: the static site data of the web portal."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from sivin.app.outcome import Outcome
from sivin.cli.common import echo_failures, finish, handled, state_of
from sivin.cli.console import console

if TYPE_CHECKING:
    from sivin.site.builder import SiteReport


def echo_site(report: SiteReport) -> None:
    """Print a summary of a site build and its failures.

    Parameters
    ----------
    report : SiteReport
        Result of the site-data step.
    """
    kind = "full" if report.full else "incremental"
    seasons = ", ".join(str(season) for season in report.seasons) or "none"
    console.echo(
        f"Site data ({kind}) -> {report.out_dir}: {len(report.built)} sensor(s) built, "
        f"{len(report.reused)} reused, {len(report.written)} file(s) written, "
        f"{len(report.removed)} removed; seasons: {seasons}"
    )
    echo_failures(report.failures)


def build_site(
    ctx: typer.Context,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            file_okay=False,
            help="Output directory. Default: <paths.site_dir>/data (site/data).",
        ),
    ] = None,
    season: Annotated[
        list[int] | None,
        typer.Option(
            "--season",
            help="Season year of an indices file; repeat for several. Default: every calendar "
            "year with data.",
        ),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Rebuild everything, ignoring the previous build state."),
    ] = False,
) -> None:
    """Generate the static site data of the web portal (docs/site.md).

    Reads every published sensor through quality control (off-site log included), computes
    the indices and writes manifest, registry copy, latest values, raw months, daily values,
    events and indices. Only sensors whose stored data changed are rebuilt unless --full.
    Exit code 1 if a sensor or an index failed.
    """
    with handled():
        report = state_of(ctx).services().site_service().build(out, season, full)
    echo_site(report)
    finish(Outcome.of(report.failures))
