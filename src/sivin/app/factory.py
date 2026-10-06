"""The composition root: builds every application service from the workspace's configuration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sivin.analytics.base import index_registry
from sivin.app.catalog import SensorCatalog, SensorCatalogLoader, SensorsCheck
from sivin.app.indices import (
    IndexContextFactory,
    IndexSelection,
    IndicesService,
    IndicesWriter,
)
from sivin.app.ingest import (
    DirectoryExports,
    ExportReader,
    IngestService,
    Quarantine,
    export_files,
)
from sivin.app.json_files import ErrorText, JsonFileWriter
from sivin.app.quality import EventsWriter, KnownSensors, QualityService
from sivin.app.run import Clock, ExportSource, RunRecorder, RunService
from sivin.app.site import SiteIndices, SiteInputsLoader, SiteService
from sivin.app.summary import (
    RunRecordFinder,
    RunSummaryService,
    SummarySettings,
    WarningCollector,
)
from sivin.app.workspace import Workspace
from sivin.config.sections import QuarantineMode
from sivin.ingest.parsers import base as parser_base
from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.validation import InputValidator
from sivin.quality.pipeline import QualityPipeline
from sivin.redaction import SecretRedactor
from sivin.registry.geojson import GeoJsonRegistryStore
from sivin.registry.offsite import OffSiteLogStore
from sivin.site.builder import SiteBuilder
from sivin.site.events import SiteEventMapping
from sivin.site.sensor_builder import DailyAggregation, SensorSiteBuilder, SummaryBuilder
from sivin.site.sensor_files import default_sensor_writers
from sivin.site.site_files import default_site_writers
from sivin.site.state import StateDirectory, StoreFingerprints
from sivin.storage.config import build_store
from sivin.storage.runlog import RUNS_DIR, RunLog
from sivin.storage.store import RAW_DIR, MeasurementStore

if TYPE_CHECKING:
    from sivin.app.fetch import DriverFactoryBuilder, FetchService
    from sivin.ingest.portal.settings import PortalSettings

logger = logging.getLogger(__name__)


FETCH_SKIPPED_DRY_RUN: Final = "fetch skipped in dry-run"
"""Note of ``sivin run --dry-run``: no login, no download."""

FETCH_SKIPPED: Final = "fetch skipped (--skip-fetch)"
"""Note of ``sivin run --skip-fetch``."""


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
    redactor : SecretRedactor, optional
        Hides the credentials in everything the services write (derived JSON files, the run
        record, error texts); built from the environment when omitted.
    """

    __slots__ = (
        "_catalog",
        "_clock",
        "_credentials",
        "_drivers",
        "_error_text",
        "_json",
        "_redactor",
        "_workspace",
    )

    def __init__(
        self,
        workspace: Workspace,
        drivers: DriverFactoryBuilder | None = None,
        credentials: Callable[[], PortalCredentials] | None = None,
        clock: Clock | None = None,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self._workspace = workspace
        self._redactor = redactor if redactor is not None else SecretRedactor.from_environment()
        self._json = JsonFileWriter(redactor=self._redactor)
        self._error_text = ErrorText(workspace.paths.root, self._redactor)
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

    @property
    def redactor(self) -> SecretRedactor:
        """The redactor of the credentials."""
        return self._redactor

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

    def ingest_service(
        self, dry_run: bool = False, quarantine_mode: QuarantineMode | None = None
    ) -> IngestService:
        """Return the ingest service.

        Parameters
        ----------
        dry_run : bool, optional
            Parse and validate only.
        quarantine_mode : QuarantineMode, optional
            Move or copy rejected files; ``ingest.quarantine_mode`` when omitted.

        Returns
        -------
        IngestService
            Parsers and validator from ``ingest``, the store and the quarantine.
        """
        ingest = self._workspace.config.ingest
        reader = ExportReader(
            parser_base.parser_registry, ingest.parsers, InputValidator(ingest.validation)
        )
        mode = quarantine_mode if quarantine_mode is not None else ingest.quarantine_mode
        quarantine = Quarantine(
            self._workspace.quarantine_dir,
            mode,
            self._clock,
            self._json,
            self._workspace.paths.root,
        )
        return IngestService(reader, self.store(), self.catalog().registry, quarantine, dry_run)

    def export_paths(self, files: Sequence[Path], from_dir: Path | None = None) -> list[Path]:
        """Return the files ``sivin ingest`` processes.

        Parameters
        ----------
        files : sequence of pathlib.Path
            Files named on the command line.
        from_dir : pathlib.Path, optional
            A directory whose exports (``ingest.file_patterns``) are added. Without files and
            without a directory, the download directory (``ingest.portal.download_dir``) is
            used.

        Returns
        -------
        list of pathlib.Path
            The given files, then the directory's exports sorted by name.
        """
        paths = list(files)
        directory = from_dir if from_dir is not None or paths else self._workspace.download_dir
        if directory is not None and directory.is_dir():
            paths += export_files(directory, self._workspace.config.ingest.file_patterns)
        return paths

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
        store = self.store()
        registry = self.catalog().registry
        return QualityService(
            store,
            pipeline,
            registry,
            EventsWriter(self._workspace.events_dir, self._json, KnownSensors(registry, store)),
            self._clock,
            dry_run,
            self._error_text,
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
            IndicesWriter(
                self._workspace.indices_dir,
                self._json,
                KnownSensors(self.catalog().registry, self.store()),
                index_registry.ids(),
            ),
            self._clock,
            dry_run=dry_run,
            error_text=self._error_text,
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
        return FetchService(
            self.portal_settings(headed, download_dir), self._credentials, drivers, self._redactor
        )

    def site_service(self) -> SiteService:
        """Return the site-data service (``sivin build-site``).

        Returns
        -------
        SiteService
            Reads every published sensor through quality control, computes the indices with a
            dry-run indices service (no derived file is written) and writes
            ``<paths.site_dir>/data``.
        """
        config = self._workspace.config
        time, analytics = config.time, config.analytics
        sensor_builder = SensorSiteBuilder(
            DailyAggregation(
                time.display_timezone,
                time.expected_interval_s,
                analytics.exclude_mask,
                analytics.auxiliary_exclude_mask,
            ),
            SummaryBuilder(time.display_timezone, analytics.exclude_mask),
            default_sensor_writers(SiteEventMapping(config.site.events), self._redactor),
        )
        builder = SiteBuilder(
            self.quality_service(dry_run=True),
            SiteIndices(self.indices_service(dry_run=True), index_registry),
            sensor_builder,
            default_site_writers(config.site.stale_after_s, redactor=self._redactor),
            StoreFingerprints(self._workspace.data_dir / RAW_DIR),
            StateDirectory(self._workspace.site_state_file.parent, self._workspace.site_data_dir),
            self._clock,
            self._error_text,
        )
        inputs = SiteInputsLoader(
            self.store(),
            self.catalog().registry,
            self._workspace.sensors_file,
            self._workspace.offsite_log_file,
            config,
        )
        return SiteService(builder, inputs, self._workspace.site_data_dir)

    def run_service(
        self,
        dry_run: bool = False,
        skip_fetch: bool = False,
        headed: bool = False,
        skip_site: bool = False,
    ) -> RunService:
        """Return the service of ``sivin run``.

        Parameters
        ----------
        dry_run : bool, optional
            Write nothing. Implies ``skip_fetch``: a dry run never logs in or downloads
            (WP-1.7 review); the files already in the download directory are validated.
        skip_fetch : bool, optional
            Do not use the portal; ingest the files already in the download directory.
        headed : bool, optional
            Show the browser window.
        skip_site : bool, optional
            Do not build the site data (the step is also skipped in a dry run).

        Returns
        -------
        RunService
            Fetch (or directory) → ingest → QC → indices → site data → run log.
        """
        source: ExportSource
        note = None
        if dry_run or skip_fetch:
            note = FETCH_SKIPPED_DRY_RUN if dry_run else FETCH_SKIPPED
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
            note,
            None if dry_run or skip_site else self.site_service(),
        )

    def run_recorder(self) -> RunRecorder:
        """Return the run-log writer of the store.

        Returns
        -------
        RunRecorder
            Appends to ``<paths.data_dir>/runs/<YYYY-MM-DD>.jsonl``.
        """
        return RunRecorder(RunLog(self._workspace.data_dir), self._error_text)

    def summary_service(self, settings: SummarySettings | None = None) -> RunSummaryService:
        """Return the service that summarises a run (``sivin report``).

        Parameters
        ----------
        settings : SummarySettings, optional
            Limits of the rendering; the defaults when omitted.

        Returns
        -------
        RunSummaryService
            Reads ``<paths.data_dir>/runs`` and ``<paths.derived_dir>/events``.
        """
        data_dir = self._workspace.data_dir
        return RunSummaryService(
            RunRecordFinder(RunLog(data_dir), data_dir / RUNS_DIR),
            WarningCollector(self._workspace.events_dir),
            self._workspace.config.time.display_timezone,
            settings,
            self._redactor.redact,
        )
