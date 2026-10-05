"""Tests of PortalSession: one failing device never stops the run."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from selenium.common.exceptions import WebDriverException

from sivin.core.ids import SensorId
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.portal.errors import PortalLoginError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.session import NOT_LISTED_REASON, PortalSession, _describe
from sivin.ingest.portal.settings import PortalSettings

FIRST, SECOND, THIRD = "8615620 77678271", "8615621 77678272", "8615622 77678273"


def test_all_devices_are_downloaded(make_client: Any) -> None:
    client, driver = make_client()

    result = PortalSession(client).run()

    assert [download.device.name for download in result.downloads] == [FIRST, SECOND, THIRD]
    assert len(set(result.files)) == 3
    assert all(path.is_file() for path in result.files)
    assert result.ok
    assert driver.log[-1] == ("quit",)


def test_one_device_timing_out_does_not_stop_the_others(
    make_client: Any, settings: PortalSettings, fake_clock: Any
) -> None:
    stale = settings.download_dir / f"MeteoData_{SECOND} (VUT)_20260201_100000.xlsx"
    stale.write_bytes(b"older synthetic export of the failing device")
    client, driver = make_client({SECOND: "partial"})

    result = PortalSession(client).run()

    assert [download.device.name for download in result.downloads] == [FIRST, THIRD]
    assert stale not in result.files
    (failure,) = result.failures
    assert failure.device == PortalDevice(SECOND)
    assert failure.reason == (
        f"DownloadTimeoutError: No new complete file appeared in {settings.download_dir} "
        "within 3 s."
    )
    assert not result.ok
    # Recovery reloads the portal and opens the folder again before the next device.
    assert driver.log.count(("get", settings.portal_url)) == 2


def test_selenium_errors_are_recorded_per_device(make_client: Any) -> None:
    client, _ = make_client({FIRST: "no_tab", THIRD: "no_button"})

    result = PortalSession(client).run()

    assert [download.device.name for download in result.downloads] == [SECOND]
    reasons = {failure.device.name: failure.reason for failure in result.failures}
    assert reasons[FIRST] == "TimeoutException: Tab 'Meteorologická data' is not clickable."
    assert reasons[THIRD].startswith("ExportButtonNotFoundError: No visible Excel button")


def test_selected_sensors_and_unknown_ones(make_client: Any) -> None:
    client, _ = make_client()

    result = PortalSession(client).run([SensorId("77678273"), SensorId("99999999")])

    assert [download.device.name for download in result.downloads] == [THIRD]
    assert [(f.device.name, f.reason) for f in result.failures] == [("99999999", NOT_LISTED_REASON)]


def test_failed_recovery_is_logged_and_the_run_continues(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, driver = make_client({FIRST: "none"})
    driver.fail_get_after = 1  # the login works, the recovery reload fails

    with caplog.at_level(logging.WARNING):
        result = PortalSession(client).run()

    assert "Returning to the device list failed: WebDriverException: navigation failed" in (
        caplog.text
    )
    # The browser stays on the first device's tab, so the other devices fail as well, each
    # recorded on its own instead of aborting the run.
    assert [failure.device.name for failure in result.failures] == [FIRST, SECOND, THIRD]
    assert result.failures[0].reason.startswith("DownloadTimeoutError")
    assert result.failures[1].reason == f"TimeoutException: No link for device {SECOND!r}."
    assert result.downloads == ()


def test_login_failure_stops_the_run_and_closes_the_browser(make_client: Any) -> None:
    client, driver = make_client(login=PortalCredentials("synthetic-user", "wrong"))

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
