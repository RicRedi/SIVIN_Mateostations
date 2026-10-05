"""The composition root: builds every application service from the workspace's configuration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sivin.analytics.base import index_registry
from sivin.app.catalog import SensorCatalog, SensorCatalogLoader, SensorsCheck
from sivin.app.indices import IndexContextFactory, IndexSelection, IndicesService
from sivin.app.ingest import DirectoryExports, ExportReader, IngestService, Quarantine
from sivin.app.quality import EventsWriter, QualityService
from sivin.app.run import Clock, ExportSource, RunRecorder, RunService
from sivin.app.workspace import Workspace
from sivin.ingest.parsers import base as parser_base
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.validation import InputValidator
from sivin.quality.pipeline import QualityPipeline
from sivin.registry.geojson import GeoJsonRegistryStore
from sivin.registry.offsite import OffSiteLogStore
from sivin.storage.config import build_store
from sivin.storage.runlog import RunLog
from sivin.storage.store import MeasurementStore

if TYPE_CHECKING:
    from sivin.app.fetch import DriverFactoryBuilder, FetchService
    from sivin.ingest.portal.settings import PortalSettings

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Return the current time in UTC (the default clock).

    Returns
    -------
    datetime.datetime
        Timezone-aware UTC time.
    """
    return datetime.now(UTC)


