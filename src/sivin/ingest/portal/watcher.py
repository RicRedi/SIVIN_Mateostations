"""Detecting a finished browser download in a directory.

The legacy script took the newest file of the download directory, so a failed download was
reported as the previous export. :class:`DownloadWatcher` instead compares the directory with
a snapshot taken before the click and only accepts a *new*, complete file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, NoReturn

from sivin.core.ids import SensorId
from sivin.ingest.portal.clock import Clock
from sivin.ingest.portal.errors import DownloadIncompleteError, DownloadTimeoutError

logger = logging.getLogger(__name__)

DEFAULT_PARTIAL_SUFFIXES: Final = (".crdownload", ".tmp")
"""Name endings of unfinished downloads: Chrome's ``.crdownload`` and generic ``.tmp``."""

DEFAULT_IGNORED_PREFIXES: Final = (".",)
"""Name beginnings of hidden files; Chrome on Linux writes ``.com.google.Chrome.*`` first."""

DEFAULT_MIN_EXPORT_SIZE_BYTES: Final = 1
"""Smallest accepted export size in bytes: an empty file is never a valid export."""


class FileKind(Enum):
    """How the download watcher treats a file of the download directory."""

    COMPLETE = "complete"
    UNFINISHED = "unfinished"
    IGNORED = "ignored"
    TOO_SMALL = "too small"


@dataclass(frozen=True, slots=True)
class DirectorySnapshot:
    """Names of the files present in the download directory at one moment.

    Parameters
    ----------
    names : frozenset[str]
        File names (not paths), including unfinished downloads.
    pending : frozenset[str]
        Final names of the unfinished downloads in ``names`` (``a.xlsx`` for
        ``a.xlsx.crdownload``): a file that appears under such a name later belongs to an
        earlier download, not to the one that follows the snapshot.
    """

    names: frozenset[str]
    pending: frozenset[str] = frozenset()


