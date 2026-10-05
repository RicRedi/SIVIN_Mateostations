"""Writing the derived JSON files atomically and byte-stable."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sivin.storage.atomic import AtomicFileWriter

logger = logging.getLogger(__name__)


class JsonFileWriter:
    """Write JSON documents atomically (temporary file + rename).

    The text is UTF-8, indented by two spaces, keys in the given order, with a final line
    break, so writing the same data twice gives the same bytes. ``NaN`` and infinite floats
    are written as ``null``.

    Parameters
    ----------
    writer : AtomicFileWriter, optional
        Replaces the target atomically; a default one when omitted.
    """

    __slots__ = ("_writer",)

    def __init__(self, writer: AtomicFileWriter | None = None) -> None:
        self._writer = writer if writer is not None else AtomicFileWriter()

    def write(self, path: Path, document: Mapping[str, Any]) -> Path:
        """Write one document (parent directories are created).

        Parameters
        ----------
        path : pathlib.Path
            Target file.
        document : Mapping
            JSON-compatible data (``str``, numbers, ``bool``, ``None``, mappings, sequences).

        Returns
        -------
        pathlib.Path
            ``path``.
        """
        text = json.dumps(finite(document), indent=2, ensure_ascii=False, allow_nan=False)
        with self._writer.open(path) as stream:
            stream.write((text + "\n").encode("utf-8"))
        return path


def finite(value: object) -> object:
    """Return JSON data with every ``NaN`` or infinite float replaced by ``None``.

    Parameters
    ----------
    value : object
        JSON-compatible data, nested freely; tuples become lists.

    Returns
    -------
    object
        The same data with non-finite floats as ``None``.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): finite(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [finite(item) for item in value]
    return value


def read_document(path: Path) -> dict[str, Any] | None:
    """Read a JSON object written earlier, for an update in place.

    Parameters
    ----------
    path : pathlib.Path
        The file.

    Returns
    -------
    dict or None
        The object; ``None`` if the file does not exist, or (with a warning) if it cannot be
        read or is not a JSON object, so that a broken file is replaced, never merged.
    """
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("%s cannot be read (%s); it is replaced.", path, error)
        return None
    if not isinstance(document, dict):
        logger.warning("%s is not a JSON object; it is replaced.", path)
        return None
    return document
