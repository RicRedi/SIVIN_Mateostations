"""Run summary (``sivin report``, WP-4.1): selection, failures, warnings and both formats.

Every run record and events file here is SYNTHETIC and written by the test.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from sivin.app.summary import (
    DerivedFailure,
    ExitStatus,
    FailureKind,
    RunOutcome,
    RunRecordFinder,
    RunSelection,
    RunSelectionError,
    RunSummary,
    RunSummaryService,
    SummarySettings,
    WarningCollector,
    WarningGroup,
    classify_failure,
    warning_groups,
)
from sivin.app.summary_formats import (
    NO_RECORD,
    MarkdownSummary,
    SummaryFormat,
    TextSummary,
    markdown_text,
    summary_format_registry,
)
from sivin.core.ids import SensorId
from sivin.storage.merge import AppendCounts
from sivin.storage.runlog import RunLog, RunRecord

START = datetime(2026, 10, 5, 4, 0, 12, tzinfo=UTC)
"""SYNTHETIC run start: 06:00:12 local time (CEST)."""


def record(
    started_at: datetime = START,
    failures: tuple[str, ...] = (),
    appends: dict[SensorId, AppendCounts] | None = None,
    files: tuple[str, ...] = ("MeteoData_8615620 77678271 (VUT)_20261005_060100.csv",),
    validation_issues: dict[str, int] | None = None,
) -> RunRecord:
    return RunRecord(
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=3, seconds=28),
        files=files,
        appends=appends if appends is not None else {SensorId("77678271"): AppendCounts(47)},
        validation_issues=validation_issues or {},
        failures=failures,
    )


def write_events(
    directory: Path, sensor: str, events: list[dict[str, object]], **extra: object
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    document = {"sensor_id": sensor, "status": "ok", "events": events, **extra}
    (directory / f"{sensor}.json").write_text(json.dumps(document), encoding="utf-8")


def event(
    kind: str, t: str, severity: str = "warning", t_end: str | None = None
) -> dict[str, object]:
    return {"type": kind, "t": t, "t_end": t_end, "severity": severity, "detail": f"{kind} at {t}"}


class TestClassifyFailure:
    @pytest.mark.parametrize(
        ("message", "kind"),
        [
            ("fetch 8615620 77678271: download timed out", FailureKind.FETCH),
            ("fetch: Portal login failed", FailureKind.FETCH),
            ("x.csv: rejected: missing column", FailureKind.REJECTED),
            ("x.csv: store: disk full", FailureKind.STORE),
            ("qc 77678271: bad file", FailureKind.QC),
            ("indices 77678271 huglin: boom", FailureKind.INDICES),
            ("site 77678271: boom", FailureKind.SITE),
            ("site: read-only", FailureKind.SITE),
            ("something else", FailureKind.OTHER),
        ],
    )
    def test_prefixes_of_the_services(self, message: str, kind: FailureKind) -> None:
        assert classify_failure(message) is kind

    def test_summary_splits_rejected_files_from_other_failures(self) -> None:
        failures = ("qc 1: a", "x.csv: rejected: b", "fetch: c", "y.csv: rejected: d")
        summary = RunSummary(record(failures=failures))
        assert summary.rejected_files == ("x.csv: rejected: b", "y.csv: rejected: d")
        assert summary.other_failures == ("fetch: c", "qc 1: a")
        assert list(summary.failures_by_kind) == [
            FailureKind.FETCH,
            FailureKind.REJECTED,
            FailureKind.QC,
        ]

    def test_no_record_has_no_failures_or_rows(self) -> None:
        summary = RunSummary(None)
        assert summary.rejected_files == ()
        assert summary.other_failures == ()
        assert summary.new_rows == 0
        assert dict(summary.appends) == {}


class TestRunOutcome:
    @pytest.mark.parametrize(
        ("code", "status"),
        [
            (0, ExitStatus.OK),
            (1, ExitStatus.PARTIAL_FAILURE),
            (2, ExitStatus.USAGE_ERROR),
            (3, ExitStatus.SETUP_ERROR),
            (4, ExitStatus.DATA_SOURCE_UNAVAILABLE),
            (5, ExitStatus.INTERNAL_ERROR),
            (130, ExitStatus.INTERRUPTED),
            (7, ExitStatus.UNKNOWN),
        ],
    )
    def test_names(self, code: int, status: ExitStatus) -> None:
        assert RunOutcome(code).status is status
        assert RunOutcome(code).meaning

    def test_source_unavailable_says_the_stored_data_were_processed(self) -> None:
        assert "stored data were processed" in RunOutcome(4).meaning


class TestRunSelection:
    def test_latest(self) -> None:
        assert RunSelection.parse("latest") == RunSelection()

    def test_date_and_naive_since_is_utc(self) -> None:
        selection = RunSelection.parse("2026-10-05", "2026-10-05T04:00:00")
        assert selection.day == date(2026, 10, 5)
        assert selection.since == datetime(2026, 10, 5, 4, tzinfo=UTC)

    def test_since_with_offset(self) -> None:
        selection = RunSelection.parse("latest", "2026-10-05T06:00:00+02:00")
        assert selection.since == datetime(2026, 10, 5, 4, tzinfo=UTC)

    @pytest.mark.parametrize(("run", "since"), [("yesterday", None), ("latest", "soon")])
    def test_invalid_values(self, run: str, since: str | None) -> None:
        with pytest.raises(RunSelectionError):
            RunSelection.parse(run, since)

    def test_naive_since_is_rejected_by_the_constructor(self) -> None:
        with pytest.raises(RunSelectionError, match="timezone-aware"):
            RunSelection(since=datetime(2026, 10, 5))

    def test_accepts_records_from_since_on(self) -> None:
        selection = RunSelection(since=START)
        assert selection.accepts(record(START))
        assert not selection.accepts(record(START - timedelta(seconds=1)))


class TestRunRecordFinder:
    @pytest.fixture
    def log(self, tmp_path: Path) -> RunLog:
        return RunLog(tmp_path)

    def finder(self, tmp_path: Path, log: RunLog) -> RunRecordFinder:
        return RunRecordFinder(log, tmp_path / "runs")

    def test_empty_log(self, tmp_path: Path, log: RunLog) -> None:
        assert self.finder(tmp_path, log).days() == []
        assert self.finder(tmp_path, log).find(RunSelection()) is None

    def test_latest_is_the_last_record_of_the_newest_day(self, tmp_path: Path, log: RunLog) -> None:
        yesterday = START - timedelta(days=1)
        log.append(record(yesterday))
        log.append(record(START, failures=("first",)))
        log.append(record(START + timedelta(hours=1), failures=("second",)))
        (tmp_path / "runs" / "notes.jsonl").write_text("", encoding="utf-8")
        finder = self.finder(tmp_path, log)
        assert finder.days() == [START.date(), yesterday.date()]
        found = finder.find(RunSelection())
        assert found is not None
        assert found.failures == ("second",)

    def test_a_given_day(self, tmp_path: Path, log: RunLog) -> None:
        yesterday = START - timedelta(days=1)
        log.append(record(yesterday, failures=("old",)))
        log.append(record(START))
        found = self.finder(tmp_path, log).find(RunSelection(day=yesterday.date()))
        assert found is not None
        assert found.failures == ("old",)

    def test_since_skips_older_runs(self, tmp_path: Path, log: RunLog) -> None:
        log.append(record(START - timedelta(days=1)))
        finder = self.finder(tmp_path, log)
        assert finder.find(RunSelection(since=START)) is None
        log.append(record(START))
        assert finder.find(RunSelection(since=START)) == record(START)


class TestWarnings:
    def test_groups_warnings_per_kind_with_the_latest(self) -> None:
        events = [
            event("low_battery", "2026-09-01T00:00:00Z", t_end="2026-09-02T00:00:00Z"),
            event("low_battery", "2026-10-01T00:00:00Z", t_end="2026-10-04T00:00:00Z"),
            event("off_site", "2026-05-01T00:00:00Z", severity="info"),
            event("unlogged_off_site", "2026-08-01T00:00:00Z"),
            "not an event",
        ]
        groups = warning_groups("77678271", events)
        assert groups == [
            WarningGroup(
                "77678271",
                "low_battery",
                2,
                "2026-10-01T00:00:00Z",
                "2026-10-04T00:00:00Z",
                "low_battery at 2026-10-01T00:00:00Z",
            ),
            WarningGroup(
                "77678271",
                "unlogged_off_site",
                1,
                "2026-08-01T00:00:00Z",
                None,
                "unlogged_off_site at 2026-08-01T00:00:00Z",
            ),
        ]

    def test_collects_files_most_recent_first_and_failed_files(self, tmp_path: Path) -> None:
        events_dir = tmp_path / "events"
        write_events(events_dir, "77678271", [event("low_battery", "2026-09-01T00:00:00Z")])
        write_events(
            events_dir,
            "77799986",
            [event("unlogged_off_site", "2026-10-01T00:00:00Z")],
            status="failed",
            error="data/raw/77799986/2026.csv:3: bad value",
        )
        (events_dir / "README.json").write_text("{}", encoding="utf-8")
        (events_dir / "12345678.json").write_text("[1, 2]", encoding="utf-8")
        warnings, failures = WarningCollector(events_dir).collect()
        assert [(group.sensor_id, group.kind) for group in warnings] == [
            ("77799986", "unlogged_off_site"),
            ("77678271", "low_battery"),
        ]
        assert failures == (DerivedFailure("77799986", "data/raw/77799986/2026.csv:3: bad value"),)

    def test_missing_directory(self, tmp_path: Path) -> None:
        assert WarningCollector(tmp_path / "none").collect() == ((), ())


class TestService:
    def test_summarises_record_and_warnings(self, tmp_path: Path) -> None:
        log = RunLog(tmp_path)
        log.append(record())
        write_events(
            tmp_path / "events", "77678271", [event("low_battery", "2026-09-01T00:00:00Z")]
        )
        service = RunSummaryService(
            RunRecordFinder(log, tmp_path / "runs"),
            WarningCollector(tmp_path / "events"),
            "Europe/Prague",
            SummarySettings(max_items=3),
        )
        summary = service.summarise(RunSelection(), RunOutcome(1))
        assert summary.record == record()
        assert summary.outcome == RunOutcome(1)
        assert [group.kind for group in summary.warnings] == ["low_battery"]
        assert summary.display_timezone == "Europe/Prague"
        assert summary.settings.max_items == 3
        assert summary.new_rows == 47

    def test_redacts_every_text_from_the_files(self, tmp_path: Path) -> None:
        log = RunLog(tmp_path)
        log.append(record(failures=("fetch: SECRET",), files=("SECRET.csv",)))
        write_events(
            tmp_path / "events",
            "77678271",
            [event("low_battery", "2026-09-01T00:00:00Z") | {"detail": "SECRET"}],
            status="failed",
            error="SECRET",
        )
        service = RunSummaryService(
            RunRecordFinder(log, tmp_path / "runs"),
            WarningCollector(tmp_path / "events"),
            "UTC",
            redact=lambda text: text.replace("SECRET", "***"),
        )
        summary = service.summarise(RunSelection())
        assert summary.record is not None
        assert summary.record.failures == ("fetch: ***",)
        assert summary.record.files == ("***.csv",)
        assert summary.warnings[0].latest_detail == "***"
        assert summary.derived_failures == (DerivedFailure("77678271", "***"),)

    def test_without_a_record(self, tmp_path: Path) -> None:
        service = RunSummaryService(
            RunRecordFinder(RunLog(tmp_path), tmp_path / "runs"),
            WarningCollector(tmp_path / "events"),
            "UTC",
        )
        summary = service.summarise(RunSelection())
        assert summary.record is None
        assert summary.settings == SummarySettings()


class TestSettings:
    def test_rejects_unknown_keys_and_zero(self) -> None:
        with pytest.raises(ValueError, match="extra"):
            SummarySettings.model_validate({"max_item": 3})
        with pytest.raises(ValueError, match="greater than or equal"):
            SummarySettings(max_items=0)

    def test_every_field_has_a_description(self) -> None:
        assert all(info.description for info in SummarySettings.model_fields.values())


def full_summary(max_items: int = 50) -> RunSummary:
    return RunSummary(
        record(
            failures=(
                "a|b.csv: rejected: column <Teplota> missing",
                "fetch 8615620 77680921: download timed out",
            ),
            appends={
                SensorId("77678271"): AppendCounts(47, 0, 2, 0, 1, 1),
                SensorId("77799986"): AppendCounts(0, 94),
            },
            validation_issues={"error:required-columns": 1, "warning:duplicates": 3},
        ),
        RunOutcome(1),
        (
            WarningGroup(
                "77678271",
                "low_battery",
                2,
                "2026-10-01T00:00:00Z",
                "2026-10-04T00:00:00Z",
                "min 3.31 V",
            ),
            WarningGroup(
                "77799986", "unlogged_off_site", 1, "2026-08-01T00:00:00Z", None, "check log"
            ),
        ),
        (DerivedFailure("77680921", "bad value"),),
        "Europe/Prague",
        SummarySettings(max_items=max_items),
    )


class TestMarkdown:
    def test_registered_formats(self) -> None:
        assert summary_format_registry.names() == ("markdown", "text")
        assert isinstance(summary_format_registry.create("markdown"), MarkdownSummary)

    def test_full_summary(self) -> None:
        text = MarkdownSummary().render(full_summary())
        assert text.startswith("## SIVIN pipeline run\n\n")
        assert text.endswith("\n")
        assert (
            "Outcome: PARTIAL\\_FAILURE (exit code 1). The run finished, but some items failed"
            in text
        )
        assert (
            "Run started 2026-10-05 04:00:12 UTC (2026-10-05 06:00 CEST), took 3 min 28 s." in text
        )
        assert "| export files processed | 1 |" in text
        assert "| files rejected | 1 |" in text
        assert "| rows added to the store | 47 |" in text
        assert "| other failures | 1 |" in text
        assert "| warning kinds (sensor, kind) | 2 |" in text
        assert "| 77678271 | 47 | 2 | 1 | 1 |" in text
        assert "| 77799986 | 0 | 0 | 0 | 0 |" in text
        assert "| error:required-columns | 1 |" in text
        assert "### Rejected files\n\n- a\\|b.csv: rejected: column \\<Teplota\\> missing" in text
        assert "### Failures\n\n- fetch 8615620 77680921: download timed out" in text
        assert "### Derived results not updated\n\n- events 77680921: bad value" in text
        assert (
            "| 77678271 | low\\_battery | 2 | 2026-10-01T00:00:00Z .. 2026-10-04T00:00:00Z "
            "| min 3.31 V |"
        ) in text
        assert "| 77799986 | unlogged\\_off\\_site | 1 | 2026-08-01T00:00:00Z | check log |" in text

    def test_caps_long_lists(self) -> None:
        text = MarkdownSummary().render(full_summary(max_items=1))
        assert "check log" not in text
        assert "... and 1 more." in text

    def test_caps_long_item_lists(self) -> None:
        summary = RunSummary(
            record(files=("a.csv", "b.csv", "c.csv")), settings=SummarySettings(max_items=2)
        )
        text = MarkdownSummary().render(summary)
        assert "- a.csv\n- b.csv\n- ... and 1 more\n" in text
        assert "c.csv" not in text

    def test_without_record_or_outcome(self) -> None:
        text = MarkdownSummary().render(RunSummary(None))
        assert "Outcome" not in text
        assert NO_RECORD.split(":")[0] in text
        assert "No QC warnings in the stored data." in text

    def test_no_rows_added(self) -> None:
        text = MarkdownSummary().render(RunSummary(record(appends={}, files=())))
        assert "No rows were added." in text
        assert "### Export files" not in text

    def test_warning_without_times(self) -> None:
        group = WarningGroup("77678271", "low_battery", 1, None, None, "")
        text = MarkdownSummary().render(RunSummary(None, warnings=(group,)))
        assert "| 77678271 | low\\_battery | 1 | - |  |" in text

    def test_escaping(self) -> None:
        assert markdown_text("a|b <script> [x](y) *z*\nnext & #1") == (
            "a\\|b \\<script\\> \\[x\\](y) \\*z\\* next \\& \\#1"
        )


class TestText:
    def test_aligned_table_and_plain_text(self) -> None:
        text = TextSummary().render(full_summary())
        assert text.startswith("SIVIN PIPELINE RUN\n\n")
        assert "Outcome: PARTIAL_FAILURE (exit code 1)." in text
        assert "Rows added per sensor:" in text
        assert "77678271  47        2              1                   1" in text
        assert "- a|b.csv: rejected: column <Teplota> missing" in text

    def test_a_new_format_is_a_registered_class(self) -> None:
        class Shout(TextSummary):
            name = "shout"

            def text(self, value: str) -> str:
                return value.upper()

        assert isinstance(Shout(), SummaryFormat)
        assert "NO QC WARNINGS" in Shout().render(RunSummary(None))
