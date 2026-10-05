"""Tests of PortalSession: one failing device never stops the run."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from selenium.common.exceptions import WebDriverException

from sivin.core.ids import SensorId
from sivin.ingest.portal.credentials import PortalCredentials, Secret
from sivin.ingest.portal.errors import PortalLoginError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.session import NOT_LISTED_REASON, PortalSession, _describe
from sivin.ingest.portal.settings import PortalSettings

FIRST, SECOND, THIRD = "8615620 77678271", "8615621 77678272", "8615622 77678273"


def _names(items: Any) -> list[str]:
    return [item.device.name for item in items]


@pytest.mark.parametrize("tab_adds_history", [False, True])
def test_all_devices_are_downloaded_in_both_history_variants(
    make_client: Any, settings: PortalSettings, tab_adds_history: bool
) -> None:
    client, driver = make_client(tab_adds_history=tab_adds_history)

    result = PortalSession(client).run()

    assert _names(result.downloads) == [FIRST, SECOND, THIRD]
    assert result.ok
    for download in result.downloads:
        assert download.device.sensor_id is not None
        assert download.device.sensor_id.serial in download.path.name
        assert download.path.is_file()
    # Login, plus one reload per device when back() lands on the device page.
    assert driver.log.count(("get", settings.portal_url)) == (4 if tab_adds_history else 1)
    assert driver.log[-1] == ("quit",)


def test_one_device_timing_out_does_not_stop_the_others(
    make_client: Any, settings: PortalSettings
) -> None:
    stale = settings.download_dir / f"MeteoData_{SECOND} (VUT)_20260201_100000.xlsx"
    stale.write_bytes(b"older synthetic export of the failing device")
    client, _ = make_client({SECOND: "partial"})

    result = PortalSession(client).run()

    assert _names(result.downloads) == [FIRST, THIRD]
    assert stale not in result.files
    (failure,) = result.failures
    assert failure.device == PortalDevice(SECOND)
    assert failure.reason == (
        f"DownloadTimeoutError: No new complete file appeared in {settings.download_dir} "
        "within 3 s. (2 attempts)"
    )
    assert not result.ok


@pytest.mark.parametrize("attempts", [1, 2])
def test_a_late_download_is_never_given_to_the_next_device(
    make_client: Any, settings: PortalSettings, attempts: int
) -> None:
    once = settings.model_copy(update={"attempts_per_device": attempts})
    client, _ = make_client({SECOND: "late"}, settings_override=once)

    result = PortalSession(client).run()

    # SECOND's export finishes only while THIRD is being downloaded.
    assert _names(result.failures) == [SECOND]
    assert _names(result.downloads) == [FIRST, THIRD]
    third = result.downloads[1].path
    assert "77678273" in third.name
    late_files = [p.name for p in settings.download_dir.iterdir() if "77678272" in p.name]
    assert len(late_files) == attempts
    assert all(name.endswith(".xlsx") for name in late_files)


def test_a_device_is_retried_once_after_recovery(
    make_client: Any, settings: PortalSettings
) -> None:
    client, driver = make_client({FIRST: "flaky"})

    result = PortalSession(client).run()

    assert result.ok
    assert _names(result.downloads) == [FIRST, SECOND, THIRD]
    assert driver.log.count(("get", settings.portal_url)) == 2  # login + one recovery


def test_selenium_errors_are_recorded_per_device(make_client: Any) -> None:
    client, _ = make_client({FIRST: "no_tab", THIRD: "no_button"})

    result = PortalSession(client).run()

    assert _names(result.downloads) == [SECOND]
    reasons = {failure.device.name: failure.reason for failure in result.failures}
    assert (
        reasons[FIRST]
        == "TimeoutException: Tab 'Meteorologická data' is not clickable. (2 attempts)"
    )
    assert reasons[THIRD].startswith("ExportButtonNotFoundError: No visible Excel button")


def test_a_failing_back_does_not_lose_the_download(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, driver = make_client()
    driver.back_error = WebDriverException("back failed")

    with caplog.at_level(logging.WARNING):
        result = PortalSession(client).run()

    assert _names(result.downloads) == [FIRST, SECOND, THIRD]
    assert result.ok
    assert "Export downloaded, but returning to the device list failed" in caplog.text


def test_selected_sensors_and_unknown_ones(make_client: Any) -> None:
    client, _ = make_client()

    result = PortalSession(client).run([SensorId("77678273"), SensorId("99999999")])

    assert _names(result.downloads) == [THIRD]
    assert [(f.device.name, f.reason) for f in result.failures] == [("99999999", NOT_LISTED_REASON)]


def test_failed_recovery_is_logged_and_the_run_continues(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, driver = make_client({FIRST: "none"})
    driver.fail_get_after = 1  # the login works, every reload fails

    with caplog.at_level(logging.WARNING):
        result = PortalSession(client).run()

    assert "Returning to the device list failed: WebDriverException: navigation failed" in (
        caplog.text
    )
    # The browser stays on the first device's tab, so the others fail as well, each recorded
    # on its own instead of aborting the run.
    assert _names(result.failures) == [FIRST, SECOND, THIRD]
    assert result.failures[0].reason.startswith("DownloadTimeoutError")
    assert result.failures[0].reason.endswith(
        f"(2 attempts; last: TimeoutException: No link for device {FIRST!r}.)"
    )
    assert result.downloads == ()


def test_login_failure_stops_the_run_and_closes_the_browser(make_client: Any) -> None:
    client, driver = make_client(login=PortalCredentials("synthetic-user", Secret("wrong")))

    with pytest.raises(PortalLoginError):
        PortalSession(client).run()
    assert driver.log[-1] == ("quit",)


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (WebDriverException("first line\n  stacktrace"), "WebDriverException: first line"),
        (WebDriverException(), "WebDriverException"),
        (OSError("disk full"), "OSError: disk full"),
    ],
)
def test_describe_gives_one_line(error: BaseException, text: str) -> None:
    assert _describe(error) == text
