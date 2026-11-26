"""Tests of the WebDriverFactory registry and of ChromeDriverFactory (no browser is started)."""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from typing import Any, ClassVar

import pytest
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.service import Service

from sivin.ingest.portal.driver import (
    BROWSER_DOWNLOAD_COMMAND,
    HEADLESS_ARGUMENT,
    PAGE_DOWNLOAD_COMMAND,
    CdpDownloadPermission,
    ChromeDriverFactory,
    WebDriverFactory,
    WebDriverFactoryRegistry,
    driver_factory_registry,
)
from sivin.ingest.portal.settings import PortalSettings


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "driver"


class _CdpDriver:
    """Fake Chrome driver recording CDP commands; ``failing`` commands raise."""

    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.failing = failing
        self.commands: list[tuple[str, dict[str, Any]]] = []

    def execute_cdp_cmd(self, cmd: str, cmd_args: dict[str, Any]) -> dict[str, Any]:
        self.commands.append((cmd, cmd_args))
        if cmd in self.failing:
            raise WebDriverException(f"unknown command {cmd}")
        return {}


class _CdpRecorder(_Recorder):
    def __init__(self, driver: _CdpDriver) -> None:
        super().__init__()
        self.driver = driver

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.driver


def _settings(tmp_path: Path, **kwargs: Any) -> PortalSettings:
    return PortalSettings(download_dir=tmp_path, **kwargs)


def test_chrome_is_registered() -> None:
    assert "chrome" in driver_factory_registry.names()
    factory = driver_factory_registry.create(PortalSettings())
    assert isinstance(factory, ChromeDriverFactory)


def test_registry_rejects_duplicates_nameless_classes_and_unknown_names() -> None:
    registry = WebDriverFactoryRegistry()

    class Firefox(WebDriverFactory):
        name: ClassVar[str] = "firefox"

        def create(self) -> Any:
            return None

    class Nameless(WebDriverFactory):
        def create(self) -> Any:
            return None

    assert registry.register(Firefox) is Firefox
    assert isinstance(registry.create(PortalSettings(browser="firefox")), Firefox)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Firefox)
    with pytest.raises(ValueError, match="no 'name'"):
        registry.register(Nameless)
    with pytest.raises(KeyError, match=r"Unknown browser 'opera'.*\['firefox'\]"):
        registry.create(PortalSettings(browser="opera"))


def test_options_configure_headless_downloads(tmp_path: Path) -> None:
    factory = ChromeDriverFactory(_settings(tmp_path), environ={})

    options = factory.options()

    assert options.arguments == [HEADLESS_ARGUMENT, "--window-size=1920,1080"]
    assert options.experimental_options["prefs"] == {
        "download.default_directory": str(tmp_path),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "profile.default_content_setting_values.automatic_downloads": 1,
    }
    assert options.binary_location == ""


def test_windowed_mode_has_no_headless_argument(tmp_path: Path) -> None:
    factory = ChromeDriverFactory(_settings(tmp_path, headless=False, chrome_arguments=()), {})

    assert factory.options().arguments == []


def test_relative_download_dir_is_rejected() -> None:
    factory = ChromeDriverFactory(PortalSettings(), environ={})

    with pytest.raises(ValueError, match="must be absolute"):
        factory.download_preferences()


def test_chrome_binary_from_settings_then_environment(tmp_path: Path) -> None:
    from_settings = ChromeDriverFactory(
        _settings(tmp_path, chrome_binary=Path("/opt/chrome")), {"CHROME_BINARY": "/env/chrome"}
    )
    from_env = ChromeDriverFactory(_settings(tmp_path), {"CHROME_BINARY": "/env/chrome"})

    assert from_settings.chrome_binary() == Path("/opt/chrome")
    assert from_env.options().binary_location == "/env/chrome"


def test_chromedriver_from_settings(tmp_path: Path) -> None:
    factory = ChromeDriverFactory(_settings(tmp_path, chromedriver_path=Path("/x/cd")), {})

    assert factory.chromedriver_path() == Path("/x/cd")


def test_chromedriver_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    assert ChromeDriverFactory(_settings(tmp_path), {}).chromedriver_path() == Path(
        "/usr/bin/chromedriver"
    )


def test_chromedriver_from_webdriver_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeManager:
        def install(self) -> str:
            return "/cache/chromedriver"

    fake_module = types.ModuleType("webdriver_manager.chrome")
    fake_module.ChromeDriverManager = FakeManager  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "webdriver_manager.chrome", fake_module)
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert ChromeDriverFactory(_settings(tmp_path), {}).chromedriver_path() == Path(
        "/cache/chromedriver"
    )


