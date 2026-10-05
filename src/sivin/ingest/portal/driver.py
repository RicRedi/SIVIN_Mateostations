"""Starting the browser: the :class:`WebDriverFactory` extension point and Chrome.

Selenium is imported only by this module and by the client and session modules, never by
``import sivin`` or by the settings, so the package works without the ``ingest`` extra.
"""

from __future__ import annotations

import logging
import os
import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, ClassVar, Final

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.remote.webdriver import WebDriver

from sivin.ingest.portal.settings import (
    CHROME_BINARY_ENV_VAR,
    CHROMEDRIVER_DIR_ENV_VAR,
    PortalSettings,
)

logger = logging.getLogger(__name__)

HEADLESS_ARGUMENT: Final = "--headless=new"
"""Chrome's headless mode that behaves like the windowed browser (Chrome ≥ 109)."""

CHROMEDRIVER_EXECUTABLE: Final = "chromedriver"
"""Name of the chromedriver executable searched on ``PATH``."""

ALLOW: Final = 1
"""Chrome content-setting value 'allow'."""


class WebDriverFactory(ABC):
    """Starts a configured Selenium WebDriver; one subclass per browser.

    Subclasses register themselves with :data:`driver_factory_registry` under :attr:`name`.

    Parameters
    ----------
    settings : PortalSettings
        Portal settings; ``download_dir`` must already be absolute.
    """

    name: ClassVar[str]

    def __init__(self, settings: PortalSettings) -> None:
        self._settings = settings

    @abstractmethod
    def create(self) -> WebDriver:
        """Start the browser.

        Returns
        -------
        selenium.webdriver.remote.webdriver.WebDriver
            A driver that saves downloads into ``settings.download_dir`` without asking.
        """


type FactoryClass = type[WebDriverFactory]


