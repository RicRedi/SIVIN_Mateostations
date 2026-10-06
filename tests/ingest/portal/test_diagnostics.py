"""Tests of the diagnostics logged after a failed download (synthetic files, fake browser)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.by import By
from tests.ingest.portal.conftest import (
    PASSWORD,
    USERNAME,
    FakeElement,
    FakePortalDriver,
)

from sivin.ingest.portal.client import PortalClient
from sivin.ingest.portal.diagnostics import (
    ELLIPSIS,
    JS_READY_STATE,
    MAX_LISTED_FILES,
    MAX_NOTICES,
    MAX_TEXT_CHARS,
    DirectoryEntry,
    DirectoryListing,
    DownloadDiagnostics,
    EntryKind,
    public_url,
)
from sivin.ingest.portal.errors import DownloadIncompleteError, DownloadTimeoutError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.session import PortalSession
from sivin.ingest.portal.settings import PortalSelectors, PortalSettings

FIRST_NAME = "8615620 77678271"
NOTICE_CSS = PortalSelectors().notification_css


class StubElement:
    """A notice element with fixed text and visibility."""

    def __init__(self, text: str, displayed: bool = True) -> None:
        self.text = text
        self._displayed = displayed

    def is_displayed(self) -> bool:
        return self._displayed


class StubDriver:
    """The few WebDriver members the diagnostics read; ``broken`` makes every one fail."""

    def __init__(
        self,
        notices: list[StubElement] | None = None,
        url: str = "https://portal.example/Device?session=synthetic-token#tab",
        broken: bool = False,
    ) -> None:
        self._notices = notices or []
        self._url = url
        self._broken = broken
        self.queries: list[tuple[str, str]] = []

    def _check(self) -> None:
        if self._broken:
            raise WebDriverException("synthetic browser failure")

    @property
    def title(self) -> str:
        self._check()
        return "  Synthetic\n portal  "

    @property
    def current_url(self) -> str:
        self._check()
        return self._url

    @property
    def window_handles(self) -> list[str]:
        self._check()
        return ["w1", "w2"]

    def execute_script(self, script: str) -> str:
        self._check()
        assert script == JS_READY_STATE
        return "complete"

    def find_elements(self, by: str, value: str) -> list[StubElement]:
        self._check()
        self.queries.append((by, value))
        return self._notices


def _touch(path: Path, content: bytes, mtime_s: int) -> None:
    """Write a synthetic file with a fixed modification time (s since the epoch)."""
    path.write_bytes(content)
    os.utime(path, (mtime_s, mtime_s))


@pytest.fixture
def download_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "downloads"
    directory.mkdir()
    return directory


@pytest.fixture
def home_downloads(tmp_path: Path) -> Path:
    return tmp_path / "home" / "Downloads"


def _diagnostics(download_dir: Path, home_downloads: Path, **selectors: str) -> DownloadDiagnostics:
    settings = PortalSettings(download_dir=download_dir, selectors=PortalSelectors(**selectors))
    return DownloadDiagnostics(settings, download_dir, default_download_dir=home_downloads)


def test_listing_marks_unfinished_ignored_and_directories_newest_first(
    download_dir: Path, home_downloads: Path
) -> None:
    _touch(download_dir / "old.xlsx", b"12345", 1_000)
    _touch(download_dir / "new.xlsx.crdownload", b"1234567", 3_000)
    _touch(download_dir / ".com.google.Chrome.abc", b"", 2_000)
    (download_dir / "sub").mkdir()
    os.utime(download_dir / "sub", (500, 500))

    report = _diagnostics(download_dir, home_downloads).collect(StubDriver())

    assert report.download_dir.format() == (
        f"{download_dir}: 4 entries: new.xlsx.crdownload (7 B, unfinished); "
        ".com.google.Chrome.abc (0 B, ignored); old.xlsx (5 B); sub/ (directory)"
    )


def test_listing_of_an_empty_and_of_a_missing_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    missing = tmp_path / "missing"

    report = _diagnostics(empty, missing).collect(StubDriver())

    assert report.download_dir.format() == f"{empty}: empty"
    assert report.default_dir.format() == f"{missing}: absent"


def test_listing_is_capped_with_a_count_of_the_rest(download_dir: Path) -> None:
    entries = tuple(DirectoryEntry(f"f{index:02d}.xlsx", index) for index in range(12))

    text = DirectoryListing(download_dir, entries).format()

    assert MAX_LISTED_FILES == 10
    assert text.startswith(f"{download_dir}: 12 entries: f00.xlsx (0 B); f01.xlsx (1 B);")
    assert "f09.xlsx (9 B)" in text
    assert "f10.xlsx" not in text
    assert text.endswith(f"f09.xlsx (9 B); {ELLIPSIS} and 2 more")


def test_default_download_dir_is_listed_when_it_differs(
    download_dir: Path, home_downloads: Path
) -> None:
    home_downloads.mkdir(parents=True)
    _touch(home_downloads / "MeteoData_x.xlsx", b"abc", 1_000)

    report = _diagnostics(download_dir, home_downloads).collect(StubDriver())

    assert report.default_dir.format() == f"{home_downloads}: 1 entry: MeteoData_x.xlsx (3 B)"


def test_default_download_dir_equal_to_the_download_dir_is_not_listed_twice(
    download_dir: Path,
) -> None:
    report = _diagnostics(download_dir, download_dir).collect(StubDriver())

    assert report.default_dir.format() == f"{download_dir}: same as the download directory"


def test_default_download_dir_falls_back_to_the_home_directory(
    download_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    settings = PortalSettings(download_dir=download_dir)

    report = DownloadDiagnostics(settings, download_dir).collect(StubDriver())

    assert report.default_dir.format() == f"{tmp_path / 'home' / 'Downloads'}: absent"


def test_missing_home_directory_is_unavailable(
    download_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_home(cls: type[Path]) -> Path:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(no_home))
    settings = PortalSettings(download_dir=download_dir)

    report = DownloadDiagnostics(settings, download_dir).collect(StubDriver())

    assert report.default_dir.format() == "~/Downloads: unavailable (RuntimeError)"


def test_unreadable_directory_is_unavailable(
    download_dir: Path, home_downloads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(self: Path) -> Any:
        raise PermissionError("synthetic")

    monkeypatch.setattr(Path, "iterdir", denied)

    report = _diagnostics(download_dir, home_downloads).collect(StubDriver())

    assert report.download_dir.format() == f"{download_dir}: unavailable (PermissionError)"


def test_a_file_vanishing_while_listing_is_skipped(
    download_dir: Path, home_downloads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _touch(download_dir / "a.xlsx", b"1", 1_000)
    _touch(download_dir / "gone.xlsx.crdownload", b"1", 1_000)
    original_stat = Path.stat

    def stat(self: Path, **kwargs: Any) -> os.stat_result:
        if self.name == "gone.xlsx.crdownload":
            raise FileNotFoundError(self)
        return original_stat(self, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)

    report = _diagnostics(download_dir, home_downloads).collect(StubDriver())

    assert report.download_dir.entries == (DirectoryEntry("a.xlsx", 1, EntryKind.COMPLETE),)


def test_browser_state_without_query_and_fragment(download_dir: Path, home_downloads: Path) -> None:
    report = _diagnostics(download_dir, home_downloads).collect(StubDriver())

    assert report.browser.format() == (
        "title Synthetic portal; url https://portal.example/Device; readyState complete; windows 2"
    )


@pytest.mark.parametrize(
    ("url", "public"),
    [
        ("https://portal.example/Device?session=abc#tab", "https://portal.example/Device"),
        ("https://user:secret@portal.example:8443/a/b?x=1", "https://portal.example:8443/a/b"),
        ("https://portal.example/", "https://portal.example/"),
        ("about:blank", "about:blank"),
    ],
)
def test_public_url_strips_credentials_query_and_fragment(url: str, public: str) -> None:
    assert public_url(url) == public


def test_an_unparsable_url_is_unavailable(download_dir: Path, home_downloads: Path) -> None:
    driver = StubDriver(url="https://portal.example:port/x")

    report = _diagnostics(download_dir, home_downloads).collect(driver)

    assert report.browser.url == "unavailable (ValueError)"


def test_a_failing_browser_makes_every_browser_item_unavailable(
    download_dir: Path, home_downloads: Path
) -> None:
    report = _diagnostics(download_dir, home_downloads).collect(StubDriver(broken=True))

    unavailable = "unavailable (WebDriverException)"
    assert report.browser.format() == (
        f"title {unavailable}; url {unavailable}; readyState {unavailable}; windows {unavailable}"
    )
    assert report.notices.format() == unavailable


def test_visible_notices_are_reported_and_truncated(
    download_dir: Path, home_downloads: Path
) -> None:
    long_text = "x" * (MAX_TEXT_CHARS + 50)
    driver = StubDriver(
        notices=[
            StubElement("hidden error", displayed=False),
            StubElement("   "),
            StubElement("Export\n  failed"),
            StubElement(long_text),
        ]
    )

    report = _diagnostics(download_dir, home_downloads).collect(driver)

    truncated = "x" * (MAX_TEXT_CHARS - 1) + ELLIPSIS
    assert report.notices.texts == ("Export failed", truncated)
    assert report.notices.format() == f"'Export failed' | '{truncated}'"
    assert driver.queries == [(By.CSS_SELECTOR, NOTICE_CSS)]


def test_notices_are_capped(download_dir: Path, home_downloads: Path) -> None:
    driver = StubDriver(notices=[StubElement(f"n{index}") for index in range(MAX_NOTICES + 2)])

    report = _diagnostics(download_dir, home_downloads).collect(driver)

    assert report.notices.format() == f"'n0' | 'n1' | 'n2' | {ELLIPSIS} and 2 more"


def test_no_notices_and_disabled_search(download_dir: Path, home_downloads: Path) -> None:
    searched = _diagnostics(download_dir, home_downloads).collect(StubDriver())
    driver = StubDriver()
    disabled = _diagnostics(download_dir, home_downloads, notification_css="").collect(driver)

    assert searched.notices.format() == "none visible"
    assert disabled.notices.format() == "not searched (no selector)"
    assert driver.queries == []


def test_a_stale_notice_element_is_unavailable(download_dir: Path, home_downloads: Path) -> None:
    class StaleElement(StubElement):
        def is_displayed(self) -> bool:
            raise StaleElementReferenceException("synthetic")

    driver = StubDriver(notices=[StaleElement("gone")])

    report = _diagnostics(download_dir, home_downloads).collect(driver)

    assert report.notices.format() == "unavailable (StaleElementReferenceException)"


def test_full_report_text(download_dir: Path, home_downloads: Path) -> None:
    _touch(download_dir / "a.xlsx.crdownload", b"partial", 1_000)

    report = _diagnostics(download_dir, home_downloads).collect(
        StubDriver(notices=[StubElement("Server error")])
    )

    expected = (
        f"  download dir {download_dir}: 1 entry: a.xlsx.crdownload (7 B, unfinished)\n"
        f"  Chrome default dir {home_downloads}: absent\n"
        "  browser: title Synthetic portal; url https://portal.example/Device; "
        "readyState complete; windows 2\n"
        "  portal notices: 'Server error'"
    )
    assert report.format() == expected
    assert str(report) == expected


def _failed_download_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and "diagnostics" in record.getMessage()
    ]


@pytest.mark.parametrize(
    ("behaviour", "error", "listed"),
    [
        ("none", DownloadTimeoutError, "empty"),
        ("partial", DownloadTimeoutError, "(7 B, unfinished)"),
        ("empty", DownloadIncompleteError, "(0 B)"),
    ],
)
def test_failed_download_logs_one_diagnostics_block_and_reraises(
    make_client: Any,
    caplog: pytest.LogCaptureFixture,
    behaviour: str,
    error: type[Exception],
    listed: str,
) -> None:
    client, _ = make_client(behaviours={FIRST_NAME: behaviour})

    with caplog.at_level(logging.DEBUG), client:
        client.login()
        device = client.list_devices()[0]
        with pytest.raises(error):
            client.download_export(device)

    warnings = _failed_download_warnings(caplog)
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert message.startswith(
        f"Export of {PortalDevice(FIRST_NAME)} failed ({error.__name__}); diagnostics:\n"
    )
    assert listed in message.splitlines()[1]
    assert "url https://lemon.e-service.cz/meteo:" in message
    assert "synthetic-token" not in message
    assert "readyState complete; windows 1" in message
    assert message.endswith("portal notices: none visible")
    assert PASSWORD not in caplog.text
    assert USERNAME not in caplog.text


def test_the_block_shows_a_visible_portal_notice(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, driver = make_client(behaviours={FIRST_NAME: "none"})
    driver.notices = [FakeElement(driver, "toast", text="Export se nezdařil")]

    with caplog.at_level(logging.WARNING), client:
        client.login()
        device = client.list_devices()[0]
        with pytest.raises(DownloadTimeoutError):
            client.download_export(device)

    assert (
        _failed_download_warnings(caplog)[0]
        .getMessage()
        .endswith("portal notices: 'Export se nezdařil'")
    )


def test_a_failing_browser_does_not_mask_the_download_error(
    make_client: Any, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, driver = make_client(behaviours={FIRST_NAME: "none"})

    def broken_title(self: Any) -> str:
        raise WebDriverException("synthetic")

    with caplog.at_level(logging.WARNING), client:
        client.login()
        device = client.list_devices()[0]
        monkeypatch.setattr(type(driver), "title", property(broken_title), raising=False)
        with pytest.raises(DownloadTimeoutError, match="No new complete file"):
            client.download_export(device)

    message = _failed_download_warnings(caplog)[0].getMessage()
    assert "title unavailable (WebDriverException)" in message
    assert "url https://lemon.e-service.cz/meteo:" in message


class ExplodingDiagnostics(DownloadDiagnostics):
    """Diagnostics that fail with an error the collector does not expect."""

    def collect(self, driver: Any) -> Any:
        raise KeyError("synthetic")


def test_an_unexpected_collecting_error_does_not_mask_the_download_error(
    settings: PortalSettings,
    credentials: Any,
    viewmodel_json: str,
    fake_clock: Any,
    factory_for: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    driver = FakePortalDriver(settings, viewmodel_json, {FIRST_NAME: "none"})
    client = PortalClient(
        settings,
        credentials,
        factory_for(settings, driver),
        clock=fake_clock,
        diagnostics=ExplodingDiagnostics(settings, settings.download_dir),
    )

    with caplog.at_level(logging.WARNING), client:
        client.login()
        device = client.list_devices()[0]
        with pytest.raises(DownloadTimeoutError) as raised:
            client.download_export(device)

    assert isinstance(raised.value, DownloadTimeoutError)
    assert raised.value.__context__ is None
    assert (
        f"Export of {device} failed (DownloadTimeoutError); diagnostics unavailable (KeyError)."
        in caplog.text
    )


def test_session_retry_behaviour_is_unchanged(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = make_client(behaviours={FIRST_NAME: "none"})

    with caplog.at_level(logging.WARNING):
        result = PortalSession(client).run()

    assert len(result.files) == 2
    (failure,) = result.failures
    assert failure.device.name == FIRST_NAME
    assert failure.reason.startswith("DownloadTimeoutError: No new complete file appeared in ")
    assert failure.reason.endswith("within 3 s. (2 attempts)")
    assert len(_failed_download_warnings(caplog)) == 2


def test_successful_download_logs_no_diagnostics(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = make_client()

    with caplog.at_level(logging.WARNING), client:
        client.login()
        client.download_export(client.list_devices()[0])

    assert _failed_download_warnings(caplog) == []


def test_an_unresolvable_default_download_dir_is_unavailable(
    download_dir: Path, home_downloads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def loop(self: Path, strict: bool = False) -> Path:
        raise OSError("synthetic symlink loop")

    monkeypatch.setattr(Path, "resolve", loop)

    report = _diagnostics(download_dir, home_downloads).collect(StubDriver())

    assert report.default_dir.format() == f"{home_downloads}: unavailable (OSError)"
