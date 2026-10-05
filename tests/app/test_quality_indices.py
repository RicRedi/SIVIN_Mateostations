"""QualityService and IndicesService on stored data (real excerpt and SYNTHETIC exports)."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
import pytest
from tests.app.conftest import make_factory
from tests.app.project import (
    EMPTY_OFFSITE_LOG,
    OUTDOOR_SENSOR,
    REAL_SENSOR,
    Project,
    make_project,
    write_synthetic_export,
)

from sivin.analytics.base import (
    ClimateIndex,
    IndexContext,
    IndexParams,
    IndexRegistry,
    IndexResult,
    index_registry,
)
from sivin.app.factory import ServiceFactory
from sivin.app.indices import (
    IndexContextFactory,
    IndexSelection,
    IndicesReport,
    SeasonWindow,
    UnknownIndexError,
)
from sivin.app.outcome import Outcome
from sivin.app.quality import QualityReport, iso_utc
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries

REAL = SensorId(REAL_SENSOR)
OUTDOOR = SensorId(OUTDOOR_SENSOR)


def ingest(factory: ServiceFactory, *paths: Path) -> None:
    report = factory.ingest_service().ingest(paths)
    assert report.outcome is Outcome.OK, report.failures


class TestQualityService:
    def test_off_site_period_of_the_real_export_is_flagged(
        self, project: Project, factory: ServiceFactory
    ) -> None:
        ingest(factory, project.real_export())
        report = factory.quality_service().run()
        assert report.outcome is Outcome.OK
        item = report.sensors[REAL]
        assert item.result is not None
        qc = item.result.series.frame[Column.QC].to_numpy()
        # The log entry (Q10) covers the whole export: every one of the 300 rows.
        assert ((qc & int(QcFlag.PRE_DEPLOYMENT)) != 0).all()
        assert item.events_file == project.root / "data/derived/events/77799986.json"
        document = json.loads(item.events_file.read_text(encoding="utf-8"))
        assert document["sensor_id"] == REAL_SENSOR
        assert document["n_samples"] == 300
        assert document["flag_counts"]["PRE_DEPLOYMENT"] == 300
        (off_site,) = [e for e in document["events"] if e["type"] == "off_site"]
        # 2025-07-30 10:00 CEST and 2026-03-01 22:30 CET in UTC.
        assert (off_site["t"], off_site["t_end"]) == (
            "2025-07-30T08:00:00Z",
            "2026-03-01T21:30:00Z",
        )
        assert off_site["source"] == "log"
        assert off_site["detail"].startswith("service: ")
        assert document["first_t"] == "2025-07-30T08:22:29Z"
        assert document["last_t"] == "2026-03-01T21:27:05Z"

    def test_events_file_is_byte_stable(self, project: Project, factory: ServiceFactory) -> None:
        ingest(factory, project.real_export())
        first = factory.quality_service().run().sensors[REAL].events_file
        assert first is not None
        content = first.read_bytes()
        factory.quality_service().run()
        assert first.read_bytes() == content

    def test_set_aside_precipitation(self, project: Project, factory: ServiceFactory) -> None:
        ingest(factory, write_synthetic_export(project.downloads, days=1, precip_spike_at=3))
        item = factory.quality_service().run([OUTDOOR]).sensors[OUTDOOR]
        assert item.result is not None
        assert item.result.values_set_aside == 1
        assert math.isnan(item.result.series.frame[Column.PRECIP].iloc[3])
        assert item.events_file is not None
        document = json.loads(item.events_file.read_text(encoding="utf-8"))
        assert document["values_set_aside"] == 1
        assert "precip_out_of_range" in {e["type"] for e in document["events"]}

    def test_range_dry_run_and_sensor_without_data(
        self, project: Project, factory: ServiceFactory
    ) -> None:
        ingest(factory, project.real_export())
        service = factory.quality_service(dry_run=True)
        report = service.run([REAL, OUTDOOR], start_utc="2026-02-01T00:00:00Z")
        assert report.dry_run
        assert report.sensors[REAL].events_file is None
        assert report.sensors[REAL].result is not None
        assert report.sensors[REAL].result.series.timestamps.min() >= pd.Timestamp(
            "2026-02-01T00:00:00Z"
        )
        assert report.sensors[OUTDOOR].result is None
        assert report.sensors[OUTDOOR].failure is None
        assert not (project.root / "data" / "derived").exists()

    def test_malformed_store_file_fails_one_sensor(
        self, project: Project, factory: ServiceFactory
    ) -> None:
        ingest(factory, write_synthetic_export(project.downloads, days=1))
        bad = project.root / "data" / "raw" / REAL_SENSOR / "2026.csv"
        bad.parent.mkdir(parents=True)
        bad.write_text("broken\n", encoding="utf-8")
        report = factory.quality_service().run()
        assert report.outcome is Outcome.PARTIAL_FAILURE
        assert report.failures[0].startswith(f"qc {REAL_SENSOR}: ")
        assert report.sensors[OUTDOOR].result is not None

    def test_known_deployments_come_from_the_registry(
        self, project: Project, factory: ServiceFactory
    ) -> None:
        service = factory.quality_service()
        known = service._known_deployments(MeasurementSeries.empty(OUTDOOR))
        assert known == [pd.Timestamp("2025-12-01T00:00:00Z")]
        assert service._known_deployments(MeasurementSeries.empty(SensorId("11111111"))) == []

    def test_helpers(self) -> None:
        assert iso_utc(None) is None
        assert iso_utc(pd.Timestamp("2026-01-01T01:00:00+01:00")) == "2026-01-01T00:00:00Z"
        assert QualityReport().outcome is Outcome.OK


class TestSeasonWindow:
    def test_window_of_a_season(self) -> None:
        window = SeasonWindow.of(2026)
        assert (window.first, window.last) == (date(2025, 1, 1), date(2026, 12, 31))
        start, end = window.bounds_utc("Europe/Prague")
        # Local midnight of 2025-01-01 (CET) and of 2027-01-01 (CET) minus 1 ns.
        assert start == pd.Timestamp("2024-12-31T23:00:00Z")
        assert end == pd.Timestamp("2026-12-31T23:00:00Z") - pd.Timedelta(1, unit="ns")


class _FailingParams(IndexParams):
    pass


class _FailingIndex(ClimateIndex[_FailingParams]):
    index_id: ClassVar[str] = "failing"
    unit: ClassVar[str] = "1"
    params_model = _FailingParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        raise ValueError("synthetic failure")


class TestIndices:
    def test_selection(self) -> None:
        selection = IndexSelection(index_registry, {"huglin": {"k_override": 1.05}})
        created = selection.create(["huglin", "huglin", "gst"])
        assert list(created) == ["huglin", "gst"]
        assert created["huglin"].params.k_override == 1.05  # type: ignore[attr-defined]
        assert list(selection.create()) == list(index_registry.ids())
        with pytest.raises(UnknownIndexError, match="unknown index nope; registered: bedd"):
            selection.create(["nope"])

    def test_context_uses_the_configuration_and_the_placement(
        self, factory: ServiceFactory
    ) -> None:
        config = factory.workspace.config
        contexts = IndexContextFactory(config.time, config.analytics, factory.catalog().registry)
        series = MeasurementSeries.from_records(
            OUTDOOR, [pd.Timestamp("2026-06-01T10:00:00Z")], [20.0], [50.0]
        )
        context = contexts.build(series, 2026)
        assert context.year == 2026
        assert context.latitude_deg == 48.880215
        assert context.elevation_m == 183.939606
        assert context.timezone == "Europe/Prague"
        assert context.exclude_mask == 311
        before = MeasurementSeries.from_records(
            OUTDOOR, [pd.Timestamp("2025-06-01T10:00:00Z")], [20.0], [50.0]
        )
        assert contexts.placement(before) is not None  # last placement
        assert contexts.placement(MeasurementSeries.empty(OUTDOOR)) is not None
        assert contexts.placement(MeasurementSeries.empty(SensorId("11111111"))) is None

    def test_season_results_file(self, project: Project, factory: ServiceFactory) -> None:
        ingest(factory, write_synthetic_export(project.downloads, days=3), project.real_export())
        report = factory.indices_service().run(2026, index_ids=["gst", "frost"])
        assert report.outcome is Outcome.OK
        assert report.file == project.root / "data/derived/indices/2026.json"
        document = json.loads(report.file.read_text(encoding="utf-8"))
        assert document["season"] == 2026
        assert (document["data_from"], document["data_to"]) == ("2025-01-01", "2026-12-31")
        assert set(document["sensors"]) == {OUTDOOR_SENSOR, REAL_SENSOR}
        gst = document["sensors"][OUTDOOR_SENSOR]["gst"]
        assert set(gst) == {
            "value",
            "unit",
            "coverage",
            "complete",
            "class",
            "estimated",
            "details",
        }
        assert gst["unit"] == "°C"
        # Three synthetic June days cover 3 of 214 days of the growing season.
        assert gst["complete"] is False
        # The real sensor was off site the whole time: no valid sample, no value.
        assert document["sensors"][REAL_SENSOR]["gst"]["value"] is None

    def test_season_without_data_and_dry_run(
        self, project: Project, factory: ServiceFactory
    ) -> None:
        ingest(factory, write_synthetic_export(project.downloads, days=1))
        report = factory.indices_service(dry_run=True).run(2020)
        assert report.results == {}
        assert report.file is None
        assert not (project.root / "data" / "derived").exists()

    def test_failing_index_and_sensor(self, tmp_path: Path) -> None:
        project = make_project(tmp_path / "p", offsite_log=EMPTY_OFFSITE_LOG)
        factory = make_factory(project)
        ingest(factory, write_synthetic_export(project.downloads, days=1))
        registry = IndexRegistry()
        registry.register(_FailingIndex)
        service = factory.indices_service()
        service._selection = IndexSelection(registry, {})  # type: ignore[misc]
        bad = project.root / "data" / "raw" / "77680921" / "2026.csv"
        bad.parent.mkdir(parents=True)
        bad.write_text("broken\n", encoding="utf-8")
        report = service.run(2026)
        assert report.outcome is Outcome.PARTIAL_FAILURE
        assert report.failures == (
            "indices 77678271 failing: synthetic failure",
            report.failures[1],
        )
        assert report.failures[1].startswith("indices 77680921: ")
        assert report.results[OUTDOOR] == {}

    def test_report_document_and_outcome(self) -> None:
        report = IndicesReport(SeasonWindow.of(2026))
        document: dict[str, Any] = report.document()
        assert document["sensors"] == {}
        assert report.outcome is Outcome.OK