class WebDriverFactoryRegistry:
    """Registry of :class:`WebDriverFactory` classes keyed by their :attr:`~WebDriverFactory.name`.

    Like the index registry, it is filled by class decorators at import time and never changed
    afterwards (the one kind of module-level mutable state MIGRATION_PLAN §1.2 allows).
    """

    __slots__ = ("_classes",)

    def __init__(self) -> None:
        self._classes: dict[str, FactoryClass] = {}

    def register[C: FactoryClass](self, cls: C) -> C:
        """Register a factory class; use as a class decorator.

        Parameters
        ----------
        cls : type[WebDriverFactory]
            The class; its ``name`` is the key.

        Returns
        -------
        type[WebDriverFactory]
            The class unchanged.

        Raises
        ------
        ValueError
            If the name is missing or already registered.
        """
        name = getattr(cls, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError(f"{cls.__name__} has no 'name'.")
        if name in self._classes:
            raise ValueError(f"A WebDriver factory named {name!r} is already registered.")
        self._classes[name] = cls
        return cls

    def create(self, settings: PortalSettings) -> WebDriverFactory:
        """Instantiate the factory named by ``settings.browser``.

        Parameters
        ----------
        settings : PortalSettings
            Portal settings.

        Returns
        -------
        WebDriverFactory
            The factory.

        Raises
        ------
        KeyError
            If no factory of that name is registered.
        """
        try:
            cls = self._classes[settings.browser]
        except KeyError:
            raise KeyError(
                f"Unknown browser {settings.browser!r}; registered: {sorted(self._classes)}."
            ) from None
        return cls(settings)

    def names(self) -> list[str]:
        """Return the registered names.

        Returns
        -------
        list[str]
            Sorted names.
        """
        return sorted(self._classes)


driver_factory_registry: Final = WebDriverFactoryRegistry()
"""The registry of browser factories."""


@driver_factory_registry.register
class ChromeDriverFactory(WebDriverFactory):
    """Starts Chrome or Chromium configured for unattended downloads.

    The browser executable is ``settings.chrome_binary``, else the ``CHROME_BINARY``
    environment variable, else whatever chromedriver finds. chromedriver is
    ``settings.chromedriver_path``, else ``$CHROMEWEBDRIVER/chromedriver`` (GitHub-hosted
    runners), else ``chromedriver`` on ``PATH``, else a matching one downloaded by
    webdriver-manager.

    Parameters
    ----------
    settings : PortalSettings
        Portal settings; ``download_dir`` must be absolute.
    environ : Mapping[str, str], optional
        Environment to read ``CHROME_BINARY`` and ``CHROMEWEBDRIVER`` from; :data:`os.environ`
        when omitted.
    driver_class : callable, optional
        Constructor of the driver, ``selenium.webdriver.Chrome`` by default (tests pass a fake).
    """

    name: ClassVar[str] = "chrome"

    def __init__(
        self,
        settings: PortalSettings,
        environ: Mapping[str, str] | None = None,
        driver_class: Callable[..., WebDriver] = webdriver.Chrome,
    ) -> None:
        super().__init__(settings)
        self._environ = os.environ if environ is None else environ
        self._driver_class = driver_class

    def create(self) -> WebDriver:
        """Start Chrome.

        Returns
        -------
        selenium.webdriver.remote.webdriver.WebDriver
            The running browser.

        Raises
        ------
        ValueError
            If ``settings.download_dir`` is not absolute (Chrome ignores relative paths).
        """
        options = self.options()
        service = ChromeService(executable_path=str(self.chromedriver_path()))
        logger.info(
            "Starting Chrome (headless=%s, downloads to %s).",
            self._settings.headless,
            self._settings.download_dir,
        )
        return self._driver_class(service=service, options=options)

    def options(self) -> ChromeOptions:
        """Build the Chrome options.

        Returns
        -------
        selenium.webdriver.chrome.options.Options
            Headless flag, extra arguments, browser binary and download preferences.
        """
        options = ChromeOptions()
        if self._settings.headless:
            options.add_argument(HEADLESS_ARGUMENT)
        for argument in self._settings.chrome_arguments:
            options.add_argument(argument)
        binary = self.chrome_binary()
        if binary is not None:
            options.binary_location = str(binary)
        options.add_experimental_option("prefs", self.download_preferences())
        return options

    def download_preferences(self) -> dict[str, Any]:
        """Return the Chrome preferences for silent downloads into the download directory.

        Returns
        -------
        dict[str, Any]
            Chrome profile preferences.

        Raises
        ------
        ValueError
            If ``settings.download_dir`` is not absolute.
        """
        download_dir = self._settings.download_dir
        if not download_dir.is_absolute():
            raise ValueError(
                f"download_dir must be absolute, got {download_dir}; "
                "resolve it with PortalSettings.resolved_against first."
            )
        return {
            "download.default_directory": str(download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "profile.default_content_setting_values.automatic_downloads": ALLOW,
        }

    def chrome_binary(self) -> Path | None:
        """Return the browser executable to use.

        Returns
        -------
        pathlib.Path or None
            ``settings.chrome_binary``, else ``$CHROME_BINARY``, else ``None`` (chromedriver
            looks for the browser itself).
        """
        if self._settings.chrome_binary is not None:
            return self._settings.chrome_binary
        from_env = self._environ.get(CHROME_BINARY_ENV_VAR)
        return Path(from_env) if from_env else None

    def chromedriver_path(self) -> Path:
        """Return the chromedriver executable to use.

        Returns
        -------
        pathlib.Path
            ``settings.chromedriver_path``, else ``$CHROMEWEBDRIVER/chromedriver`` if it
            exists, else ``chromedriver`` on ``PATH``, else a driver installed by
            webdriver-manager (needs network access to its download site).
        """
        if self._settings.chromedriver_path is not None:
            return self._settings.chromedriver_path
        runner_dir = self._environ.get(CHROMEDRIVER_DIR_ENV_VAR)
        if runner_dir:
            runner_driver = Path(runner_dir) / CHROMEDRIVER_EXECUTABLE
            if runner_driver.is_file():
                return runner_driver
        on_path = shutil.which(CHROMEDRIVER_EXECUTABLE)
        if on_path is not None:
            return Path(on_path)
        logger.info("No chromedriver on PATH; installing one with webdriver-manager.")
        from webdriver_manager.chrome import ChromeDriverManager

        return Path(ChromeDriverManager().install())
