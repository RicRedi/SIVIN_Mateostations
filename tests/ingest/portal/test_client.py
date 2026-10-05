"""Tests of PortalClient and PortalPage against the fake portal (no real browser, no network)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from selenium.common.exceptions import TimeoutException, WebDriverException

from sivin.ingest.portal.client import SELENIUM_WIRE_LOGGER, PortalClient, _secret_input_logging
from sivin.ingest.portal.credentials import PortalCredentials, Secret
from sivin.ingest.portal.errors import (
    DownloadIncompleteError,
    ExportButtonNotFoundError,
    PortalLoginError,
    ViewModelError,
)
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.page import xpath_literal
from sivin.ingest.portal.settings import PortalSelectors, PortalSettings

FIRST_NAME = "8615620 77678271"
FIRST = PortalDevice(FIRST_NAME)


def _on_device_list(client: PortalClient) -> Any:
    client.login()
    return client.list_devices()


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
    client, _ = make_client(login=PortalCredentials("synthetic-user", Secret("wrong")))

    with client, pytest.raises(PortalLoginError, match="wrong credentials"):
        client.login()


def test_missing_login_form_is_a_login_error(
    make_client: Any, settings: PortalSettings, factory_for: Any, credentials: PortalCredentials
) -> None:
    changed = settings.model_copy(update={"selectors": PortalSelectors(username_id="user")})
    _, driver = make_client()
    client = PortalClient(changed, credentials, factory_for(changed, driver))

    with client, pytest.raises(PortalLoginError, match="login form was not found"):
        client.login()


def test_list_devices_reads_the_viewmodel(make_client: Any) -> None:
    client, driver = make_client()

    with client:
        devices = _on_device_list(client)

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


def test_download_export_clicks_the_section_button_and_returns_the_new_file(
    make_client: Any, settings: PortalSettings, fake_clock: Any
) -> None:
    old_export = settings.download_dir / f"MeteoData_{FIRST_NAME} (VUT)_20260201_100000.xlsx"
    old_export.write_bytes(b"an older synthetic export")
    client, driver = make_client()

    with client:
        _on_device_list(client)
        path = client.download_export(FIRST)

    assert path.parent == settings.download_dir
    assert path != old_export
    assert path.name.startswith(f"MeteoData_{FIRST_NAME} (VUT)_")
    clicks = [entry[1] for entry in driver.log if entry[0] == "click"]
    assert clicks[-3:] == [f"device:{FIRST_NAME}", "meteo_tab", f"excel:{FIRST_NAME}"]
    assert ("script", f"excel:{FIRST_NAME}") in driver.log  # scrolled into view
    assert driver.page == f"meteo:{FIRST_NAME}"  # going back is the session's job
    # Device settle 0.5 s, tab settle 0.25 s, then one watcher poll of 0.01 s.
    assert fake_clock.sleeps == [0.5, 0.25, 0.01]


def test_spinner_is_waited_for_after_every_action(make_client: Any) -> None:
    client, driver = make_client()

    with client:
        _on_device_list(client)
        client.download_export(FIRST)

    # Folder, device and tab each show the spinner for 2 polls; the 3rd poll sees it hidden.
    # Waits: folder (3), before the device link (1), after the device (3), after the tab (3).
    assert driver.spinner_checks == 10


def test_stuck_spinner_times_out_with_a_clear_message(make_client: Any) -> None:
    client, driver = make_client()

    with client:
        _on_device_list(client)
        driver.spinner_stuck = True
        with pytest.raises(TimeoutException, match=r"Spinner #UpdateProgress is still visible"):
            client.download_export(FIRST)


def test_button_outside_the_section_is_used_with_a_warning(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, driver = make_client({FIRST_NAME: "no_section"})

    with client, caplog.at_level(logging.WARNING):
        _on_device_list(client)
        client.download_export(FIRST)

    assert "No Excel button in section 'Historie meteorologických dat'" in caplog.text
    assert ("click", f"excel:{FIRST_NAME}") in driver.log
    assert ("click", "excel:default-tab") not in driver.log


def test_missing_export_button_is_reported(make_client: Any) -> None:
    client, _ = make_client({FIRST_NAME: "no_button"})

    with client:
        _on_device_list(client)
        with pytest.raises(ExportButtonNotFoundError, match=FIRST_NAME):
            client.download_export(FIRST)


def test_missing_tab_is_a_selenium_timeout(make_client: Any) -> None:
    client, _ = make_client({FIRST_NAME: "no_tab"})

    with client:
        _on_device_list(client)
        with pytest.raises(TimeoutException, match="Tab 'Meteorologická data' is not clickable"):
            client.download_export(FIRST)


def test_empty_export_is_incomplete(make_client: Any) -> None:
    client, _ = make_client({FIRST_NAME: "empty"})

    with client:
        _on_device_list(client)
        with pytest.raises(DownloadIncompleteError, match="smaller than 1 B"):
            client.download_export(FIRST)


def test_export_name_without_serial_is_accepted_with_a_warning(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = make_client({FIRST_NAME: "unnamed"})

    with client, caplog.at_level(logging.WARNING):
        _on_device_list(client)
        path = client.download_export(FIRST)

    assert path.name == "export_1.xlsx"
    assert "has no sensor serial" in caplog.text


def test_device_without_serial_skips_the_name_check(
    settings: PortalSettings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        PortalClient._check_name(PortalDevice("Weather station"), Path("export.xlsx"))

    assert caplog.text == ""


@pytest.mark.parametrize("tab_adds_history", [False, True])
def test_back_to_device_list_in_both_history_variants(
    make_client: Any, settings: PortalSettings, tab_adds_history: bool
) -> None:
    client, driver = make_client(tab_adds_history=tab_adds_history)

    with client:
        _on_device_list(client)
        client.download_export(FIRST)
        client.back_to_device_list()

    assert driver.page == "folder"
    reloads = driver.log.count(("get", settings.portal_url)) - 1
    assert reloads == (1 if tab_adds_history else 0)


def test_return_to_folder_reloads_and_waits_for_the_list(make_client: Any) -> None:
    client, driver = make_client()

    with client:
        _on_device_list(client)
        client.return_to_folder()

    assert driver.page == "folder"


def test_return_to_folder_before_listing_waits_for_the_viewmodel(make_client: Any) -> None:
    client, driver = make_client()

    with client:
        client.login()
        client.return_to_folder()

    assert driver.page == "folder"


def test_settle_pauses_can_be_disabled(
    make_client: Any, settings: PortalSettings, fake_clock: Any
) -> None:
    quick = settings.model_copy(
        update={
            "timeouts": settings.timeouts.model_copy(
                update={"device_settle_s": 0.0, "tab_settle_s": 0.0}
            )
        }
    )
    client, _ = make_client(settings_override=quick)

    with client:
        _on_device_list(client)
        client.download_export(FIRST)

    assert fake_clock.sleeps == [0.01]


def test_client_must_be_opened(make_client: Any) -> None:
    client, _ = make_client()

    with pytest.raises(RuntimeError, match="not open"):
        client.login()


def test_relative_download_dir_is_rejected(
    credentials: PortalCredentials, factory_for: Any
) -> None:
    settings = PortalSettings()

    with pytest.raises(ValueError, match="must be absolute"):
        PortalClient(settings, credentials, factory_for(settings, None))


def test_failing_quit_is_logged(make_client: Any, caplog: pytest.LogCaptureFixture) -> None:
    client, driver = make_client()
    driver.quit_error = WebDriverException("browser already gone")

    with caplog.at_level(logging.WARNING), client:
        pass

    assert "Closing the browser failed: browser already gone" in caplog.text


def test_closing_an_unopened_client_does_nothing(make_client: Any) -> None:
    client, driver = make_client()

    client.__exit__(None, None, None)

    assert driver.log == []


def test_typed_credentials_never_reach_selenium_debug_logs(
    make_client: Any, caplog: pytest.LogCaptureFixture, credentials: PortalCredentials
) -> None:
    # The fake element logs typed text through selenium's request logger, as RemoteConnection
    # does; without the guard the password would be in the captured DEBUG records.
    client, _ = make_client()

    with caplog.at_level(logging.DEBUG), client:
        client.login()
        logging.getLogger(SELENIUM_WIRE_LOGGER).debug("after login")

    assert credentials.password.reveal() not in caplog.text
    assert credentials.username not in caplog.text
    assert "after login" in caplog.text  # the logger works again after typing


def test_without_the_guard_the_fake_would_leak(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, driver = make_client()

    with caplog.at_level(logging.DEBUG), client:
        driver.get(client.settings.portal_url)
        driver.find_element("id", "username").send_keys("visible-text")

    assert "visible-text" in caplog.text


def test_wire_log_level_is_restored_also_after_an_error() -> None:
    wire_logger = logging.getLogger(SELENIUM_WIRE_LOGGER)
    previous = wire_logger.level
    wire_logger.setLevel(logging.DEBUG)
    try:
        levels_inside: list[int] = []
        try:
            with _secret_input_logging():
                levels_inside.append(wire_logger.level)
                raise RuntimeError("typing failed")
        except RuntimeError:
            pass
        assert levels_inside == [logging.WARNING]
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