class ServiceFactory:
    """Build the application services of one workspace.

    The registry and the off-site log are loaded once, on first use; an invalid file raises
    :class:`~sivin.app.outcome.SetupError` then.

    Parameters
    ----------
    workspace : Workspace
        Project root and resolved configuration.
    drivers : DriverFactoryBuilder, optional
        Builds the browser factory for the portal; the browser registry
        (``ingest.portal.browser``) when omitted. Tests inject a fake browser here.
    credentials : callable, optional
        Returns the portal credentials; read from the environment when omitted.
    clock : Clock, optional
        Current time; UTC system time when omitted.
    """

    __slots__ = ("_catalog", "_clock", "_credentials", "_drivers", "_workspace")

    def __init__(
        self,
        workspace: Workspace,
        drivers: DriverFactoryBuilder | None = None,
        credentials: Callable[[], PortalCredentials] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._workspace = workspace
        self._drivers = drivers
        self._credentials = credentials if credentials is not None else PortalCredentials.from_env
        self._clock = clock if clock is not None else utc_now
        self._catalog: SensorCatalog | None = None

    @property
    def workspace(self) -> Workspace:
        """The project the services work on."""
        return self._workspace

    @property
    def clock(self) -> Clock:
        """The clock of the services."""
        return self._clock

    def catalog_loader(self) -> SensorCatalogLoader:
        """Return the loader of the registry and the off-site log.

        Returns
        -------
        SensorCatalogLoader
            Configured with ``paths.sensors_file``, ``registry`` and ``offsite_log``.
        """
        config = self._workspace.config
        return SensorCatalogLoader(
            GeoJsonRegistryStore(config.registry),
            self._workspace.sensors_file,
            OffSiteLogStore(),
            self._workspace.offsite_log_file,
            config.offsite_log.timezone,
        )

    def catalog(self) -> SensorCatalog:
        """Return the registry and the off-site log (loaded once).

        Returns
        -------
        SensorCatalog
            The validated files.
        """
        if self._catalog is None:
            self._catalog = self.catalog_loader().load()
        return self._catalog

    def sensors_check(self) -> SensorsCheck:
        """Return the ``sensors check`` service.

        Returns
        -------
        SensorsCheck
            Validates the registry and the off-site log.
        """
        return SensorsCheck(self.catalog_loader())

    def store(self) -> MeasurementStore:
        """Return the measurement store (``paths.data_dir``, ``storage``).

        Returns
        -------
        MeasurementStore
            The store.
        """
        return build_store(self._workspace.data_dir, self._workspace.config.storage)

    def ingest_service(self, dry_run: bool = False) -> IngestService:
        """Return the ingest service.

        Parameters
        ----------
        dry_run : bool, optional
            Parse and validate only.

        Returns
        -------
        IngestService
            Parsers and validator from ``ingest``, the store and the quarantine.
        """
        ingest = self._workspace.config.ingest
        reader = ExportReader(
            parser_base.parser_registry, ingest.parsers, InputValidator(ingest.validation)
        )
        quarantine = Quarantine(self._workspace.quarantine_dir, ingest.quarantine_mode)
        return IngestService(reader, self.store(), self.catalog().registry, quarantine, dry_run)

    def quality_service(self, dry_run: bool = False) -> QualityService:
        """Return the QC service.

        Parameters
        ----------
        dry_run : bool, optional
            Write no events file.

        Returns
        -------
        QualityService
            Pipeline from ``quality`` with the off-site log.
        """
        pipeline = QualityPipeline.from_settings(
            self._workspace.config.quality, off_site_log=self.catalog().offsite_log
        )
        return QualityService(
            self.store(),
            pipeline,
            self.catalog().registry,
            EventsWriter(self._workspace.events_dir),
            dry_run,
        )

    def indices_service(self, dry_run: bool = False) -> IndicesService:
        """Return the indices service.

        Parameters
        ----------
        dry_run : bool, optional
            Write no indices file.

        Returns
        -------
        IndicesService
            Indices from ``analytics.indices``, contexts from ``time`` and ``analytics``.
        """
        config = self._workspace.config
        return IndicesService(
            self.quality_service(dry_run=True),
            IndexContextFactory(config.time, config.analytics, self.catalog().registry),
            IndexSelection(index_registry, config.analytics.indices),
            self._workspace.indices_dir,
            dry_run=dry_run,
        )

    def portal_settings(
        self, headed: bool = False, download_dir: Path | None = None
    ) -> PortalSettings:
        """Return the portal settings with absolute paths and the command-line overrides.

        Parameters
        ----------
        headed : bool, optional
            Show the browser window (``headless = False``).
        download_dir : pathlib.Path, optional
            Download directory instead of ``ingest.portal.download_dir``.

        Returns
        -------
        PortalSettings
            Settings resolved against the project root.
        """
        settings = self._workspace.config.ingest.portal.resolved_against(self._workspace.paths)
        changes: dict[str, object] = {}
        if headed:
            changes["headless"] = False
        if download_dir is not None:
            changes["download_dir"] = download_dir.resolve()
        return settings.model_copy(update=changes)

    def fetch_service(self, headed: bool = False, download_dir: Path | None = None) -> FetchService:
        """Return the portal download service.

        Imports Selenium (the ``ingest`` extra) only here, so the other commands work
        without it.

        Parameters
        ----------
        headed : bool, optional
            Show the browser window.
        download_dir : pathlib.Path, optional
            Download directory instead of the configured one.

        Returns
        -------
        FetchService
            The service.
        """
        from sivin.app.fetch import FetchService
        from sivin.ingest.portal.driver import driver_factory_registry

        drivers = self._drivers if self._drivers is not None else driver_factory_registry.create
        return FetchService(self.portal_settings(headed, download_dir), self._credentials, drivers)

    def run_service(
        self, dry_run: bool = False, skip_fetch: bool = False, headed: bool = False
    ) -> RunService:
        """Return the service of ``sivin run``.

        Parameters
        ----------
        dry_run : bool, optional
            Write nothing.
        skip_fetch : bool, optional
            Do not use the portal; ingest the files already in the download directory.
        headed : bool, optional
            Show the browser window.

        Returns
        -------
        RunService
            Fetch (or directory) → ingest → QC → indices → run log.
        """
        source: ExportSource
        if skip_fetch:
            source = DirectoryExports(
                self._workspace.download_dir, self._workspace.config.ingest.file_patterns
            )
        else:
            from sivin.app.fetch import PortalExports

            source = PortalExports(self.fetch_service(headed))
        return RunService(
            source,
            self.ingest_service(dry_run),
            self.quality_service(dry_run),
            self.indices_service(dry_run),
            self.run_recorder(),
            self._clock,
            dry_run,
        )

    def run_recorder(self) -> RunRecorder:
        """Return the run-log writer of the store.

        Returns
        -------
        RunRecorder
            Appends to ``<paths.data_dir>/runs/<YYYY-MM-DD>.jsonl``.
        """
        return RunRecorder(RunLog(self._workspace.data_dir))
