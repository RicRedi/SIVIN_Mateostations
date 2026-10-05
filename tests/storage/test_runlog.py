"""Tests of RunLog and RunRecord. All counts are synthetic."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from sivin.core.ids import SensorId
from sivin.storage.errors import StoreFormatError
from sivin.storage.merge import AppendCounts
from sivin.storage.runlog import RunLog, RunRecord

PRAGUE_SUMMER = timezone(timedelta(hours=2))


def _record(started_at: datetime) -> RunRecord:
    return RunRecord(
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=3, seconds=20),
        files=("MeteoData_8615620 77678271 (VUT)_20260301_223857.csv",),
        appends={SensorId("77678271"): AppendCounts(new_rows=2, identical_skipped=48)},
        validation_issues={"warning": 1},
        failures=("sensor 11111111: download timed out",),
    )


def test_record_is_stored_as_one_json_line_in_the_file_of_its_utc_start_date(
    tmp_path: Path,
) -> None:
    # 01:30 local summer time on 6 Oct is 23:30 UTC on 5 Oct.
    record = _record(datetime(2026, 10, 6, 1, 30, tzinfo=PRAGUE_SUMMER))
    path = RunLog(tmp_path).append(record)
    assert path == tmp_path / "runs" / "2026-10-05.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "appends": {
            "77678271": {
                "conflicting_rows": 0,
                "identical_skipped": 48,
                "new_rows": 2,
                "replaced_rows": 0,
            }
        },
        "failures": ["sensor 11111111: download timed out"],
        "files": ["MeteoData_8615620 77678271 (VUT)_20260301_223857.csv"],
        "finished_at": "2026-10-05T23:33:20Z",
        "started_at": "2026-10-05T23:30:00Z",
        "validation_issues": {"warning": 1},
    }


def test_append_only_and_round_trip(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    first = _record(datetime(2026, 10, 5, 8, 0, tzinfo=UTC))
    second = _record(datetime(2026, 10, 5, 9, 0, tzinfo=UTC))
    log.append(first)
    log.append(second)
    assert log.read(date(2026, 10, 5)) == [first, second]
    assert log.read(date(2026, 10, 4)) == []


def test_record_normalises_to_utc_and_freezes_mappings() -> None:
    record = _record(datetime(2026, 10, 6, 1, 30, tzinfo=PRAGUE_SUMMER))
    assert record.started_at == datetime(2026, 10, 5, 23, 30, tzinfo=UTC)
    assert record.started_at.tzinfo is UTC
    assert record.day == date(2026, 10, 5)
    with pytest.raises(TypeError):
        record.validation_issues["error"] = 1  # type: ignore[index]


def test_record_rejects_naive_times_and_negative_duration() -> None:
    with pytest.raises(ValueError, match="started_at must be timezone-aware"):
        RunRecord(datetime(2026, 10, 5, 8, 0), datetime(2026, 10, 5, 9, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="before started_at"):
        RunRecord(datetime(2026, 10, 5, 9, 0, tzinfo=UTC), datetime(2026, 10, 5, 8, 0, tzinfo=UTC))


def test_minimal_record_defaults() -> None:
    moment = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    record = RunRecord(moment, moment)
    assert record.to_dict() == {
        "started_at": "2026-10-05T08:00:00Z",
        "finished_at": "2026-10-05T08:00:00Z",
        "files": [],
        "appends": {},
        "validation_issues": {},
        "failures": [],
    }


@pytest.mark.parametrize("line", ["not json", "{}", '{"started_at": 1}'])
def test_invalid_line_is_reported_with_its_number(tmp_path: Path, line: str) -> None:
    log = RunLog(tmp_path)
    log.append(_record(datetime(2026, 10, 5, 8, 0, tzinfo=UTC)))
    with log.path_for(date(2026, 10, 5)).open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    with pytest.raises(StoreFormatError, match=r"2026-10-05.jsonl:2: invalid run record"):
        log.read(date(2026, 10, 5))
