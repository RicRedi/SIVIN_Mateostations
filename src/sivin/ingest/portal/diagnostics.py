"""Diagnostics logged when an export download fails.

When :meth:`~sivin.ingest.portal.client.PortalClient.download_export` gives up waiting for the
file, the log must show whether the provider or our side failed. :class:`DownloadDiagnostics`
collects what can be seen at that moment (the download directory, Chrome's default download
directory, the browser state and any visible portal notice) into an immutable
:class:`DownloadReport`, whose :meth:`DownloadReport.format` is the logged text.

Collecting never raises: any error while collecting one item turns only that item into
``unavailable (<ExceptionName>)``, so the directory listings survive a dead browser. Nothing
secret is collected: no cookies, no page source, no input values, and the URL without
credentials, parameters, query string and fragment.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISDIR
from typing import Final
from urllib.parse import urlparse, urlunparse

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from sivin.ingest.portal.settings import PortalSettings
from sivin.ingest.portal.watcher import DownloadWatcher, FileKind

logger = logging.getLogger(__name__)

MAX_LISTED_FILES: Final = 10
"""Most directory entries listed per directory; the rest are counted as "… and N more"."""

MAX_NOTICES: Final = 3
"""Most visible portal notices reported."""

MAX_NOTICE_CANDIDATES: Final = 20
"""Most elements matching ``selectors.notification_css`` inspected (each costs WebDriver calls);
a broad selector on a large page is cut here before visibility is checked."""

MAX_TEXT_CHARS: Final = 200
"""Longest page title or notice text reported (characters); longer ones are cut with "…"."""

ELLIPSIS: Final = "…"
"""Marks a truncated text or list."""

JS_READY_STATE: Final = "return document.readyState;"
"""Script returning the page's loading state (``loading``, ``interactive`` or ``complete``)."""

CHROME_DEFAULT_SUBDIR: Final = "Downloads"
"""Chrome's default download directory relative to the user's home, used when its download
preferences are ignored."""

WHOLE_URL_SCHEMES: Final = frozenset({"about"})
"""Schemes of non-hierarchical URLs shown whole (``about:blank`` carries no data); of any other
non-hierarchical URL (``data:``, ``javascript:``) only the scheme is shown."""

_WHITESPACE: Final = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """One entry of a listed directory.

    Parameters
    ----------
    name : str
        File name (not a path).
    size_bytes : int
        Size (bytes); 0 for a directory.
    kind : FileKind
        How the download watcher treats it (:meth:`DownloadWatcher.classify`).
    is_directory : bool
        Whether it is a directory (``kind`` is then meaningless).
    """

    name: str
    size_bytes: int
    kind: FileKind = FileKind.COMPLETE
    is_directory: bool = False

    def format(self) -> str:
        """Return ``name (size B[, kind])``.

        Returns
        -------
        str
            One entry as logged.
        """
        if self.is_directory:
            return f"{self.name}/ (directory)"
        marker = "" if self.kind is FileKind.COMPLETE else f", {self.kind.value}"
        return f"{self.name} ({self.size_bytes} B{marker})"


@dataclass(frozen=True, slots=True)
class DirectoryListing:
    """The contents of one directory, or why they are not known.

    Parameters
    ----------
    path : pathlib.Path
        The directory.
    entries : tuple[DirectoryEntry, ...]
        Entries, newest first.
    status : str
        Empty when listed; otherwise ``absent``, ``not a directory``, ``same as the download
        directory`` or ``unavailable (<ExceptionName>)``.
    """

    path: Path
    entries: tuple[DirectoryEntry, ...] = ()
    status: str = ""

    def format(self) -> str:
        """Return the listing as one line, capped at :data:`MAX_LISTED_FILES` entries.

        Returns
        -------
        str
            ``<path>: <status>``, ``<path>: empty`` or ``<path>: N entries: a (1 B); …``.
        """
        if self.status:
            return f"{self.path}: {self.status}"
        if not self.entries:
            return f"{self.path}: empty"
        shown = "; ".join(entry.format() for entry in self.entries[:MAX_LISTED_FILES])
        hidden = len(self.entries) - MAX_LISTED_FILES
        more = f"; {ELLIPSIS} and {hidden} more" if hidden > 0 else ""
        count = len(self.entries)
        noun = "entry" if count == 1 else "entries"
        return f"{self.path}: {count} {noun}: {shown}{more}"