class DownloadWatcher:
    """Waits for the file that one click produced in a download directory.

    A file counts as the download when

    * it is not in the snapshot taken before the click, is not the final name of a download
      that was unfinished at snapshot time, and is not left over from an earlier timed-out
      download of this watcher (late downloads are never given to the next device);
    * its name neither ends with a partial-download suffix (``.crdownload``, ``.tmp``) nor
      starts with an ignored prefix;
    * its size is the same in two consecutive polls and at least ``min_size_bytes``;
    * when a sensor is expected and the name contains a sensor serial, it is that sensor's
      serial (a file of another sensor is skipped with a warning).

    The watcher is stateful (it remembers late downloads); use one per download directory and
    session.

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
    min_size_bytes : int
        Smallest size (bytes) of a complete export; smaller stable files are rejected.
    """

    def __init__(
        self,
        directory: Path,
        timeout_s: float,
        poll_interval_s: float,
        clock: Clock,
        partial_suffixes: tuple[str, ...] = DEFAULT_PARTIAL_SUFFIXES,
        ignored_prefixes: tuple[str, ...] = DEFAULT_IGNORED_PREFIXES,
        min_size_bytes: int = DEFAULT_MIN_EXPORT_SIZE_BYTES,
    ) -> None:
        if timeout_s <= 0 or poll_interval_s <= 0:
            raise ValueError("timeout_s and poll_interval_s must be positive.")
        if min_size_bytes < 1:
            raise ValueError("min_size_bytes must be at least 1.")
        self._directory = directory
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._clock = clock
        self._partial_suffixes = partial_suffixes
        self._ignored_prefixes = ignored_prefixes
        self._min_size_bytes = min_size_bytes
        self._orphaned: set[str] = set()

    @property
    def directory(self) -> Path:
        """Return the watched directory.

        Returns
        -------
        pathlib.Path
            The download directory.
        """
        return self._directory

    @property
    def orphaned(self) -> frozenset[str]:
        """Return the names never accepted because they belong to an earlier download.

        Returns
        -------
        frozenset[str]
            Final names of timed-out downloads and files of other sensors.
        """
        return frozenset(self._orphaned)

    def classify(self, name: str, size_bytes: int) -> FileKind:
        """Return how the watcher treats a file, by its name and size.

        Parameters
        ----------
        name : str
            File name (not a path).
        size_bytes : int
            File size (bytes).

        Returns
        -------
        FileKind
            ``UNFINISHED`` (partial-download suffix), ``IGNORED`` (ignored prefix),
            ``TOO_SMALL`` (below ``min_size_bytes``) or ``COMPLETE``; the name rules come first.
        """
        kind = self._name_kind(name)
        if kind is FileKind.COMPLETE and size_bytes < self._min_size_bytes:
            return FileKind.TOO_SMALL
        return kind

    def snapshot(self) -> DirectorySnapshot:
        """Record the files present now; call it right before triggering the download.

        Returns
        -------
        DirectorySnapshot
            Names of all files in the directory and the final names of unfinished ones.
        """
        self._directory.mkdir(parents=True, exist_ok=True)
        names = frozenset(self._file_sizes())
        return DirectorySnapshot(names, frozenset(filter(None, map(self._final_name, names))))

    def wait_for_new_file(
        self, before: DirectorySnapshot, expected: SensorId | None = None
    ) -> Path:
        """Wait until the new, complete file of this download appears.

        Parameters
        ----------
        before : DirectorySnapshot
            Snapshot taken before the download was triggered.
        expected : SensorId, optional
            Sensor whose export is expected; files naming another sensor are skipped.

        Returns
        -------
        pathlib.Path
            The new file. When several qualify at once, the first by name is returned and the
            others are logged.

        Raises
        ------
        DownloadIncompleteError
            If only files smaller than ``min_size_bytes`` appeared within ``timeout_s``.
        DownloadTimeoutError
            If no new complete file with a stable size appeared within ``timeout_s``. Its
            unfinished files are remembered and never accepted by a later wait.
        """
        excluded = before.names | before.pending
        deadline = self._clock.monotonic() + self._timeout_s
        previous_sizes: dict[str, int] = {}
        too_small: set[str] = set()
        grace_used = False
        while True:
            expired = self._clock.monotonic() >= deadline
            sizes = self._new_files(excluded)
            accepted = self._accepted(sizes, previous_sizes, expected, too_small)
            if accepted:
                if len(accepted) > 1:
                    logger.warning("Several new downloads appeared at once: %s", accepted)
                return self._directory / accepted[0]
            if expired:
                unconfirmed = any(previous_sizes.get(name) != size for name, size in sizes.items())
                if grace_used or not unconfirmed:
                    self._give_up(excluded, too_small)
                grace_used = True  # one more poll to confirm a file seen at the deadline
            previous_sizes = sizes
            self._clock.sleep(self._poll_interval_s)

    def _accepted(
        self,
        sizes: dict[str, int],
        previous_sizes: dict[str, int],
        expected: SensorId | None,
        too_small: set[str],
    ) -> list[str]:
        """Return the stable candidates that qualify; record the too small and foreign ones."""
        accepted: list[str] = []
        for name in sorted(sizes):
            if previous_sizes.get(name) != sizes[name]:
                continue
            if self.classify(name, sizes[name]) is FileKind.TOO_SMALL:
                too_small.add(name)
            elif self._belongs_to_other_sensor(name, expected):
                self._orphaned.add(name)
            else:
                accepted.append(name)
        return accepted

    def _new_files(self, excluded: frozenset[str]) -> dict[str, int]:
        return {
            name: size
            for name, size in self._file_sizes().items()
            if name not in excluded and name not in self._orphaned and self._is_complete(name)
        }

    def _give_up(self, excluded: frozenset[str], too_small: set[str]) -> NoReturn:
        late = {
            self._final_name(name) or name for name in self._file_sizes() if name not in excluded
        }
        if late:
            logger.warning("Files of the timed-out download will be ignored: %s", sorted(late))
        self._orphaned.update(late)
        if too_small:
            raise DownloadIncompleteError(
                f"Only files smaller than {self._min_size_bytes} B appeared in "
                f"{self._directory}: {sorted(too_small)}."
            )
        raise DownloadTimeoutError(
            f"No new complete file appeared in {self._directory} within {self._timeout_s:g} s."
        )

    @staticmethod
    def _belongs_to_other_sensor(name: str, expected: SensorId | None) -> bool:
        if expected is None:
            return False
        try:
            found = SensorId.parse(name)
        except ValueError:
            return False
        if found == expected:
            return False
        logger.warning("Skipping %s: it is the export of %s, not of %s.", name, found, expected)
        return True

    def _final_name(self, name: str) -> str | None:
        for suffix in self._partial_suffixes:
            if name.endswith(suffix) and len(name) > len(suffix):
                return name.removesuffix(suffix)
        return None

    def _is_complete(self, name: str) -> bool:
        return self._name_kind(name) is FileKind.COMPLETE

    def _name_kind(self, name: str) -> FileKind:
        if name.endswith(self._partial_suffixes):
            return FileKind.UNFINISHED
        if name.startswith(self._ignored_prefixes):
            return FileKind.IGNORED
        return FileKind.COMPLETE

    def _file_sizes(self) -> dict[str, int]:
        sizes: dict[str, int] = {}
        for entry in self._directory.iterdir():
            try:
                if entry.is_file():
                    sizes[entry.name] = entry.stat().st_size
            except FileNotFoundError:
                logger.debug("%s vanished while listing the download directory.", entry.name)
        return sizes
