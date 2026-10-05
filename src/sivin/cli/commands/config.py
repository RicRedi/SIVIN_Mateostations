"""``sivin config show`` and ``sivin config schema``."""

from __future__ import annotations

from typing import Annotated

import typer
import yaml

from sivin.cli.common import handled, state_of
from sivin.cli.state import CliState

config_app = typer.Typer(help="Inspect the configuration.", no_args_is_help=True)


@config_app.command("show")
def show(ctx: typer.Context) -> None:
    """Print the resolved configuration as YAML (file values, defaults and shared values).

    Outside a project and without --config, the defaults are shown.
    """
    with handled():
        resolved = state_of(ctx).config()
    typer.echo(
        yaml.safe_dump(resolved.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        nl=False,
    )


@config_app.command("schema")
def schema(
    markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            help="Print the key reference as Markdown tables instead of the JSON schema.",
        ),
    ] = False,
) -> None:
    """Print the JSON schema of config/sivin.yaml (with every registered check and index)."""
    typer.echo(CliState.schema_text(markdown), nl=False)