@dataclass(frozen=True, slots=True)
class BrowserState:
    """What the browser shows; every field is a value or ``unavailable (<ExceptionName>)``.

    Parameters
    ----------
    title : str
        Page title, truncated to :data:`MAX_TEXT_CHARS`.
    url : str
        Current URL without credentials, query string and fragment.
    ready_state : str
        ``document.readyState``.
    window_count : str
        Number of open windows and tabs (count).
    """

    title: str
    url: str
    ready_state: str
    window_count: str

    def format(self) -> str:
        """Return the state as one line.

        Returns
        -------
        str
            ``title …; url …; readyState …; windows …``.
        """
        return (
            f"title {self.title}; url {self.url}; readyState {self.ready_state}; "
            f"windows {self.window_count}"
        )


@dataclass(frozen=True, slots=True)
class PortalNotices:
    """Visible notice texts of the portal found with ``selectors.notification_css``.

    Parameters
    ----------
    texts : tuple[str, ...]
        At most :data:`MAX_NOTICES` texts, each at most :data:`MAX_TEXT_CHARS` characters.
    status : str
        Empty when searched; otherwise ``not searched (no selector)`` or
        ``unavailable (<ExceptionName>)``.
    hidden_count : int
        Further visible notices not reported (count).
    """

    texts: tuple[str, ...] = ()
    status: str = ""
    hidden_count: int = 0

    def format(self) -> str:
        """Return the notices as one line.

        Returns
        -------
        str
            ``none visible``, the status, or the quoted texts separated by ``|``.
        """
        if self.status:
            return self.status
        if not self.texts:
            return "none visible"
        more = f" | {ELLIPSIS} and {self.hidden_count} more" if self.hidden_count else ""
        return " | ".join(repr(text) for text in self.texts) + more


@dataclass(frozen=True, slots=True)
class DownloadReport:
    """Everything known about a failed download at the moment it failed.

    Parameters
    ----------
    download_dir : DirectoryListing
        The configured download directory (all entries, also unfinished and ignored ones).
    default_dir : DirectoryListing
        Chrome's default download directory; a file there means the download preferences
        were ignored.
    browser : BrowserState
        Title, URL, loading state and window count.
    notices : PortalNotices
        Visible error or notification texts of the portal.
    """

    download_dir: DirectoryListing
    default_dir: DirectoryListing
    browser: BrowserState
    notices: PortalNotices

    def format(self) -> str:
        """Return the report as four indented lines (no leading or trailing newline).

        Returns
        -------
        str
            The text logged after a failed download.
        """
        return "\n".join(
            (
                f"  download dir {self.download_dir.format()}",
                f"  Chrome default dir {self.default_dir.format()}",
                f"  browser: {self.browser.format()}",
                f"  portal notices: {self.notices.format()}",
            )
        )

    def __str__(self) -> str:
        return self.format()


