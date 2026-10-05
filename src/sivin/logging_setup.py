"""Logging configuration; called only by the command-line entry point (:mod:`sivin.cli`).

Two safeguards keep the portal credentials out of every log (WP-1.7 review, major 1):

1. **Third-party loggers are capped** at WARNING whatever ``--log-level`` says
   (:data:`CAPPED_LOGGERS`). Selenium's ``remote_connection`` logger writes every WebDriver
   command body at DEBUG, including the text typed into the login form.
2. **Secrets are redacted** in every record by :class:`SecretRedactor`, a filter on the root
   handler: the current values of :data:`SECRET_ENV_VARS` are replaced by ``***`` in the
   formatted message and traceback, whichever logger produced it.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Final, TextIO

LOG_FORMAT: Final = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
"""Format of every log record."""

LOG_DATE_FORMAT: Final = "%Y-%m-%dT%H:%M:%S%z"
"""ISO 8601 timestamp format of log records (local time with UTC offset)."""

CAPPED_LOGGERS: Final = ("selenium", "urllib3", "WDM")
"""Loggers of third-party packages that never log below :data:`CAPPED_LEVEL`: Selenium (logs
WebDriver command bodies, i.e. typed credentials, at DEBUG), urllib3 (request lines) and
webdriver-manager (``WDM``)."""

CAPPED_LEVEL: Final = logging.WARNING
"""Lowest level the :data:`CAPPED_LOGGERS` emit."""

SECRET_ENV_VARS: Final = ("SIVIN_PASSWORD", "SIVIN_USER")
"""Environment variables whose values never appear in a log record."""

REDACTED: Final = "***"
"""Replacement text of a secret value."""


class SecretRedactor(logging.Filter):
    """Replace the current values of secret environment variables by ``***`` in a record.

    The values are read from the environment at every record, so secrets loaded later (from
    ``.env``) are covered too. The message is formatted (``msg % args``) before redaction and
    the record then keeps the redacted text without arguments.

    Parameters
    ----------
    names : sequence of str, optional
        Environment variables to redact; :data:`SECRET_ENV_VARS` by default.
    environ : callable, optional
        Returns the environment; :data:`os.environ` by default (tests pass a mapping).
    """

    def __init__(
        self,
        names: Sequence[str] = SECRET_ENV_VARS,
        environ: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self._names = tuple(names)
        self._environ = environ if environ is not None else _process_environment

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the record in place; never drops it.

        Parameters
        ----------
        record : logging.LogRecord
            The record.

        Returns
        -------
        bool
            Always ``True``.
        """
        environ = self._environ()
        secrets = sorted(
            {environ[name] for name in self._names if environ.get(name)}, key=len, reverse=True
        )
        if not secrets:
            return True
        message = record.getMessage()
        redacted = _redact(message, secrets)
        if redacted != message:
            record.msg, record.args = redacted, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _redact(record.exc_text, secrets)
        return True


def _process_environment() -> Mapping[str, str]:
    return os.environ


def _redact(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


def setup_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Configure the root logger to write to standard error, with the safeguards above.

    Parameters
    ----------
    level : str, optional
        Level name (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``), case-insensitive.
        The :data:`CAPPED_LOGGERS` never go below WARNING.
    stream : text stream, optional
        Where to write; standard error by default (tests pass a buffer).

    Raises
    ------
    ValueError
        If the level name is unknown.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper())
    if numeric_level is None:
        raise ValueError(f"Unknown log level {level!r}.")
    logging.basicConfig(
        level=numeric_level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, force=True, stream=stream
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(SecretRedactor())
    for name in CAPPED_LOGGERS:
        logging.getLogger(name).setLevel(max(CAPPED_LEVEL, numeric_level))
