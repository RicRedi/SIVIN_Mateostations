"""Logging configuration; called only by the command-line entry point (:mod:`sivin.cli`).

Two safeguards keep the portal credentials out of every log (WP-1.7 review, major 1):

1. **Third-party loggers are capped** at WARNING whatever ``--log-level`` says
   (:data:`CAPPED_LOGGERS`). Selenium's ``remote_connection`` logger writes every WebDriver
   command body at DEBUG, including the text typed into the login form.
2. **Secrets are redacted** in every record by :class:`RedactingFilter` on the root handler,
   with the process's one :class:`~sivin.redaction.SecretRedactor` (the same one the CLI
   applies to its output, the run record and the derived files).
"""

from __future__ import annotations

import logging
from typing import Final, TextIO

from sivin.redaction import SecretRedactor

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


class RedactingFilter(logging.Filter):
    """Pass every record through the process's :class:`~sivin.redaction.SecretRedactor`.

    The message is formatted (``msg % args``) before redaction and the record then keeps the
    redacted text without arguments; the traceback text is redacted too.

    Parameters
    ----------
    redactor : SecretRedactor
        The redactor; replaced by :func:`install_redactor` once the credentials are loaded.
    """

    def __init__(self, redactor: SecretRedactor) -> None:
        super().__init__()
        self.redactor = redactor

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
        if not self.redactor.secrets:
            return True
        message = record.getMessage()
        redacted = self.redactor.redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.redactor.redact(record.exc_text)
        return True


def install_redactor(redactor: SecretRedactor) -> None:
    """Use ``redactor`` in the filters of the root handlers (after ``.env`` was loaded).

    Parameters
    ----------
    redactor : SecretRedactor
        The redactor of the loaded credentials.
    """
    for handler in logging.getLogger().handlers:
        for item in handler.filters:
            if isinstance(item, RedactingFilter):
                item.redactor = redactor


def setup_logging(
    level: str = "INFO", stream: TextIO | None = None, redactor: SecretRedactor | None = None
) -> None:
    """Configure the root logger to write to standard error, with the safeguards above.

    Parameters
    ----------
    level : str, optional
        Level name (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``), case-insensitive.
        The :data:`CAPPED_LOGGERS` never go below WARNING.
    stream : text stream, optional
        Where to write; standard error by default (tests pass a buffer).
    redactor : SecretRedactor, optional
        Redacts the credentials; built from the environment when omitted.

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
        handler.addFilter(
            RedactingFilter(redactor if redactor is not None else SecretRedactor.from_environment())
        )
    for name in CAPPED_LOGGERS:
        logging.getLogger(name).setLevel(max(CAPPED_LEVEL, numeric_level))
