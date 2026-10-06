"""Diagnostics logged when an export download fails.

When :meth:`~sivin.ingest.portal.client.PortalClient.download_export` gives up waiting for the
file, the log must show whether the provider or our side failed. :class:`DownloadDiagnostics`
collects what can be seen at that moment (the download directory, Chrome's default download
directory, the browser state and any visible portal notice) into an immutable
:class:`DownloadReport`, whose :meth:`DownloadReport.format` is the logged text.

Collecting never raises: a browser or file system error while collecting one item turns that
item into ``unavailable (<ExceptionName>)``. Nothing secret is collected: no cookies, no page
source, no input values, and the URL without credentials, query string and fragment.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from stat import S_ISDIR
from typing import Final
from urllib.parse import urlsplit, urlunsplit

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from sivin.ingest.portal.settings import PortalSettings

logger = logging.getLogger(__name__)

MAX_LISTED_FILES: Final = 10
"""Most directory entries listed per directory; the rest are counted as "… and N more"."""

MAX_NOTICES: Final = 3
"""Most visible portal notices reported."""

MAX_TEXT_CHARS: Final = 200
"""Longest page title or notice text reported (characters); longer ones are cut with "…"."""

ELLIPSIS: Final = "…"
"""Marks a truncated text or list."""

JS_READY_STATE: Final = "return document.readyState;"
"""Script returning the page's loading state (``loading``, ``interactive`` or ``complete``)."""

CHROME_DEFAULT_SUBDIR: Final = "Downloads"
"""Chrome's default download directory relative to the user's home, used when its download
preferences are ignored."""

DIAGNOSTIC_ERRORS: Final = (WebDriverException, OSError, RuntimeError, ValueError)
"""Errors turned into "unavailable": browser and file system failures, ``Path.home()`` without a
home directory (``RuntimeError``) and an unparsable URL (``ValueError``)."""

_WHITESPACE: Final = re.compile(r"\s+")


class EntryKind(Enum):
    """How the download watcher treats a directory entry."""

    COMPLETE = ""
    UNFINISHED = "unfinished"
    IGNORED = "ignored"
    DIRECTORY = "directory"


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """One entry of a listed directory.

    Parameters
    ----------
    name : str
        File name (not a path).
    size_bytes : int
        Size (bytes); 0 for a directory.
    kind : EntryKind
        Whether the watcher would consider, wait for or ignore it.
    """

    name: str
    size_bytes: int
    kind: EntryKind = EntryKind.COMPLETE

    def format(self) -> str:
        """Return ``name (size B[, kind])``.

        Returns
        -------
        str
            One entry as logged.
        """
        if self.kind is EntryKind.DIRECTORY:
            return f"{self.name}/ (directory)"
        marker = f", {self.kind.value}" if self.kind.value else ""
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
        Empty when listed; otherwise ``absent``, ``same as the download directory`` or
        ``unavailable (<ExceptionName>)``.
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

    Parameters
    ----------
    settings : PortalSettings
        Partial-download suffixes, ignored prefixes and ``selectors.notification_css``.
    directory : pathlib.Path
        The watched download directory.
    default_download_dir : pathlib.Path, optional
        Chrome's default download directory; ``~/Downloads`` of the process user when
        omitted (resolved when collecting, so a missing home never raises).
    """

    def __init__(
        self,
        settings: PortalSettings,
        directory: Path,
        default_download_dir: Path | None = None,
    ) -> None:
        self._settings = settings
        self._directory = directory
        self._default_download_dir = default_download_dir

    def collect(self, driver: WebDriver) -> DownloadReport:
        """Collect the report; never raises for browser or file system errors.

        Parameters
        ----------
        driver : selenium.webdriver.remote.webdriver.WebDriver
            The open browser.

        Returns
        -------
        DownloadReport
            The report; unreadable items say ``unavailable (<ExceptionName>)``.
        """
        return DownloadReport(
            download_dir=self._listing(self._directory),
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
        except DIAGNOSTIC_ERRORS as error:
            return DirectoryListing(Path("~", CHROME_DEFAULT_SUBDIR), status=_unavailable(error))
        try:
            same = default_dir.resolve() == self._directory.resolve()
        except DIAGNOSTIC_ERRORS as error:
            return DirectoryListing(default_dir, status=_unavailable(error))
        if same:
            return DirectoryListing(default_dir, status="same as the download directory")
        return self._listing(default_dir)

    def _listing(self, directory: Path) -> DirectoryListing:
        try:
            if not directory.is_dir():
                return DirectoryListing(directory, status="absent")
            entries = [self._entry(path) for path in directory.iterdir()]
        except DIAGNOSTIC_ERRORS as error:
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
            return stat.st_mtime, DirectoryEntry(path.name, 0, EntryKind.DIRECTORY)
        return stat.st_mtime, DirectoryEntry(path.name, stat.st_size, self._kind(path.name))

    def _kind(self, name: str) -> EntryKind:
        if name.endswith(self._settings.partial_download_suffixes):
            return EntryKind.UNFINISHED
        if name.startswith(self._settings.ignored_download_prefixes):
            return EntryKind.IGNORED
        return EntryKind.COMPLETE

    def _notices(self, driver: WebDriver) -> PortalNotices:
        css = self._settings.selectors.notification_css
        if not css:
            return PortalNotices(status="not searched (no selector)")
        try:
            texts = [
                _truncate(element.text)
                for element in driver.find_elements(By.CSS_SELECTOR, css)
                if element.is_displayed() and element.text.strip()
            ]
        except DIAGNOSTIC_ERRORS as error:
            return PortalNotices(status=_unavailable(error))
        return PortalNotices(tuple(texts[:MAX_NOTICES]), hidden_count=len(texts[MAX_NOTICES:]))


def public_url(url: str) -> str:
    """Return ``url`` without user info, query string and fragment (they may carry tokens).

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
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port is not None else host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


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
    except DIAGNOSTIC_ERRORS as error:
        return _unavailable(error)


def _unavailable(error: BaseException) -> str:
    return f"unavailable ({type(error).__name__})"
