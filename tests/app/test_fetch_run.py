"""FetchService and RunService with the fake portal (SYNTHETIC exports, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.app.conftest import RUN_TIME
from tests.app.fake_portal import credentials, drivers
from tests.app.project import OUTDOOR_SENSOR, Project, write_synthetic_export

from sivin.app.factory import ServiceFactory, utc_now
from sivin.app.fetch import FetchReport, FetchService, PortalExports
from sivin.app.outcome import Outcome, SetupError
from sivin.app.workspace import Workspace
from sivin.core.ids import SensorId
from sivin.ingest.portal.errors import MissingCredentialsError
from sivin.ingest.portal.models import DeviceFailure, PortalDevice, SessionResult
from sivin.redaction import SecretRedactor
from sivin.storage.runlog import RunLog

OUTDOOR = SensorId(OUTDOOR_SENSOR)


def portal_factory(project: Project, behaviours: dict[str, str] | None = None) -> ServiceFactory:
    return ServiceFactory(
        Workspace.open(start=project.root),
        drivers=drivers(behaviours),
        credentials=credentials,
        clock=lambda: RUN_TIME,
    )


class TestFetch:
    def test_downloads_the_selected_sensor(self, project: Project) -> None:
        service = portal_factory(project).fetch_service()
        report = service.fetch([OUTDOOR])
        assert report.outcome is Outcome.OK
        assert [path.name for path in report.files] == [
            "MeteoData_8615620 77678271 (VUT)_20260605_060001.csv"
        ]
        assert report.files[0].parent == project.root / "data" / "downloads"

    def test_failed_device_is_reported(self, project: Project) -> None:
        behaviours = {"8615621 77678272": "no_button"}
        report = portal_factory(project, behaviours).fetch_service().fetch()
        assert report.outcome is Outcome.PARTIAL_FAILURE
        assert len(report.files) == 2
        assert report.failures[0].startswith("fetch 8615621 77678272: ")

    def test_overrides(self, project: Project, tmp_path: Path) -> None:
        factory = portal_factory(project)
        settings = factory.portal_settings(headed=True, download_dir=tmp_path / "dl")
        assert settings.headless is False
        assert settings.download_dir == (tmp_path / "dl").resolve()
        default = factory.portal_settings()
        assert default.headless is True
        assert default.download_dir == project.root / "data" / "downloads"
        assert (
            factory.fetch_service(download_dir=tmp_path / "dl").settings.download_dir
            == (tmp_path / "dl").resolve()
        )

    def test_missing_credentials(self, project: Project) -> None:
        def missing() -> None:
            raise MissingCredentialsError("Set SIVIN_USER and SIVIN_PASSWORD.")

        service = FetchService(
            portal_factory(project).portal_settings(),
            missing,
            drivers(),  # type: ignore[arg-type]
        )
        with pytest.raises(SetupError, match="SIVIN_USER"):
            service.fetch()

    def test_failed_login_is_a_setup_error(self, project: Project) -> None:
        from sivin.ingest.portal.credentials import PortalCredentials, Secret

        def wrong() -> PortalCredentials:
            return PortalCredentials("synthetic-user", Secret("not-the-password-77"))

        service = FetchService(portal_factory(project).portal_settings(), wrong, drivers())
        with pytest.raises(SetupError, match="Portal session failed") as caught:
            service.fetch()
        assert "not-the-password-77" not in str(caught.value)

    def test_portal_export_source(self, project: Project) -> None:
        files, failures = PortalExports(portal_factory(project).fetch_service()).exports([OUTDOOR])
        assert len(files) == 1
        assert failures == ()

    def test_default_drivers_come_from_the_browser_registry(self, project: Project) -> None:
        service = ServiceFactory(Workspace.open(start=project.root)).fetch_service()
        assert service.settings.browser == "chrome"


class TestRun:
    def test_run_end_to_end_with_the_fake_portal(self, project: Project) -> None:
        report = portal_factory(project).run_service().run(2026, [OUTDOOR])
        assert report.outcome is Outcome.OK, (report.record.failures, report.fetch_failures)
        assert report.ingest.appends[OUTDOOR].new_rows == 94  # 2 days of 1830 s
        assert report.quality.sensors[OUTDOOR].events_file is not None
        assert report.indices.file == project.root / "data/derived/indices/2026.json"
        indices = json.loads(report.indices.file.read_text(encoding="utf-8"))
        assert set(indices["sensors"]) == {OUTDOOR_SENSOR}
        (record,) = RunLog(project.root / "data").read(RUN_TIME.date())
        assert record == report.record
        assert record.files == ("MeteoData_8615620 77678271 (VUT)_20260605_060001.csv",)

    def test_portal_failure_keeps_the_stored_data(self, project: Project) -> None:
        def missing() -> None:
            raise MissingCredentialsError("Set SIVIN_USER and SIVIN_PASSWORD.")

        factory = ServiceFactory(
            Workspace.open(start=project.root),
            drivers=drivers(),
            credentials=missing,  # type: ignore[arg-type]
            clock=lambda: RUN_TIME,
        )
        factory.ingest_service().ingest([write_synthetic_export(project.downloads, days=1)])
        report = factory.run_service().run(2026)
        assert report.outcome is Outcome.DATA_SOURCE_UNAVAILABLE
        assert report.source_unavailable
        assert report.fetch_failures[0].startswith("fetch: Set SIVIN_USER")
        assert report.record.failures[0] == report.fetch_failures[0]
        assert report.quality.sensors[OUTDOOR].result is not None
        assert OUTDOOR in report.indices.results

    def test_skip_fetch_and_dry_run(self, project: Project, factory: ServiceFactory) -> None:
        write_synthetic_export(project.downloads, days=1)
        report = factory.run_service(dry_run=True, skip_fetch=True).run(2026)
        assert report.dry_run
        assert report.outcome is Outcome.OK
        assert report.ingest.files[0].rows == {OUTDOOR: 47}
        assert not (project.root / "data" / "runs").exists()
        assert not (project.root / "data" / "raw").exists()

    def test_utc_now_is_aware(self) -> None:
        assert utc_now().utcoffset() is not None


def test_device_failures_are_redacted() -> None:
    failure = DeviceFailure(PortalDevice("VUT 77678271"), "timeout as synthetic-user")
    report = FetchReport(
        SessionResult((), (failure,)), SecretRedactor.of({"SIVIN_USER": "synthetic-user"})
    )
    assert report.failures == ("fetch VUT 77678271: timeout as ***",)