class DownloadDiagnostics:
    """Collects a :class:`DownloadReport` after a failed download.

    Every item is collected on its own and any error becomes ``unavailable (<ExceptionName>)``
    for that item only. ``Exception`` is caught on purpose: besides ``WebDriverException`` and
    ``OSError``, a dead chromedriver raises urllib3's ``MaxRetryError`` (Selenium's transport),
    and diagnostics must never cost the directory listing or replace the download error.

    Parameters
    ----------
    settings : PortalSettings
        Provides ``selectors.notification_css``.
    watcher : DownloadWatcher
        The client's watcher: its directory is listed and its :meth:`DownloadWatcher.classify`
        marks the entries, so the report uses exactly the watcher's rules.
    default_download_dir : pathlib.Path, optional
        Chrome's default download directory; ``~/Downloads`` of the process user when
        omitted (resolved when collecting, so a missing home never raises).
    """

    def __init__(
        self,
        settings: PortalSettings,
        watcher: DownloadWatcher,
        default_download_dir: Path | None = None,
    ) -> None:
        self._settings = settings
        self._watcher = watcher
        self._default_download_dir = default_download_dir

    def collect(self, driver: WebDriver) -> DownloadReport:
        """Collect the report; never raises.

        Parameters
        ----------
        driver : selenium.webdriver.remote.webdriver.WebDriver
            The open (or dead) browser.

        Returns
        -------
        DownloadReport
            The report; unreadable items say ``unavailable (<ExceptionName>)``.
        """
        return DownloadReport(
            download_dir=self._listing(self._watcher.directory),
            default_dir=self._default_listing(),
            browser=BrowserState(
                title=_attempt(lambda: _truncate(str(driver.title))),
                url=_attempt(lambda: _truncate(public_url(str(driver.current_url)))),
                ready_state=_attempt(lambda: str(driver.execute_script(JS_READY_STATE))),
                window_count=_attempt(lambda: str(len(driver.window_handles))),
            ),
            notices=self._notices(driver),
        )

    def _default_listing(self) -> DirectoryListing:
        try:
            default_dir = self._default_download_dir or Path.home() / CHROME_DEFAULT_SUBDIR
        except Exception as error:  # see the class docstring
            return DirectoryListing(Path("~", CHROME_DEFAULT_SUBDIR), status=_unavailable(error))
        try:
            same = default_dir.resolve() == self._watcher.directory.resolve()
        except Exception as error:  # see the class docstring
            return DirectoryListing(default_dir, status=_unavailable(error))
        if same:
            return DirectoryListing(default_dir, status="same as the download directory")
        return self._listing(default_dir)

    def _listing(self, directory: Path) -> DirectoryListing:
        try:
            if not S_ISDIR(directory.stat().st_mode):
                return DirectoryListing(directory, status="not a directory")
            entries = [self._entry(path) for path in directory.iterdir()]
        except FileNotFoundError:
            return DirectoryListing(directory, status="absent")
        except Exception as error:  # see the class docstring
            return DirectoryListing(directory, status=_unavailable(error))
        found = sorted(
            (entry for entry in entries if entry is not None),
            key=lambda pair: (-pair[0], pair[1].name),
        )
        return DirectoryListing(directory, tuple(entry for _, entry in found))

    def _entry(self, path: Path) -> tuple[float, DirectoryEntry] | None:
        """Return ``(modification time in s, entry)``, or ``None`` when it vanished."""
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        if S_ISDIR(stat.st_mode):
            return stat.st_mtime, DirectoryEntry(path.name, 0, is_directory=True)
        kind = self._watcher.classify(path.name, stat.st_size)
        return stat.st_mtime, DirectoryEntry(path.name, stat.st_size, kind)

    def _notices(self, driver: WebDriver) -> PortalNotices:
        css = self._settings.selectors.notification_css
        if not css:
            return PortalNotices(status="not searched (no selector)")
        try:
            candidates = driver.find_elements(By.CSS_SELECTOR, css)[:MAX_NOTICE_CANDIDATES]
        except Exception as error:  # see the class docstring
            return PortalNotices(status=_unavailable(error))
        texts = [text for text in map(_visible_text, candidates) if text]
        return PortalNotices(tuple(texts[:MAX_NOTICES]), hidden_count=len(texts[MAX_NOTICES:]))


def _visible_text(element: WebElement) -> str:
    """Return the element's text when it is visible, else ``""``; a stale element gives ``""``."""
    try:
        return _truncate(element.text) if element.is_displayed() else ""
    except Exception as error:  # one stale element must not drop the other notices
        logger.debug("Skipping a notice element: %s", type(error).__name__)
        return ""


def public_url(url: str) -> str:
    """Return ``url`` without user info, ``;params``, query string and fragment.

    These parts may carry tokens. Of a non-hierarchical URL (``data:``, ``javascript:``) only
    the scheme is returned, unless the scheme is in :data:`WHOLE_URL_SCHEMES`.

    Parameters
    ----------
    url : str
        Any URL.

    Returns
    -------
    str
        Scheme, host, port and path only.

    Raises
    ------
    ValueError
        If the port is not a number.
    """
    parts = urlparse(url)
    if parts.scheme and not url[len(parts.scheme) + 1 :].startswith("//"):
        return url if parts.scheme in WHOLE_URL_SCHEMES else f"{parts.scheme}:"
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port is not None else host
    return urlunparse((parts.scheme, netloc, parts.path, "", "", ""))


def _truncate(text: str) -> str:
    """Collapse whitespace and cut to :data:`MAX_TEXT_CHARS` characters."""
    single_line = _WHITESPACE.sub(" ", text).strip()
    if len(single_line) <= MAX_TEXT_CHARS:
        return single_line
    return single_line[: MAX_TEXT_CHARS - len(ELLIPSIS)] + ELLIPSIS


def _attempt(read: Callable[[], str]) -> str:
    """Return ``read()``, or ``unavailable (<ExceptionName>)`` when it fails."""
    try:
        return read()
    except Exception as error:  # see DownloadDiagnostics: one item never costs the others
        return _unavailable(error)


def _unavailable(error: BaseException) -> str:
    return f"unavailable ({type(error).__name__})"
