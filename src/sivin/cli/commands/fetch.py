"""``sivin fetch``: download the exports from the data provider's portal."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from sivin.cli.common import echo_failures, finish, handled, sensor_ids, state_of
from sivin.cli.console import console

SENSOR_HELP = "Sensor to process (any name spelling); repeat for several. Default: all."


def fetch(
    ctx: typer.Context,
    sensor: Annotated[list[str] | None, typer.Option("--sensor", "-s", help=SENSOR_HELP)] = None,
    headed: Annotated[
        bool, typer.Option("--headed", help="Show the browser window (default: headless).")
    ] = False,
    download_dir: Annotated[
        Path | None,
        typer.Option(
            "--download-dir",
            file_okay=False,
            help="Save the exports here instead of ingest.portal.download_dir.",
        ),
    ] = None,
) -> None:
    """Log in to the portal and download one export per sensor.

    Credentials come from SIVIN_USER and SIVIN_PASSWORD (environment or .env); they are
    never printed. Exit code 1 if a device failed, 3 if nothing could be fetched.
    """
    wanted = sensor_ids(sensor)
    with handled():
        report = state_of(ctx).services().fetch_service(headed, download_dir).fetch(wanted)
    for path in report.files:
        console.echo(f"DOWNLOADED {path}")
    echo_failures(report.failures)
    finish(report.outcome)
