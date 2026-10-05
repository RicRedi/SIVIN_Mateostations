"""The logging safeguards: capped third-party loggers and redacted secrets (WP-1.7 review)."""

from __future__ import annotations

import io
import logging
import warnings
from collections.abc import Iterator

import pytest
from selenium.webdriver.remote.client_config import ClientConfig
from selenium.webdriver.remote.command import Command
from selenium.webdriver.remote.remote_connection import RemoteConnection

from sivin.logging_setup import CAPPED_LOGGERS, RedactingFilter, install_redactor, setup_logging
from sivin.redaction import REDACTED, SecretRedactor

PASSWORD = "pwSENTINEL-synthetic-42"
USER = "synthetic-operator"


@pytest.fixture
def log_stream(monkeypatch: pytest.MonkeyPatch) -> Iterator[io.StringIO]:
    """Configure logging into a buffer and restore the root and capped loggers afterwards."""
    monkeypatch.setenv("SIVIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("SIVIN_USER", USER)
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    capped = {name: logging.getLogger(name).level for name in CAPPED_LOGGERS}
    stream = io.StringIO()
    logging.captureWarnings(False)
    yield stream
    logging.captureWarnings(False)
    root.handlers[:], level = saved[0], saved[1]
    root.setLevel(level)
    for name, previous in capped.items():
        logging.getLogger(name).setLevel(previous)


def test_debug_send_keys_never_logs_the_password(
    log_stream: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_logging("DEBUG", log_stream)
    connection = RemoteConnection(client_config=ClientConfig("http://127.0.0.1:9"))
    monkeypatch.setattr(
        connection, "_request", lambda *args, **kwargs: {"status": 200, "value": None}
    )
    connection.execute(
        Command.SEND_KEYS_TO_ELEMENT,
        {"sessionId": "s", "id": "e", "text": PASSWORD, "value": list(PASSWORD)},
    )
    logging.getLogger("sivin.test").debug("typed %s as %s", PASSWORD, USER)
    output = log_stream.getvalue()
    assert PASSWORD not in output
    assert USER not in output
    assert f"typed {REDACTED} as {REDACTED}" in output
    assert logging.getLogger("selenium").level == logging.WARNING


def test_redaction_alone_hides_selenium_debug_bodies(
    log_stream: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_logging("DEBUG", log_stream)
    logging.getLogger("selenium").setLevel(logging.DEBUG)  # defence in depth: cap removed
    connection = RemoteConnection(client_config=ClientConfig("http://127.0.0.1:9"))
    monkeypatch.setattr(
        connection, "_request", lambda *args, **kwargs: {"status": 200, "value": None}
    )
    connection.execute(
        Command.SEND_KEYS_TO_ELEMENT, {"sessionId": "s", "id": "e", "text": PASSWORD}
    )
    output = log_stream.getvalue()
    assert "remote_connection" in output
    assert PASSWORD not in output


def test_tracebacks_are_redacted(log_stream: io.StringIO) -> None:
    setup_logging("INFO", log_stream)
    try:
        raise RuntimeError(f"login as {USER} failed")
    except RuntimeError:
        logging.getLogger("sivin.test").exception("failed")
    assert USER not in log_stream.getvalue()
    assert f"login as {REDACTED} failed" in log_stream.getvalue()


def test_without_secrets_records_are_untouched() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "a %s", ("b",), None)
    assert RedactingFilter(SecretRedactor()).filter(record)
    assert (record.msg, record.args) == ("a %s", ("b",))


def test_capped_loggers_follow_a_higher_level(log_stream: io.StringIO) -> None:
    setup_logging("ERROR", log_stream)
    assert logging.getLogger("urllib3").level == logging.ERROR


def test_install_redactor_replaces_the_secrets_of_the_handlers(log_stream: io.StringIO) -> None:
    setup_logging("INFO", log_stream, redactor=SecretRedactor())
    install_redactor(SecretRedactor.of({"SIVIN_PASSWORD": "loaded-from-dotenv"}))
    logging.getLogger("sivin.test").info("value loaded-from-dotenv")
    assert "loaded-from-dotenv" not in log_stream.getvalue()
    assert f"value {REDACTED}" in log_stream.getvalue()


def test_warnings_pass_the_redacting_filter(log_stream: io.StringIO) -> None:
    setup_logging("INFO", log_stream)
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.warn(f"login {USER} with {PASSWORD} looks odd", UserWarning, stacklevel=1)
    output = log_stream.getvalue()
    assert "py.warnings" in output
    assert f"login {REDACTED} with {REDACTED} looks odd" in output
    assert PASSWORD not in output
    assert USER not in output


def test_a_record_that_cannot_be_formatted_does_not_stop_the_run(
    log_stream: io.StringIO,
) -> None:
    setup_logging("INFO", log_stream)
    logging.getLogger("sivin.test").error("count %d", f"not a number {PASSWORD}")
    logging.getLogger("sivin.test").info("still logging")
    output = log_stream.getvalue()
    assert f"count %d ('not a number {REDACTED}',) (log message could not be formatted)" in (output)
    assert PASSWORD not in output
    assert "still logging" in output
