"""``sivin sensors check``."""

from __future__ import annotations

import typer

from sivin.cli.common import finish, handled, state_of

sensors_app = typer.Typer(help="The sensor registry and the off-site log.", no_args_is_help=True)


@sensors_app.command("check")
def check(ctx: typer.Context) -> None:
    """Validate sensors/sensors.geojson and sensors/offsite_log.yaml.

    Exit code 0 when both are valid, 1 with the problems on standard error otherwise.
    """
    with handled():
        report = state_of(ctx).services().sensors_check().run()
    if report.catalog is not None:
        registry, log = report.catalog.registry, report.catalog.offsite_log
        typer.echo(f"Sensor registry: {len(registry)} sensor(s), {len(registry.active())} active.")
        typer.echo(f"Off-site log: {len(log)} period(s).")
    if report.problem is not None:
        typer.echo(report.problem, err=True)
    finish(report.outcome)
