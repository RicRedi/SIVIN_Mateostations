"""IngestService: parse, validate, quarantine, append; run-log record of an ingest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.app.conftest import RUN_TIME, make_factory
from tests.app.project import (
    OUTDOOR_SENSOR,
    REAL_SENSOR,
    Project,
    make_project,
    write_synthetic_export,
)

from sivin.app.factory import ServiceFactory
from sivin.app.ingest import DirectoryExports, IngestReport, export_files
from sivin.app.outcome import Outcome
from sivin.app.run import RunRecorder
from sivin.core.ids import SensorId
from sivin.core.schema import Column
from sivin.storage.runlog import RunLog

BROKEN_CSV = "Meteo Data;\r\nDatum a čas;Teplota (°C)\r\n2026-03-01 00:00:07;3,7\r\n;\r\n"
"""SYNTHETIC export without the humidity column (rejected: required column missing)."""


def test_real_export_is_appended_with_a_short_source(
    project: Project, factory: ServiceFactory
) -> None:
    path = project.real_export()
    report = factory.ingest_service().ingest([path])
    assert report.outcome is Outcome.OK
    (item,) = report.files
    assert item.accepted
    assert item.rows == {SensorId(REAL_SENSOR): 300}
    assert item.appends[SensorId(REAL_SENSOR)].new_rows == 300
    stored = factory.store().read(SensorId(REAL_SENSOR))
    assert len(stored) == 300
    assert set(stored.frame[Column.SOURCE]) == {"20260301T223842"}
    again = factory.ingest_service().ingest([path])
    assert again.files[0].appends[SensorId(REAL_SENSOR)].identical_skipped == 300


def test_two_files_sum_their_counts(project: Project, factory: ServiceFactory) -> None:
    first = write_synthetic_export(project.downloads, days=1, stamp="20260602_060000")
    second = write_synthetic_export(project.downloads, days=2, stamp="20260603_060000")
    report = factory.ingest_service().ingest([first, second])
    counts = report.appends[SensorId(OUTDOOR_SENSOR)]
    # 1 day = 47 rows (86 400 // 1830), 2 days = 94 rows; the first 47 are identical.
    assert (counts.new_rows, counts.identical_skipped) == (94, 47)
    assert report.validation_counts == {}
    assert report.failures == ()


def test_rejected_file_is_moved_to_quarantine_with_its_report(
    project: Project, factory: ServiceFactory
) -> None:
    path = project.downloads / "MeteoData_8615620 77678271 (VUT)_20260301_223857.csv"
    project.downloads.mkdir(parents=True)
    path.write_text(BROKEN_CSV, encoding="utf-8")
    original = path.read_bytes()
    report = factory.ingest_service().ingest([path])
    (item,) = report.files
    assert not item.accepted
    assert item.failure is not None
    assert item.failure.startswith("rejected: ")
    assert report.outcome is Outcome.PARTIAL_FAILURE
    assert report.failures[0].startswith(f"{path.name}: rejected: ")
    quarantined = project.root / "data" / "quarantine" / path.name
    assert item.quarantined == quarantined
    assert quarantined.read_bytes() == original
    assert not path.exists()  # the default mode moves the file out of the downloads
    document = json.loads(quarantined.with_name(path.name + ".report.json").read_text("utf-8"))
    assert document["file"] == path.name
    assert document["accepted"] is False
    assert "error" in {issue["severity"] for issue in document["issues"]}
    assert any(key.startswith("error:") for key in report.validation_counts)
    assert factory.store().sensors() == []


def test_copy_mode_keeps_the_rejected_file(tmp_path: Path) -> None:
    project = make_project(
        tmp_path / "p",
        config=(
            "ingest:\n  quarantine_mode: copy\n"
            '  parsers:\n    latest_timestamp: "2030-01-01T00:00:00"\n'
        ),
    )
    path = project.downloads / "export_without_name.csv"
    project.downloads.mkdir(parents=True)
    path.write_text(BROKEN_CSV, encoding="utf-8")
    report = make_factory(project).ingest_service().ingest([path])
    assert path.exists()
    assert report.files[0].quarantined == project.root / "data" / "quarantine" / path.name


def test_quarantine_name_collision_gets_a_time_suffix(
    project: Project, factory: ServiceFactory
) -> None:
    project.downloads.mkdir(parents=True)
    quarantine = project.root / "data" / "quarantine"
    names = []
    for _ in range(3):
        path = project.downloads / "broken.csv"
        path.write_text(BROKEN_CSV, encoding="utf-8")
        (item,) = factory.ingest_service().ingest([path]).files
        assert item.quarantined is not None
        names.append(item.quarantined.name)
    # RUN_TIME 2026-10-05T04:00Z; nothing is overwritten.
    assert names == ["broken.csv", "broken_20261005T040000Z.csv", "broken_20261005T040000Z_2.csv"]
    assert (quarantine / "broken_20261005T040000Z_2.csv.report.json").exists()


def test_quarantine_failure_is_recorded_not_raised(
    project: Project, factory: ServiceFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.downloads.mkdir(parents=True)
    bad = project.downloads / "broken.csv"
    bad.write_text(BROKEN_CSV, encoding="utf-8")
    good = write_synthetic_export(project.downloads, days=1)

    def denied(source: object, target: object) -> None:
        raise PermissionError("synthetic: permission denied")

    monkeypatch.setattr("sivin.app.ingest.shutil.move", denied)
    report = factory.ingest_service().ingest([bad, good])
    assert report.files[0].quarantined is None
    assert report.files[0].failure is not None
    assert "quarantine failed: synthetic: permission denied" in report.files[0].failure
    assert report.files[1].accepted
    assert report.outcome is Outcome.PARTIAL_FAILURE


def test_unreadable_file_is_rejected(
    project: Project, factory: ServiceFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_synthetic_export(project.downloads, days=1)

    def unreadable(self: object, path: Path) -> object:
        raise PermissionError("synthetic: cannot open")

    monkeypatch.setattr("sivin.app.ingest.ExportReader.read", unreadable)
    (item,) = factory.ingest_service(dry_run=True).ingest([path]).files
    assert item.report.rules() == {"file-readable"}
    assert item.failure == "rejected: cannot read: synthetic: cannot open"


def test_unknown_format_and_unregistered_sensor_are_rejected(
    project: Project, factory: ServiceFactory
) -> None:
    project.downloads.mkdir(parents=True)
    unknown = project.downloads / "notes.txt"
    unknown.write_text("hello", encoding="utf-8")
    stranger = write_synthetic_export(project.downloads, serial="11111111", days=1)
    report = factory.ingest_service().ingest([unknown, stranger])
    rules = [{issue.rule for issue in item.report.errors} for item in report.files]
    assert rules == [{"export-format"}, {"sensor-registered"}]
    assert "11111111 not in the sensor registry" in (report.files[1].failure or "")
    assert factory.store().sensors() == []


def test_dry_run_writes_nothing(project: Project, factory: ServiceFactory) -> None:
    good = project.real_export()
    bad = project.downloads / "broken.csv"
    bad.write_text(BROKEN_CSV, encoding="utf-8")
    report = factory.ingest_service(dry_run=True).ingest([good, bad])
    assert report.dry_run
    assert report.files[0].rows == {SensorId(REAL_SENSOR): 300}
    assert report.files[0].appends == {}
    assert report.files[1].quarantined is None
    assert not (project.root / "data" / "raw").exists()
    assert not (project.root / "data" / "quarantine").exists()


def test_store_error_fails_the_file_only(project: Project, factory: ServiceFactory) -> None:
    partition = project.root / "data" / "raw" / REAL_SENSOR / "2025.csv"
    partition.parent.mkdir(parents=True)
    partition.write_text("not a store file\n", encoding="utf-8")
    outdoor = write_synthetic_export(project.downloads, days=1)
    report = factory.ingest_service().ingest([project.real_export(), outdoor])
    assert report.files[0].failure is not None
    assert report.files[0].failure.startswith("store: ")
    assert report.files[1].accepted
    assert report.outcome is Outcome.PARTIAL_FAILURE


def test_run_record_of_an_ingest(project: Project, factory: ServiceFactory) -> None:
    report = factory.ingest_service().ingest([project.real_export()])
    record = RunRecorder.record(RUN_TIME, RUN_TIME, report, ("fetch x: timeout",))
    assert record.files == ("MeteoData_8615620_77799986_VUT_20260301_223842.csv",)
    assert record.appends[SensorId(REAL_SENSOR)].new_rows == 300
    assert record.failures == ("fetch x: timeout",)
    path = factory.run_recorder().write(record)
    assert path == project.root / "data" / "runs" / "2026-10-05.jsonl"
    assert RunLog(project.root / "data").read(RUN_TIME.date()) == [record]


def test_export_files_and_directory_source(project: Project) -> None:
    assert DirectoryExports(project.downloads, ("*.csv",)).exports(None) == ((), ())
    project.downloads.mkdir(parents=True)
    for name in ("b.csv", "a.xlsx", ".hidden.csv", "c.csv.crdownload", "d.txt"):
        (project.downloads / name).write_text("x", encoding="utf-8")
    (project.downloads / "sub.csv").mkdir()
    names = [p.name for p in export_files(project.downloads, ("*.csv", "*.xlsx"))]
    assert names == ["a.xlsx", "b.csv"]
    files, failures = DirectoryExports(project.downloads, ("*.csv",)).exports(None)
    assert [p.name for p in files] == ["b.csv"]
    assert failures == ()


def test_empty_report() -> None:
    report = IngestReport()
    assert report.outcome is Outcome.OK
    assert report.appends == {}
    assert report.conflicts == ()


@pytest.mark.parametrize("policy", ["prefer_newest", "prefer_existing"])
def test_conflicts_are_reported(tmp_path: Path, policy: str) -> None:
    project = make_project(
        tmp_path / "p",
        config=(
            f"storage:\n  conflict_policy: {policy}\n"
            'ingest:\n  parsers:\n    latest_timestamp: "2030-01-01T00:00:00"\n'
        ),
    )
    first = write_synthetic_export(project.downloads, days=1, stamp="20260602_060000")
    text = first.read_text(encoding="utf-8").replace("3,60", "3,50")
    second = project.downloads / "MeteoData_8615620 77678271 (VUT)_20260603_060000.csv"
    second.write_text(text, encoding="utf-8")
    report = make_factory(project).ingest_service().ingest([first, second])
    counts = report.appends[SensorId(OUTDOOR_SENSOR)]
    assert counts.conflicting_values == 47
    assert len(report.conflicts) == 47
    assert {d.conflict.incoming_source for d in report.conflicts} == {"20260603T060000"}


def test_rejecting_a_file_inside_the_quarantine_keeps_it(
    project: Project, factory: ServiceFactory
) -> None:
    quarantine = project.root / "data" / "quarantine"
    quarantine.mkdir(parents=True)
    path = quarantine / "broken.csv"
    path.write_text(BROKEN_CSV, encoding="utf-8")
    report = factory.ingest_service().ingest([path])
    assert report.files[0].quarantined == path
    assert path.exists()
    assert (quarantine / "broken.csv.report.json").exists()