def test_create_passes_service_and_options(tmp_path: Path) -> None:
    recorder = _Recorder()
    factory = ChromeDriverFactory(
        _settings(tmp_path, chromedriver_path=Path("/x/chromedriver")), {}, driver_class=recorder
    )

    assert factory.create() == "driver"
    (call,) = recorder.calls
    assert isinstance(call["service"], Service)
    assert call["service"].path == "/x/chromedriver"
    assert call["options"].experimental_options["prefs"]["download.default_directory"] == str(
        tmp_path
    )


def test_chromedriver_from_the_runner_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_dir = tmp_path / "runner"
    runner_dir.mkdir()
    (runner_dir / "chromedriver").write_bytes(b"")
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    factory = ChromeDriverFactory(_settings(tmp_path), {"CHROMEWEBDRIVER": str(runner_dir)})

    assert factory.chromedriver_path() == runner_dir / "chromedriver"


def test_missing_runner_chromedriver_falls_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    factory = ChromeDriverFactory(_settings(tmp_path), {"CHROMEWEBDRIVER": str(tmp_path / "x")})

    assert factory.chromedriver_path() == Path("/usr/bin/chromedriver")


class TestCdpDownloadPermission:
    def test_browser_domain_allows_downloads(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        driver = _CdpDriver()
        caplog.set_level(logging.INFO, logger="sivin.ingest.portal.driver")

        assert CdpDownloadPermission(tmp_path).grant(driver) == "Browser.setDownloadBehavior"

        assert driver.commands == [
            (
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(tmp_path), "eventsEnabled": False},
            )
        ]
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_falls_back_to_the_page_domain(self, tmp_path: Path) -> None:
        driver = _CdpDriver(failing=(BROWSER_DOWNLOAD_COMMAND,))

        assert CdpDownloadPermission(tmp_path).grant(driver) == "Page.setDownloadBehavior"

        assert [command for command, _ in driver.commands] == [
            "Browser.setDownloadBehavior",
            "Page.setDownloadBehavior",
        ]
        assert driver.commands[1][1] == {"behavior": "allow", "downloadPath": str(tmp_path)}

    def test_both_failing_logs_a_warning_and_does_not_raise(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        driver = _CdpDriver(failing=(BROWSER_DOWNLOAD_COMMAND, PAGE_DOWNLOAD_COMMAND))

        assert CdpDownloadPermission(tmp_path).grant(driver) is None

        (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning.getMessage() == (
            "Could not allow downloads via CDP (Browser.setDownloadBehavior: "
            "WebDriverException; Page.setDownloadBehavior: WebDriverException); downloads "
            "rely on the profile preferences only."
        )

    def test_driver_without_cdp_logs_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert CdpDownloadPermission(tmp_path).grant(object()) is None

        (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert "cannot send CDP commands" in warning.getMessage()


@pytest.mark.parametrize("headless", [True, False], ids=["headless", "headed"])
def test_create_allows_downloads_via_cdp(tmp_path: Path, headless: bool) -> None:
    driver = _CdpDriver()
    recorder = _CdpRecorder(driver)
    factory = ChromeDriverFactory(
        _settings(tmp_path, headless=headless, chromedriver_path=Path("/x/chromedriver")),
        {},
        driver_class=recorder,
    )

    assert factory.create() is driver

    assert driver.commands == [
        (
            "Browser.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(tmp_path), "eventsEnabled": False},
        )
    ]
    prefs = recorder.calls[0]["options"].experimental_options["prefs"]
    assert prefs["download.default_directory"] == str(tmp_path)


def test_create_survives_a_driver_without_cdp(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    factory = ChromeDriverFactory(
        _settings(tmp_path, chromedriver_path=Path("/x/chromedriver")),
        {},
        driver_class=_Recorder(),
    )

    assert factory.create() == "driver"
    assert any("cannot send CDP commands" in r.getMessage() for r in caplog.records)


def test_create_uses_an_injected_permission(tmp_path: Path) -> None:
    class Permission(CdpDownloadPermission):
        def __init__(self) -> None:
            super().__init__(tmp_path / "elsewhere")
            self.granted: list[object] = []

        def grant(self, driver: object) -> str | None:
            self.granted.append(driver)
            return None

    permission = Permission()
    driver = _CdpDriver()
    factory = ChromeDriverFactory(
        _settings(tmp_path, chromedriver_path=Path("/x/chromedriver")),
        {},
        driver_class=_CdpRecorder(driver),
        permission=permission,
    )

    factory.create()

    assert permission.granted == [driver]
    assert driver.commands == []
