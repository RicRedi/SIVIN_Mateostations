"""Writing the derived JSON files atomically and byte-stable."""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sivin.redaction import SecretRedactor
from sivin.storage.atomic import AtomicFileWriter

logger = logging.getLogger(__name__)


class JsonFileWriter:
    """Write JSON documents atomically (temporary file + rename).

    The text is UTF-8, indented by two spaces, keys in the given order, with a final line
    break, so writing the same data twice gives the same bytes. ``NaN`` and infinite floats
    are written as ``null``.

    Every string (keys included) passes the redactor, so a credential inside e.g. an error
    message never reaches a derived file.

    Parameters
    ----------
    writer : AtomicFileWriter, optional
        Replaces the target atomically; a default one when omitted.
    redactor : SecretRedactor, optional
        Redacts the credentials; nothing is redacted when omitted.
    """

    __slots__ = ("_redactor", "_writer")

    def __init__(
        self, writer: AtomicFileWriter | None = None, redactor: SecretRedactor | None = None
    ) -> None:
        self._writer = writer if writer is not None else AtomicFileWriter()
        self._redactor = redactor if redactor is not None else SecretRedactor()

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
        clean = self._redactor.redact_data(finite(document))
        text = json.dumps(clean, indent=2, ensure_ascii=False, allow_nan=False)
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


class ErrorText:
    """Turn an exception into a text that may leave the process (derived files, run record).

    Absolute paths below the project root become relative (no runner paths in the published
    data) and the credentials are redacted.

    Parameters
    ----------
    root : pathlib.Path
        The project root.
    redactor : SecretRedactor
        Redacts the credentials.
    """

    __slots__ = ("_prefix", "_redactor")

    def __init__(self, root: Path, redactor: SecretRedactor) -> None:
        self._prefix = f"{root}{os.sep}"
        self._redactor = redactor

    def __call__(self, error: BaseException | str) -> str:
        """Return the safe text of an error.

        Parameters
        ----------
        error : BaseException or str
            The error or its message.

        Returns
        -------
        str
            The message with project paths relative and credentials redacted.
        """
        return self._redactor.redact(str(error).replace(self._prefix, ""))
