"""Atomic replacement of a file: write a temporary sibling, then rename it over the target."""

from __future__ import annotations

import contextlib
import logging
import os
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Final

logger = logging.getLogger(__name__)

TEMP_PREFIX: Final = "."
"""Prefix of temporary files; hidden, and never a valid partition file name."""

TEMP_SUFFIX: Final = ".tmp"
"""Suffix of temporary files."""

NEW_FILE_MODE: Final = 0o644
"""Permission bits of a newly created file (owner read/write, others read).

:func:`tempfile.mkstemp` creates files readable by the owner only; an existing target keeps its
own mode.
"""


class AtomicFileWriter:
    """Writes a file so that readers see either the complete old or the complete new content.

    The content goes to a temporary file in the target's directory (same file system), which is
    flushed, ``fsync``-ed and then renamed over the target with :func:`os.replace`. If anything
    raises before the rename, the temporary file is removed and the target is left untouched. A
    process killed before the rename may leave a hidden ``.<name>.*.tmp`` file behind; it is
    ignored by the store and can be deleted.
    """

    __slots__ = ()

    @contextlib.contextmanager
    def open(self, target: Path) -> Iterator[IO[bytes]]:
        """Open a binary stream whose content replaces ``target`` on a clean exit.

        Parent directories are created as needed.

        Parameters
        ----------
        target : pathlib.Path
            The file to create or replace.

        Yields
        ------
        binary file object
            The stream to write the complete new content to.

        Raises
        ------
        Exception
            Whatever the body of the ``with`` block raises; the target is then unchanged.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f"{TEMP_PREFIX}{target.name}.", suffix=TEMP_SUFFIX, dir=target.parent
        )
        temp_path = Path(temp_name)
        try:
            os.chmod(temp_path, _mode_for(target))
            with os.fdopen(descriptor, "wb") as stream:
                yield stream
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, target)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            logger.debug("Discarded the incomplete write of %s.", target)
            raise
        logger.debug("Wrote %s atomically.", target)


def _mode_for(target: Path) -> int:
    """Return the permission bits the replaced file should have."""
    try:
        return stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        return NEW_FILE_MODE
