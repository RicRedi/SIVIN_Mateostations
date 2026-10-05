"""``sivin ingest``, ``sivin qc``, ``sivin indices`` and ``sivin run``."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer

from sivin.app.outcome import Outcome
from sivin.app.period import TimeBounds
from sivin.cli.commands.fetch import SENSOR_HELP
from sivin.cli.commands.report import echo_indices, echo_ingest, echo_quality
from sivin.cli.commands.site import echo_site
from sivin.cli.common import echo_failures, finish, handled, sensor_ids, state_of
from sivin.cli.console import console

DRY_RUN_HELP = "Compute and report, but write nothing."


class QuarantineChoice(StrEnum):
    """Values of ``sivin ingest --quarantine-mode``.

    The same values as :class:`~sivin.config.sections.QuarantineMode`, which is not imported
    here because the configuration models pull in pandas (``sivin --help`` stays fast).
    """

    MOVE = "move"
    COPY = "copy"


SensorOption = Annotated[list[str] | None, typer.Option("--sensor", "-s", help=SENSOR_HELP)]
DryRunOption = Annotated[bool, typer.Option("--dry-run", help=DRY_RUN_HELP)]


def ingest(
    ctx: typer.Context,
    files: Annotated[
        list[Path] | None,
        typer.Argument(exists=True, dir_okay=False, help="Export files (CSV or XLSX)."),
    ] = None,
    from_dir: Annotated[
        Path | None,
        typer.Option(
            "--from-dir",
            exists=True,
            file_okay=False,
            help="Ingest every export in this directory (ingest.file_patterns). Default "
            "without FILES: ingest.portal.download_dir.",
        ),
    ] = None,
    quarantine_mode: Annotated[
        QuarantineChoice | None,
        typer.Option(
            "--quarantine-mode",
            case_sensitive=False,
            help="move: a rejected file leaves its directory (also a file you named); copy: "
            "it stays. Default: ingest.quarantine_mode (move).",
        ),
    ] = None,
    dry_run: DryRunOption = False,
) -> None:
    """Parse and validate export files; quarantine rejected ones, append the rest to the store.

    Writes a run record to data/runs/<date>.jsonl. Exit code 1 if a file was rejected.
    """
    with handled():
        from sivin.config.sections import QuarantineMode

        services = state_of(ctx).services()
        paths = services.export_paths(files or [], from_dir)
        started = services.clock()
        mode = QuarantineMode(quarantine_mode.value) if quarantine_mode is not None else None
        report = services.ingest_service(dry_run, mode).ingest(paths)
        if not paths:
            console.echo("No export files to ingest.")
        elif not dry_run:
            recorder = services.run_recorder()
            recorder.write(recorder.record(started, services.clock(), report))
    echo_ingest(report)
    finish(report.outcome)


def qc(
    ctx: typer.Context,
    sensor: SensorOption = None,
    start: Annotated[
        str | None,
        typer.Option(
            "--from",
            help="First time to check, ISO 8601; a date or a time without offset is local "
            "time (time.display_timezone). Default: the first stored sample.",
        ),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option(
            "--to", help="Last time to check (a date includes the whole day). Default: the end."
        ),
    ] = None,
    dry_run: DryRunOption = False,
) -> None:
    """Quality control of the stored data with the off-site log; writes the derived events.

    Exit code 1 if a sensor failed, 3 if the registry, the off-site log or the
    configuration is invalid.
    """
    wanted = sensor_ids(sensor)
    with handled():
        services = state_of(ctx).services()
        try:
            bounds = TimeBounds.parse(start, end, services.workspace.config.time.display_timezone)
        except ValueError as error:
            raise typer.BadParameter(str(error), param_hint="--from/--to") from error
        report = services.quality_service(dry_run).run(wanted, bounds.start, bounds.end)
    echo_quality(report)
    finish(report.outcome)


def indices(
    ctx: typer.Context,
    season: Annotated[int, typer.Option("--season", help="Season year, e.g. 2026.")],
    index: Annotated[
        list[str] | None,
        typer.Option("--index", "-i", help="Index id; repeat for several. Default: all."),
    ] = None,
    sensor: SensorOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Compute the climate indices of a season (QC first); writes derived/indices/<season>.json.

    Exit code 1 if a sensor or index failed, 2 for an unknown index id.
    """
    wanted = sensor_ids(sensor)
    with handled():
        report = state_of(ctx).services().indices_service(dry_run).run(season, wanted, index)
    echo_indices(report)
    finish(report.outcome)


def run(
    ctx: typer.Context,
    season: Annotated[
        int | None,
        typer.Option("--season", help="Season year of the indices. Default: the current year."),
    ] = None,
    sensor: SensorOption = None,
    skip_fetch: Annotated[
        bool,
        typer.Option(
            "--skip-fetch",
            help="Do not use the portal; ingest the exports already in the download directory.",
        ),
    ] = False,
    headed: Annotated[bool, typer.Option("--headed", help="Show the browser window.")] = False,
    skip_site: Annotated[
        bool,
        typer.Option("--skip-site", help="Do not build the site data (sivin build-site)."),
    ] = False,
    dry_run: DryRunOption = False,
) -> None:
    """Fetch, ingest, QC, indices and site data in one go (used by the scheduled workflow).

    Goes on past a failed device, file or sensor, and past a failed portal login (the stored
    data stay). Exit code 1 if anything failed, 0 otherwise.
    """
    wanted = sensor_ids(sensor)
    with handled():
        services = state_of(ctx).services()
        zone = ZoneInfo(services.workspace.config.time.display_timezone)
        year = season if season is not None else services.clock().astimezone(zone).year
        report = services.run_service(dry_run, skip_fetch, headed, skip_site).run(year, wanted)
    if report.fetch_note is not None:
        console.echo(f"Note: {report.fetch_note}.")
    echo_failures(report.fetch_failures)
    echo_ingest(report.ingest)
    echo_quality(report.quality)
    echo_indices(report.indices)
    if report.site is not None:
        echo_site(report.site)
    elif not report.site_failures:
        console.echo("Site data not built (--skip-site or --dry-run).")
    echo_failures(report.site_failures if report.site is None else ())
    console.echo(f"Run finished: {Outcome(report.outcome).name}.")
    finish(report.outcome)
