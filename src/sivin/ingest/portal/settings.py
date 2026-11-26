"""Settings of the portal client as frozen pydantic models (MIGRATION_PLAN §1.3).

The values default to what the legacy ``chrome_driver.py`` used against the portal. Selectors
are grouped in :class:`PortalSelectors`, so a change of the portal's HTML is fixed in the
configuration, not in the code. Credentials are not settings; see
:class:`~sivin.ingest.portal.credentials.PortalCredentials`.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Final, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

RELATIVE_XPATH_PREFIX: Final = "./"
"""Beginning of an XPath relative to the meteorological data card (``.//table``)."""

PAGING_TEXT_GROUPS: Final = frozenset({"shown", "total", "page_size"})
"""Named groups the paging text pattern must define."""

DEFAULT_TABLE_COLUMNS: Final = {
    "Datum a čas": "Datum a čas",
    "Teplota": "Teplota (°C)",
    "Vlhkost": "Vlhkost (%)",
    "Srážky": "Srážky (mm)",
    "Celkové srážky": "Celkové srážky (mm)",
    "Nabití baterie": "Nabití baterie (V)",
}
"""Table header text → column header of the portal's CSV export, in the export's column order.

Table headers as on the saved device page (2026-11, WP-1.10); export headers as in the real
CSV export (MIGRATION_PLAN §0.6.1)."""

DEFAULT_TABLE_TIMEZONE: Final = "Europe/Prague"
"""Zone of the table's wall-clock times; set from ``time.source_timezone`` by the configuration."""


class PortalSource(StrEnum):
    """Ways of getting a device's data from the portal, tried in the configured order."""

    EXPORT = "export"
    """Click the Excel export button and wait for the downloaded file (WP-1.3)."""
    TABLE = "table"
    """Read the table *Historie meteorologických dat* of the device page (WP-1.10)."""


DEFAULT_SOURCES: Final = (PortalSource.EXPORT, PortalSource.TABLE)
"""Export first, the table as the fallback (owner decision 2026-11-26)."""


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
        120.0,
        gt=0,
        description="Maximum wait for an export to appear in the download directory (s); "
        "legacy value 30 s, raised to 120 s after the headless runs on GitHub Actions timed out "
        "at 30 s (WP-1.3.2).",
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


class PortalTableSettings(_Settings):
    """Reading the table *Historie meteorologických dat* as the fallback source (WP-1.10).

    The locators were taken from a saved device page (2026-11) and are **not verified in a
    live browser** [to be verified]. Relative XPaths start with ``./`` and are evaluated
    inside the card found by ``card_xpath_template``.
    """

    card_xpath_template: str = Field(
        "//*[contains(normalize-space(text()), {text})]"
        "/ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]",
        description=(
            "XPath of the card whose heading contains {text} (export_section_name): the "
            "heading's nearest ancestor with the CSS class 'card' (XPath template)."
        ),
    )
    table_xpath: str = Field(
        ".//table[.//tbody]",
        description=(
            "XPath of the data table inside the card; DotVVM renders it only while it has rows "
            "(relative XPath)."
        ),
    )
    paging_xpath: str = Field(
        ".//*[contains(@data-bind, 'RecordsPerPage')]",
        description=(
            "XPath of the paging control inside the card; its text holds 'Zobrazeno <shown> z "
            "<total> (<page size>)' (relative XPath)."
        ),
    )
    next_page_xpath: str = Field(
        ".//button[.//i[contains(@class, 'fa-step-forward')]]",
        description=(
            "XPath of the button to the next (older) page inside the card; disabled on the last "
            "page (relative XPath)."
        ),
    )
    page_size_xpath: str = Field(
        ".//button[.//i[contains(@class, 'fa-chevron-down')]]",
        description=(
            "XPath of the button that changes the page size inside the card ('Zvětšit počet "
            "zobrazených záznamů'); assumed to step through the portal's page sizes "
            "(10, 15, 20, 30, 50, 100, 500, 1000, 5000), [to be verified] (relative XPath)."
        ),
    )
    paging_text_pattern: str = Field(
        r"Zobrazeno\s+(?P<shown>[\d\s]+?)\s+z\s+(?P<total>[\d\s]+?)\s*\((?P<page_size>[\d\s]+)\)",
        description=(
            "Regular expression searched in the text of the paging control; groups 'shown', "
            "'total' and 'page_size' (rows; spaces inside a number are removed) (regex)."
        ),
    )
    columns: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_TABLE_COLUMNS),
        description=(
            "Table header text → column header written into the CSV file, in the export's "
            "column order; the first entry is the timestamp column, other table columns are "
            "ignored (mapping of texts)."
        ),
    )
    timestamp_format: str = Field(
        "%d.%m.%Y %H:%M:%S",
        min_length=1,
        description=(
            "strptime format of the table's timestamps, e.g. '18.11.2026 9:53:11' (local "
            "wall-clock time) (format)."
        ),
    )
    source_timezone: str = Field(
        DEFAULT_TABLE_TIMEZONE,
        description=(
            "IANA zone of the table's wall-clock times, used to compare them with the last "
            "stored UTC time and to name the file; set from time.source_timezone (zone)."
        ),
    )
    incremental_page_size: int = Field(
        500,
        ge=1,
        description=(
            "Page size used when the store already has data of the sensor (rows); 500 rows are "
            "about 10 days at the ~1800 s step. Owner decision 2026-11-26."
        ),
    )
    full_history_page_size: int = Field(
        5000,
        ge=1,
        description=(
            "Page size used when the store has nothing of the sensor and the whole history is "
            "read (rows); the largest size the portal offers."
        ),
    )
    max_page_size_clicks: int = Field(
        9,
        ge=0,
        description=(
            "Most clicks on the page-size button to reach the wanted page size (count); the "
            "portal offers 9 sizes. When the size is not reached, the shown size is used."
        ),
    )
    max_pages: int = Field(
        100,
        ge=1,
        description=(
            "Most pages read per device (count), a guard against a paging control that never "
            "reports the last page."
        ),
    )
    rows_wait_s: float = Field(
        30.0,
        gt=0,
        description=(
            "Maximum wait for the first table rows after the tab opens (s); DotVVM loads them "
            "with a postback. Project default, [to be tuned] on the first real run."
        ),
    )
    file_label: str = Field(
        "table",
        pattern=r"^[^\W\d_][\w-]*$",
        description=(
            "Label in the name of the written file, 'MeteoData_<device> (<label>)_<YYYYMMDD>_"
            "<HHMMSS>.csv', marking that the data came from the table (word)."
        ),
    )

    @field_validator("card_xpath_template")
    @classmethod
    def _has_placeholder(cls, value: str) -> str:
        if TEXT_PLACEHOLDER not in value:
            raise ValueError(f"an XPath template must contain {TEXT_PLACEHOLDER}")
        return value

    @field_validator("table_xpath", "paging_xpath", "next_page_xpath", "page_size_xpath")
    @classmethod
    def _is_relative(cls, value: str) -> str:
        if not value.startswith(RELATIVE_XPATH_PREFIX):
            raise ValueError(f"a relative XPath must start with {RELATIVE_XPATH_PREFIX!r}")
        return value

    @field_validator("paging_text_pattern")
    @classmethod
    def _has_groups(cls, value: str) -> str:
        try:
            groups = set(re.compile(value).groupindex)
        except re.error as error:
            raise ValueError(f"not a regular expression: {error}") from error
        missing = PAGING_TEXT_GROUPS - groups
        if missing:
            raise ValueError(f"the pattern lacks the named groups {sorted(missing)}")
        return value

    @field_validator("columns")
    @classmethod
    def _not_empty(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("at least the timestamp column is needed")
        return value

    @field_validator("source_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA time zone {value!r}") from error
        return value

    def within_card(self, card_xpath: str, relative_xpath: str) -> str:
        """Return an absolute XPath of an element inside the card.

        Parameters
        ----------
        card_xpath : str
            Absolute XPath of the card.
        relative_xpath : str
            One of the relative XPaths of these settings (``./…``).

        Returns
        -------
        str
            ``(<card>)[1]/…``.
        """
        return f"({card_xpath})[1]{relative_xpath.removeprefix('.')}"


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
    sources: tuple[PortalSource, ...] = Field(
        DEFAULT_SOURCES,
        min_length=1,
        description=(
            "How a device's data are fetched, tried in this order until one succeeds (list of "
            "'export', 'table'): [export, table] = export, the table as the fallback; [table] "
            "= table only; [export] = export only."
        ),
    )
    table: PortalTableSettings = Field(
        default_factory=PortalTableSettings,
        description="Reading the device page's data table, the fallback source (WP-1.10).",
    )

    @model_validator(mode="after")
    def _unique_sources(self) -> Self:
        if len(set(self.sources)) != len(self.sources):
            raise ValueError(f"sources must not repeat a source, got {list(self.sources)}")
        return self

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
