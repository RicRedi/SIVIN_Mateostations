"""Tests of PortalClient against the fake portal (no real browser, no network)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from selenium.common.exceptions import TimeoutException, WebDriverException

from sivin.ingest.portal.client import (
    SELENIUM_WIRE_LOGGER,
    PortalClient,
    _secret_input_logging,
    xpath_literal,
)
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.portal.driver import WebDriverFactory
from sivin.ingest.portal.errors import ExportButtonNotFoundError, PortalLoginError, ViewModelError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.settings import PortalSelectors, PortalSettings

FIRST = PortalDevice("8615620 77678271")


def _factory(settings: PortalSettings, driver: Any) -> Any:
    class Factory(WebDriverFactory):
        name = "test"

        def create(self) -> Any:
            return driver

    return Factory(settings)


def test_login_follows_the_legacy_call_order(make_client: Any, settings: PortalSettings) -> None:
    client, driver = make_client()

    with client:
        client.login()

    assert driver.log == [
        ("get", settings.portal_url),
        ("send_keys", "username"),
        ("send_keys", "password"),
        ("click", "submit"),
        ("quit",),
    ]
    assert driver.page == "dashboard"


def test_wrong_password_is_a_login_error(make_client: Any) -> None:
    client, _ = make_client(login=PortalCredentials("synthetic-user", "wrong"))

    with client, pytest.raises(PortalLoginError, match="wrong credentials"):
        client.login()


def test_missing_login_form_is_a_login_error(make_client: Any, settings: PortalSettings) -> None:
    changed = settings.model_copy(update={"selectors": PortalSelectors(username_id="user")})
    _, driver = make_client()
    client = PortalClient(changed, PortalCredentials("u", "p"), _factory(changed, driver))

    with client, pytest.raises(PortalLoginError, match="login form was not found"):
        client.login()


def test_list_devices_reads_the_viewmodel(make_client: Any) -> None:
    client, driver = make_client()

    with client:
        client.login()
        devices = client.list_devices()

    assert [device.name for device in devices] == [
        "8615620 77678271",
        "8615621 77678272",
        "8615622 77678273",
    ]
    assert ("click", "folder") in driver.log
    assert driver.page == "folder"


def test_empty_viewmodel_value_is_an_error(make_client: Any) -> None:
    client, driver = make_client()
    driver.viewmodel_json = ""

    with client:
        client.login()
        with pytest.raises(ViewModelError, match="has no value"):
            client.list_devices()


def test_download_export_returns_the_new_file_and_goes_back(
    make_client: Any, settings: PortalSettings, fake_clock: Any
) -> None:
    old_export = settings.download_dir / "MeteoData_8615620 77678271 (VUT)_20260201_100000.xlsx"
    old_export.write_bytes(b"an older synthetic export")
    client, driver = make_client()

    with client:
        client.login()
        client.list_devices()
        path = client.download_export(FIRST)

    assert path.parent == settings.download_dir
    assert path != old_export
    assert path.name.startswith("MeteoData_8615620 77678271 (VUT)_")
    assert ("click", "excel:8615620 77678271") in driver.log
    assert ("click", "excel:hidden") not in driver.log
    assert ("script", "excel:8615620 77678271") in driver.log  # scrolled into view
    assert driver.log[-2:] == [("back",), ("quit",)]
    assert driver.page == "folder"
    # Two settle pauses of 0.5 s, then one watcher poll.
    assert fake_clock.sleeps[:2] == [0.5, 0.5]


def test_missing_export_button_is_reported(make_client: Any) -> None:
    client, _ = make_client({"8615620 77678271": "no_button"})

    with client:
        client.login()
        client.list_devices()
        with pytest.raises(ExportButtonNotFoundError, match="8615620 77678271"):
            client.download_export(FIRST)


def test_missing_tab_is_a_selenium_timeout(make_client: Any) -> None:
    client, _ = make_client({"8615620 77678271": "no_tab"})

    with client:
        client.login()
        client.list_devices()
        with pytest.raises(TimeoutException):
            client.download_export(FIRST)


def test_no_settle_pause_when_disabled(
    make_client: Any, settings: PortalSettings, fake_clock: Any
) -> None:
    quick = settings.model_copy(
        update={"timeouts": settings.timeouts.model_copy(update={"settle_delay_s": 0.0})}
    )
    _, driver = make_client()
    driver.settings = quick
    client = PortalClient(
        quick,
        PortalCredentials("synthetic-user", "synthetic-Secret-42"),
        _factory(quick, driver),
        clock=fake_clock,
    )

    with client:
        client.login()
        client.list_devices()
        client.download_export(FIRST)

    assert 0.5 not in fake_clock.sleeps


def test_return_to_folder_reloads_and_opens_the_folder(make_client: Any) -> None:
    client, driver = make_client()

    with client:
        client.login()
        client.return_to_folder()

    assert driver.page == "folder"


def test_client_must_be_opened(make_client: Any) -> None:
    client, _ = make_client()

    with pytest.raises(RuntimeError, match="not open"):
        client.login()


def test_relative_download_dir_is_rejected(credentials: PortalCredentials) -> None:
    settings = PortalSettings()

    with pytest.raises(ValueError, match="must be absolute"):
        PortalClient(settings, credentials, _factory(settings, None))


def test_failing_quit_is_logged(make_client: Any, caplog: pytest.LogCaptureFixture) -> None:
    client, driver = make_client()
    driver.quit_error = WebDriverException("browser already gone")

    with caplog.at_level(logging.WARNING), client:
        pass

    assert "Closing the browser failed: browser already gone" in caplog.text


def test_credentials_never_reach_the_logs(
    make_client: Any, caplog: pytest.LogCaptureFixture, credentials: PortalCredentials
) -> None:
    client, _ = make_client()

    with caplog.at_level(logging.DEBUG), client:
        client.login()
        client.list_devices()
        client.download_export(FIRST)

    assert credentials.password not in caplog.text
    assert credentials.username not in caplog.text
    assert credentials.password not in repr(client.__dict__)


def test_selenium_wire_logging_is_silenced_while_typing_secrets() -> None:
    wire_logger = logging.getLogger(SELENIUM_WIRE_LOGGER)
    previous = wire_logger.level
    wire_logger.setLevel(logging.DEBUG)
    try:
        with _secret_input_logging():
            assert wire_logger.level == logging.WARNING
        assert wire_logger.level == logging.DEBUG
    finally:
        wire_logger.setLevel(previous)


@pytest.mark.parametrize(
    ("text", "literal"),
    [
        ("SIVIN VUT", "'SIVIN VUT'"),
        ("it's", '"it\'s"'),
        ("a'b\"c", "concat('a', \"'\", 'b\"c')"),
    ],
)
def test_xpath_literal(text: str, literal: str) -> None:
    assert xpath_literal(text) == literal


def test_closing_an_unopened_client_does_nothing(make_client: Any) -> None:
    client, driver = make_client()

    client.__exit__(None, None, None)

    assert driver.log == []
