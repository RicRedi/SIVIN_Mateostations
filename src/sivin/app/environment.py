"""Secrets from the environment and the local ``.env`` file (MIGRATION_PLAN §1.3, owner Q7)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DOTENV_FILE: Final = ".env"
"""Name of the local secrets file in the project root (git-ignored; template ``.env.example``)."""


class DotEnvLoader:
    """Load ``<project root>/.env`` into the process environment.

    Variables that are already set are **never** overridden, so GitHub Actions secrets and
    variables exported in the shell win over the file. Values are never logged.

    Parameters
    ----------
    root : pathlib.Path
        The project root.
    """

    __slots__ = ("_path",)

    def __init__(self, root: Path) -> None:
        self._path = root / DOTENV_FILE

    @property
    def path(self) -> Path:
        """The ``.env`` file this loader reads."""
        return self._path

    def load(self) -> bool:
        """Read the file if it exists.

        Returns
        -------
        bool
            ``True`` if the file exists and was read.
        """
        if not self._path.is_file():
            logger.debug("No %s; using the environment only.", self._path)
            return False
        load_dotenv(self._path, override=False)
        logger.debug("Read environment variables from %s (existing ones kept).", self._path)
        return True
