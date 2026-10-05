"""Project root discovery and resolution of project-relative paths (MIGRATION_PLAN §1.3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

PROJECT_MARKER: Final = "pyproject.toml"
"""File that marks the project root directory."""


class ProjectRootNotFoundError(FileNotFoundError):
    """Raised when no directory containing :data:`PROJECT_MARKER` is found."""


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """The project root and resolution of paths relative to it.

    Paths in the configuration are relative to the project root, so the tools work regardless
    of the current working directory and no user-specific absolute path is ever committed.

    Parameters
    ----------
    root : pathlib.Path
        Absolute path of the project root.

    Raises
    ------
    ValueError
        If ``root`` is not absolute.
    """

    root: Path

    def __post_init__(self) -> None:
        if not self.root.is_absolute():
            raise ValueError(f"The project root must be an absolute path, got {self.root}.")

    @classmethod
    def discover(cls, start: Path | None = None) -> Self:
        """Find the project root by walking up from ``start``.

        Parameters
        ----------
        start : pathlib.Path, optional
            Directory (or file) to start from; the current working directory when omitted.

        Returns
        -------
        ProjectPaths
            Paths rooted at the nearest directory that contains ``pyproject.toml``.

        Raises
        ------
        ProjectRootNotFoundError
            If neither ``start`` nor any of its parents contains ``pyproject.toml``.
        """
        origin = (start if start is not None else Path.cwd()).resolve()
        for directory in (origin, *origin.parents):
            if (directory / PROJECT_MARKER).is_file():
                return cls(directory)
        raise ProjectRootNotFoundError(
            f"No {PROJECT_MARKER} found in {origin} or any parent directory; "
            "run the command inside the project or pass explicit paths."
        )

    def resolve(self, relative: str | Path) -> Path:
        """Resolve a project-relative path.

        Parameters
        ----------
        relative : str or pathlib.Path
            Path relative to the project root; an absolute path is returned unchanged.

        Returns
        -------
        pathlib.Path
            Absolute path.
        """
        path = Path(relative)
        return path if path.is_absolute() else self.root / path
