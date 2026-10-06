"""Settings of the portal client as frozen pydantic models (MIGRATION_PLAN §1.3).

The values default to what the legacy ``chrome_driver.py`` used against the portal. Selectors
are grouped in :class:`PortalSelectors`, so a change of the portal's HTML is fixed in the
configuration, not in the code. Credentials are not settings; see
:class:`~sivin.ingest.portal.credentials.PortalCredentials`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sivin.ingest.portal.watcher import (
    DEFAULT_IGNORED_PREFIXES,
    DEFAULT_MIN_EXPORT_SIZE_BYTES,
    DEFAULT_PARTIAL_SUFFIXES,
)
from sivin.paths import ProjectPaths

TEXT_PLACEHOLDER: Final = "{text}"
"""Placeholder in XPath templates, replaced by a quoted XPath string literal."""

CHROME_BINARY_ENV_VAR: Final = "CHROME_BINARY"
"""Environment variable naming the Chrome/Chromium executable when ``chrome_binary`` is unset."""

CHROMEDRIVER_DIR_ENV_VAR: Final = "CHROMEWEBDRIVER"
"""Environment variable of GitHub-hosted runner images: the directory containing chromedriver."""


class _Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PortalSelectors(_Settings):
    """Locators of the portal's HTML elements (taken from the legacy ``chrome_driver.py``).

    Adjust these when the portal's HTML changes; ``docs/ingest.md`` says which one belongs to
    which step. XPath templates contain ``{text}``, which is replaced by a quoted literal.
    """

    username_id: str = Field("username", description="HTML id of the user name input (id).")
    password_id: str = Field("password", description="HTML id of the password input (id).")
    submit_css: str = Field(
        "input[type='submit']", description="CSS selector of the login submit button (CSS)."
    )
    spinner_id: str = Field(
        "UpdateProgress",
        description="HTML id of the DotVVM progress spinner; waited for to disappear (id).",
    )
    viewmodel_id: str = Field(
        "__dot_viewmodel_root",
        description="HTML id of the hidden input holding the DotVVM viewmodel JSON (id).",
    )
    link_xpath_template: str = Field(
        "//a[contains(., {text})]",
        description=(
            "XPath of a link whose text contains {text}; used for the folder and the device "
            "links (XPath template)."
        ),
    )
    tab_xpath_template: str = Field(
        "//a[contains(text(), {text})]",
        description="XPath of the tab link whose own text contains {text} (XPath template).",
    )
    excel_button_xpath: str = Field(
        "//button[.//i[contains(@class, 'mdi-file-excel')]]",
        description=(
            "XPath of all Excel export buttons; the first visible one is the fallback when no "
            "button is found inside the export section (XPath)."
        ),
    )
    section_button_xpath_template: str = Field(
        "//*[contains(normalize-space(text()), {text})]"
        "/ancestor::*[.//button[.//i[contains(@class, 'mdi-file-excel')]]][1]"
        "//button[.//i[contains(@class, 'mdi-file-excel')]]",
        description=(
            "XPath of the Excel buttons inside the section whose heading contains {text} "
            "(export_section_name): the nearest ancestor of the heading that holds an Excel "
            "button, then its buttons. A visible match also proves that the meteorological tab "
            "is shown. Structure assumed from the legacy comments, [to be verified] (XPath "
            "template)."
        ),
    )

    notification_css: str = Field(
        "[role='alert'], [role='status'], .alert, .toast, .notification",
        description=(
            "CSS selector of visible portal error or notification messages, whose text is "
            "logged when a download fails; generic ARIA roles and common toast classes, not "
            "taken from the portal's HTML, [to be verified]. Empty disables the search (CSS)."
        ),
    )

    @field_validator("link_xpath_template", "tab_xpath_template", "section_button_xpath_template")
    @classmethod
    def _has_placeholder(cls, value: str) -> str:
        if TEXT_PLACEHOLDER not in value:
            raise ValueError(f"an XPath template must contain {TEXT_PLACEHOLDER}")
        return value


class PortalTimeouts(_Settings):
    """Waiting times of the portal client, in seconds."""

    element_wait_s: float = Field(
        15.0,
        gt=0,
        description="Maximum wait for an element or the spinner (s); legacy value 15 s.",
    )
    download_wait_s: float = Field(
        30.0,
        gt=0,
        description="Maximum wait for an export to appear in the download directory (s); "
        "legacy value 30 s.",
    )
    poll_interval_s: float = Field(
        0.5,
        gt=0,
        description="Polling interval of explicit waits and of the download watcher (s).",
    )
    device_settle_s: float = Field(
        3.0,
        ge=0,
        description=(
            "Fixed pause after clicking a device link (s), for DotVVM to render the device "
            "page; legacy value 3 s, [to be tuned] on the first real run."
        ),
    )
    tab_settle_s: float = Field(
        2.0,
        ge=0,
        description=(
            "Fixed pause after switching to the meteorological tab (s); legacy value 2 s, "
            "[to be tuned] on the first real run."
        ),
    )
    list_check_s: float = Field(
        5.0,
        gt=0,
        description=(
            "Maximum wait for the device list after going back from a device (s); when it "
            "does not appear, the client reloads the portal and opens the folder again."
        ),
    )


class PortalSettings(_Settings):
    """Everything the portal client needs except the credentials.

    Proposed configuration section: ``ingest.portal`` in ``config/sivin.yaml`` (wired by the
    integration workpackage).
    """

    portal_url: str = Field(
        "https://lemon.e-service.cz/",
        description="Start URL of the data provider's portal; it redirects to the login (URL).",
    )
    folder_name: str = Field(
        "SIVIN VUT",
        min_length=1,
        description="Text of the folder link that lists our devices (text).",
    )
    meteo_tab_name: str = Field(
        "Meteorologická data",
        min_length=1,
        description="Text of the device tab with the meteorological data and the export (text).",
    )
    export_section_name: str = Field(
        "Historie meteorologických dat",
        min_length=1,
        description="Heading text of the tab section whose Excel button is clicked (text).",
    )
    attempts_per_device: int = Field(
        2,
        ge=1,
        description=(
            "How often a device is tried before it is recorded as failed (count); the client "
            "returns to the device list before each retry."
        ),
    )
    min_export_size_bytes: int = Field(
        DEFAULT_MIN_EXPORT_SIZE_BYTES,
        ge=1,
        description="Smallest accepted export file (bytes); smaller files are incomplete.",
    )
    selectors: PortalSelectors = Field(
        default_factory=PortalSelectors, description="Locators of the portal's HTML elements."
    )
    timeouts: PortalTimeouts = Field(
        default_factory=PortalTimeouts, description="Waiting times (s)."
    )
    headless: bool = Field(True, description="Run the browser without a window (flag).")
    browser: str = Field(
        "chrome",
        min_length=1,
        description="Key of the registered WebDriverFactory that starts the browser (name).",
    )
    download_dir: Path = Field(
        Path("data/downloads"),
        description=(
            "Directory the browser saves exports into (path, relative to the project root; "
            "resolved by the caller with resolved_against before use)."
        ),
    )
    chrome_binary: Path | None = Field(
        None,
        description=(
            "Chrome/Chromium executable (path). When unset, the CHROME_BINARY environment "
            "variable is used, otherwise the browser found by chromedriver."
        ),
    )
    chromedriver_path: Path | None = Field(
        None,
        description=(
            "chromedriver executable (path). When unset: $CHROMEWEBDRIVER/chromedriver (set "
            "on GitHub-hosted runners), then chromedriver on PATH, then webdriver-manager "
            "downloads a matching one."
        ),
    )
    chrome_arguments: tuple[str, ...] = Field(
        ("--window-size=1920,1080",),
        description=(
            "Extra Chrome command-line arguments (list of flags). The window size keeps the "
            "export button inside the viewport in headless mode; add '--no-sandbox' only when "
            "running as root in a container."
        ),
    )
    partial_download_suffixes: tuple[str, ...] = Field(
        DEFAULT_PARTIAL_SUFFIXES,
        description="File name endings of unfinished browser downloads, ignored (suffixes).",
    )
    ignored_download_prefixes: tuple[str, ...] = Field(
        DEFAULT_IGNORED_PREFIXES,
        description=(
            "File name beginnings ignored by the download watcher (prefixes); Chrome on Linux "
            "writes hidden '.com.google.Chrome.*' temporary files."
        ),
    )

    def resolved_against(self, paths: ProjectPaths) -> Self:
        """Return a copy whose path settings are absolute.

        Parameters
        ----------
        paths : ProjectPaths
            The project root that relative paths refer to.

        Returns
        -------
        PortalSettings
            Copy with ``download_dir`` (and the optional executables) made absolute.
        """
        return self.model_copy(
            update={
                "download_dir": paths.resolve(self.download_dir),
                "chrome_binary": _resolve_optional(paths, self.chrome_binary),
                "chromedriver_path": _resolve_optional(paths, self.chromedriver_path),
            }
        )


def _resolve_optional(paths: ProjectPaths, path: Path | None) -> Path | None:
    return None if path is None else paths.resolve(path)
