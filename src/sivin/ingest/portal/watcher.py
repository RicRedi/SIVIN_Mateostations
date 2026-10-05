"""Detecting a finished browser download in a directory.

The legacy script took the newest file of the download directory, so a failed download was
reported as the previous export. :class:`DownloadWatcher` instead compares the directory with
a snapshot taken before the click and only accepts a *new*, complete file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sivin.ingest.portal.clock import Clock
from sivin.ingest.portal.errors import DownloadTimeoutError

logger = logging.getLogger(__name__)

DEFAULT_PARTIAL_SUFFIXES: Final = (".crdownload", ".tmp")
"""Name endings of unfinished downloads: Chrome's ``.crdownload`` and generic ``.tmp``."""

DEFAULT_IGNORED_PREFIXES: Final = (".",)
"""Name beginnings of hidden files; Chrome on Linux writes ``.com.google.Chrome.*`` first."""


@dataclass(frozen=True, slots=True)
class DirectorySnapshot:
    """Names of the files present in the download directory at one moment.

    Parameters
    ----------
    names : frozenset[str]
        File names (not paths).
    """

    names: frozenset[str]


class DownloadWatcher:
    """Waits for a new, complete file in a download directory.

    A file counts as the download when it is not in the snapshot, its name does not end with
    a partial-download suffix (``.crdownload``, ``.tmp``) or start with an ignored prefix, and
    its size is the same in two consecutive polls.

    Parameters
    ----------
    directory : pathlib.Path
        The browser's download directory; created if missing.
    timeout_s : float
        Maximum wait for the download (s).
    poll_interval_s : float
        Pause between two polls (s).
    clock : Clock
        Time source (a fake one in tests).
    partial_suffixes : tuple[str, ...]
        File name endings of unfinished downloads.
    ignored_prefixes : tuple[str, ...]
        File name beginnings to ignore (hidden temporary files).
    """

    def __init__(
        self,
        directory: Path,
        timeout_s: float,
        poll_interval_s: float,
        clock: Clock,
        partial_suffixes: tuple[str, ...] = DEFAULT_PARTIAL_SUFFIXES,
        ignored_prefixes: tuple[str, ...] = DEFAULT_IGNORED_PREFIXES,
    ) -> None:
        if timeout_s <= 0 or poll_interval_s <= 0:
            raise ValueError("timeout_s and poll_interval_s must be positive.")
        self._directory = directory
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._clock = clock
        self._partial_suffixes = partial_suffixes
        self._ignored_prefixes = ignored_prefixes

    @property
    def directory(self) -> Path:
        """Return the watched directory.

        Returns
        -------
        pathlib.Path
            The download directory.
        """
        return self._directory

    def snapshot(self) -> DirectorySnapshot:
        """Record the files present now; call it right before triggering the download.

        Returns
        -------
        DirectorySnapshot
            Names of all files (including partial ones) in the directory.
        """
        self._directory.mkdir(parents=True, exist_ok=True)
        return DirectorySnapshot(frozenset(self._file_sizes()))

    def wait_for_new_file(self, before: DirectorySnapshot) -> Path:
        """Wait until a new, complete file appears.

        Parameters
        ----------
        before : DirectorySnapshot
            Snapshot taken before the download was triggered.

        Returns
        -------
        pathlib.Path
            The new file. When several complete files appear at once, the first by name is
            returned and the others are logged.

        Raises
        ------
        DownloadTimeoutError
            If no new complete file with a stable size appears within ``timeout_s``.
        """
        deadline = self._clock.monotonic() + self._timeout_s
        previous_sizes: dict[str, int] = {}
        while True:
            sizes = {
                name: size
                for name, size in self._file_sizes().items()
                if name not in before.names and self._is_complete(name)
            }
            stable = sorted(
                name for name, size in sizes.items() if previous_sizes.get(name) == size
            )
            if stable:
                if len(stable) > 1:
                    logger.warning("Several new downloads appeared at once: %s", stable)
                return self._directory / stable[0]
            if self._clock.monotonic() >= deadline:
                raise DownloadTimeoutError(
                    f"No new complete file appeared in {self._directory} within "
                    f"{self._timeout_s:g} s."
                )
            previous_sizes = sizes
            self._clock.sleep(self._poll_interval_s)

    def _is_complete(self, name: str) -> bool:
        return not name.endswith(self._partial_suffixes) and not name.startswith(
            self._ignored_prefixes
        )

    def _file_sizes(self) -> dict[str, int]:
        sizes: dict[str, int] = {}
        for entry in self._directory.iterdir():
            try:
                if entry.is_file():
                    sizes[entry.name] = entry.stat().st_size
            except FileNotFoundError:
                logger.debug("%s vanished while listing the download directory.", entry.name)
        return sizes
