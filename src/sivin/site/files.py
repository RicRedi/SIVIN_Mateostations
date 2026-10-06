"""Site files as bytes, and the output directory they are written to.

A :class:`SiteFile` is the complete content of one file of the contract; the writers
(:mod:`sivin.site.sensor_files`, :mod:`sivin.site.site_files`) produce them and
:class:`SiteOutput` writes them, only when their bytes change.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sivin.redaction import SecretRedactor
from sivin.storage.atomic import AtomicFileWriter

logger = logging.getLogger(__name__)

MANAGED_DIRS: Final = ("series", "events", "indices")
"""Directories of the output that hold only builder files; others' files there are pruned."""

JSON_SEPARATORS: Final = (",", ":")
"""Compact JSON: no spaces after separators."""


def encode_json(document: Mapping[str, Any], redactor: SecretRedactor | None = None) -> bytes:
    """Encode a document as compact, stable UTF-8 JSON with a final line break.

    Keys keep the given order (the writers build them in contract order), so the same data
    always give the same bytes. ``NaN`` is not allowed: missing values must already be ``None``.

    Parameters
    ----------
    document : Mapping
        JSON-compatible data.
    redactor : SecretRedactor, optional
        Applied to every string (keys included); nothing is redacted when omitted.

    Returns
    -------
    bytes
        The encoded file content.
    """
    data = document if redactor is None else redactor.redact_data(document)
    text = json.dumps(data, ensure_ascii=False, separators=JSON_SEPARATORS, allow_nan=False)
    return (text + "\n").encode("utf-8")


def digest(content: bytes) -> str:
    """Return the SHA-256 of some bytes as hex.

    Parameters
    ----------
    content : bytes
        Any content.

    Returns
    -------
    str
        64 hex digits.
    """
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class SiteFile:
    """One output file.

    Attributes
    ----------
    path : str
        Path relative to the output directory, ``/``-separated (e.g. ``"events/77678271.json"``).
    content : bytes
        The complete file content.
    """

    path: str
    content: bytes

    def __post_init__(self) -> None:
        if self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError(f"Site file paths must be relative and inside the output: {self.path}")

    @property
    def digest(self) -> str:
        """SHA-256 of :attr:`content` (hex)."""
        return digest(self.content)


class SiteOutput:
    """The output directory (``site/data``): writes changed files, prunes stale ones.

    Parameters
    ----------
    root : pathlib.Path
        The output directory (created on the first write).
    writer : AtomicFileWriter, optional
        Replaces files atomically.
    """

    __slots__ = ("_root", "_writer")

    def __init__(self, root: Path, writer: AtomicFileWriter | None = None) -> None:
        self._root = root
        self._writer = writer if writer is not None else AtomicFileWriter()

    @property
    def root(self) -> Path:
        """The output directory."""
        return self._root

    def path_of(self, relative: str) -> Path:
        """Return the absolute path of an output file.

        Parameters
        ----------
        relative : str
            ``/``-separated path relative to the output directory.

        Returns
        -------
        pathlib.Path
            The file.
        """
        return self._root.joinpath(*relative.split("/"))

    def read(self, relative: str) -> bytes | None:
        """Return the bytes of an output file, or ``None`` if it does not exist.

        Parameters
        ----------
        relative : str
            ``/``-separated path relative to the output directory.

        Returns
        -------
        bytes or None
            The content.
        """
        path = self.path_of(relative)
        return path.read_bytes() if path.is_file() else None

    def has(self, relative: str, expected_digest: str) -> bool:
        """Tell whether an output file exists with the given SHA-256.

        Parameters
        ----------
        relative : str
            ``/``-separated path relative to the output directory.
        expected_digest : str
            SHA-256 (hex) the file must have.

        Returns
        -------
        bool
            ``True`` if the file is present and unchanged.
        """
        content = self.read(relative)
        return content is not None and digest(content) == expected_digest

    def write(self, file: SiteFile) -> bool:
        """Write a file unless it already has exactly this content.

        Parameters
        ----------
        file : SiteFile
            The file.

        Returns
        -------
        bool
            ``True`` if the file was written.
        """
        if self.read(file.path) == file.content:
            return False
        with self._writer.open(self.path_of(file.path)) as stream:
            stream.write(file.content)
        return True

    def prune(self, keep: Collection[str]) -> list[str]:
        """Delete every file below :data:`MANAGED_DIRS` that is not in ``keep``.

        Empty directories left behind are removed too. Files outside the managed directories
        (e.g. a README next to the data) are never touched.

        Parameters
        ----------
        keep : collection of str
            Relative paths of the files of this build.

        Returns
        -------
        list of str
            The deleted relative paths, sorted.
        """
        kept = set(keep)
        removed: list[str] = []
        for name in MANAGED_DIRS:
            directory = self._root / name
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*")):
                relative = path.relative_to(self._root).as_posix()
                if path.is_file() and relative not in kept:
                    path.unlink()
                    removed.append(relative)
            for path in [*sorted(directory.rglob("*"), reverse=True), directory]:
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
        if removed:
            logger.info("Removed %d stale site file(s).", len(removed))
        return sorted(removed)
