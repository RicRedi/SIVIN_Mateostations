"""Tests of the WebDriverFactory registry and of ChromeDriverFactory (no browser is started)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, ClassVar

import pytest
from selenium.webdriver.chrome.service import Service

from sivin.ingest.portal.driver import (
    HEADLESS_ARGUMENT,
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
