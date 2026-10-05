"""Exceptions raised by the portal client.

All of them derive from :class:`PortalError`, so a caller can tell a portal problem from a
programming error. Selenium's own exceptions (``WebDriverException`` and its subclasses) are not
wrapped; :class:`~sivin.ingest.portal.session.PortalSession` handles both kinds per device.
"""

from __future__ import annotations


class PortalError(Exception):
    """Base class of every error raised by :mod:`sivin.ingest.portal`."""


class MissingCredentialsError(PortalError):
    """Raised when ``SIVIN_USER`` or ``SIVIN_PASSWORD`` is not set in the environment."""


class PortalLoginError(PortalError):
    """Raised when the login form is missing or the portal does not accept the login."""


class ViewModelError(PortalError):
    """Raised when the DotVVM viewmodel cannot be read or has an unexpected structure."""


class ExportButtonNotFoundError(PortalError):
    """Raised when no visible Excel export button appears on the meteorological data tab."""


class DownloadTimeoutError(PortalError):
    """Raised when no new, complete file appears in the download directory in time."""


class DownloadIncompleteError(PortalError):
    """Raised when the only new file is smaller than the minimum export size (e.g. empty)."""
