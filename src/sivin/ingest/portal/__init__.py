"""Client of the data provider's portal (``lemon.e-service.cz``), WP-1.3.

This package re-exports only the objects that do not need Selenium (settings, credentials,
value objects, errors, the viewmodel parser and the download watcher), so loading the
configuration never requires the ``ingest`` extra. The browser-driving classes are imported
from their modules::

    from sivin.ingest.portal.client import PortalClient
    from sivin.ingest.portal.driver import ChromeDriverFactory, driver_factory_registry
    from sivin.ingest.portal.session import PortalSession

See ``docs/ingest.md``.
"""

from sivin.ingest.portal.clock import Clock, SystemClock
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.portal.errors import (
    DownloadTimeoutError,
    ExportButtonNotFoundError,
    MissingCredentialsError,
    PortalError,
    PortalLoginError,
    ViewModelError,
)
from sivin.ingest.portal.models import DeviceFailure, DownloadedExport, PortalDevice, SessionResult
from sivin.ingest.portal.settings import PortalSelectors, PortalSettings, PortalTimeouts
from sivin.ingest.portal.viewmodel import ViewModelParser
from sivin.ingest.portal.watcher import DirectorySnapshot, DownloadWatcher

__all__ = [
    "Clock",
    "DeviceFailure",
    "DirectorySnapshot",
    "DownloadTimeoutError",
    "DownloadWatcher",
    "DownloadedExport",
    "ExportButtonNotFoundError",
    "MissingCredentialsError",
    "PortalCredentials",
    "PortalDevice",
    "PortalError",
    "PortalLoginError",
    "PortalSelectors",
    "PortalSettings",
    "PortalTimeouts",
    "SessionResult",
    "SystemClock",
    "ViewModelError",
    "ViewModelParser",
]
