"""Command-line entry point ``sivin`` (``docs/cli.md``).

The only module tree that configures logging and writes to the console; the work is done by
the application services in :mod:`sivin.app`.
"""

from sivin.cli.main import app

__all__ = ["app"]
