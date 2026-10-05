"""End to end: ``sivin fetch`` → ``ingest`` → ``qc`` → ``indices`` and ``sivin run``.

A temporary project with the repository's sensor registry and off-site log (with the real Q10
entry of sensor 77799986), the trimmed REAL export of 77799986 and SYNTHETIC outdoor exports
of 77678271. The portal is the WP-1.3 fake browser (no network); every command goes through
the real CLI (typer's CliRunner).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.app.fake_portal import credentials, drivers
from tests.app.project import (
    OUTDOOR_SENSOR,
    REAL_SENSOR,
    Project,
    make_project,
    write_synthetic_export,
)
from typer.testing import CliRunner, Result

from sivin.cli import main as cli
from sivin.cli.state import CliOverrides

RUN_TIME = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
runner = CliRunner()


@pytest.fixture(autouse=True)
def no_global_logging_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda level: None)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    made = make_project(tmp_path / "vineyard")
    monkeypatch.chdir(made.root)
    return made


def sivin(*args: str) -> Result:
    overrides = CliOverrides(drivers=drivers(), credentials=credentials, clock=lambda: RUN_TIME)
    result = runner.invoke(cli.app, list(args), obj=overrides)
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    return result


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[Any]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fetch_ingest_qc_indices(project: Project) -> None:
    fetched = sivin("fetch", "--sensor", OUTDOOR_SENSOR)
    assert fetched.exit_code == 0, fetched.output
    project.real_export()
    write_synthetic_export(project.downloads, days=3, stamp="20260604_060000")

    ingested = sivin("ingest")
    assert ingested.exit_code == 0, ingested.output
    raw = project.root / "data" / "raw"
    # Real export: 2025-07-30 .. 2026-03-01 UTC -> two year files; synthetic: June 2026.
    assert sorted(p.relative_to(raw).as_posix() for p in raw.rglob("*.csv")) == [
        f"{OUTDOOR_SENSOR}/2026.csv",
        f"{REAL_SENSOR}/2025.csv",
        f"{REAL_SENSOR}/2026.csv",
    ]
    real_lines = (raw / REAL_SENSOR / "2026.csv").read_text(encoding="utf-8").splitlines()
    assert real_lines[0] == "timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source"
    assert real_lines[-1] == "2026-03-01T21:27:05Z,23.79,31.1,0.0,326.4,3.6,20260301T223842"
    (record,) = read_jsonl(project.root / "data/runs/2026-10-05.jsonl")
    assert sorted(record["files"]) == [
        "MeteoData_8615620 77678271 (VUT)_20260604_060000.csv",
        "MeteoData_8615620 77678271 (VUT)_20260605_060001.csv",
        "MeteoData_8615620_77799986_VUT_20260301_223842.csv",
    ]
    assert record["appends"][REAL_SENSOR]["new_rows"] == 300
    # 3 days of 1830 s = 141 rows; the fetched 2-day export repeats 94 of them.
    outdoor = record["appends"][OUTDOOR_SENSOR]
    assert outdoor["new_rows"] + outdoor["identical_skipped"] == 141 + 94
    assert record["failures"] == []

    checked = sivin("qc")
    assert checked.exit_code == 0, checked.output
    events_dir = project.root / "data" / "derived" / "events"
    real_events = read_json(events_dir / f"{REAL_SENSOR}.json")
    assert real_events["flag_counts"]["PRE_DEPLOYMENT"] == 300  # the whole excerpt is off site
    (off_site,) = [e for e in real_events["events"] if e["type"] == "off_site"]
    assert (off_site["t"], off_site["t_end"], off_site["source"]) == (
        "2025-07-30T08:00:00Z",
        "2026-03-01T21:30:00Z",
        "log",
    )
    outdoor_events = read_json(events_dir / f"{OUTDOOR_SENSOR}.json")
    assert "PRE_DEPLOYMENT" not in outdoor_events["flag_counts"]
    assert outdoor_events["n_samples"] == 141

    computed = sivin("indices", "--season", "2026")
    assert computed.exit_code == 0, computed.output
    document = read_json(project.root / "data" / "derived" / "indices" / "2026.json")
    assert document["season"] == 2026
    assert set(document["sensors"]) == {OUTDOOR_SENSOR, REAL_SENSOR}
    huglin = document["sensors"][OUTDOOR_SENSOR]["huglin"]
    assert set(huglin) == {"value", "unit", "coverage", "complete", "class", "estimated", "details"}
    assert huglin["unit"] == "°C·d"
    assert huglin["complete"] is False  # 3 June days of a 183-day period
    assert 0.0 < huglin["coverage"] < 0.05
    # The real sensor was off site the whole time: no index has a value.
    assert all(r["value"] is None for r in document["sensors"][REAL_SENSOR].values())

    again = sivin("ingest", "--from-dir", str(project.downloads))
    assert again.exit_code == 0, again.output
    assert "+0 new" in again.output


def test_run_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path / "vineyard")
    monkeypatch.chdir(project.root)
    project.real_export(project.root / "inbox")
    assert sivin("ingest", "--from-dir", str(project.root / "inbox")).exit_code == 0

    result = sivin("run", "--sensor", OUTDOOR_SENSOR, "--sensor", REAL_SENSOR)
    # 77799986 is not in the fake portal's device list: a fetch failure, the rest runs.
    assert result.exit_code == 1, result.output
    assert f"FAILED fetch {REAL_SENSOR}: not listed in the portal" in result.output
    assert "Run finished: PARTIAL_FAILURE." in result.output
    records = read_jsonl(project.root / "data/runs/2026-10-05.jsonl")
    assert len(records) == 2  # the ingest and the run
    assert records[1]["failures"] == [f"fetch {REAL_SENSOR}: not listed in the portal"]
    document = read_json(project.root / "data" / "derived" / "indices" / "2026.json")
    assert set(document["sensors"]) == {OUTDOOR_SENSOR, REAL_SENSOR}
    assert (project.root / "data" / "derived" / "events" / f"{REAL_SENSOR}.json").exists()

    clean = sivin("run", "--sensor", OUTDOOR_SENSOR)
    assert clean.exit_code == 0, clean.output
    assert "Run finished: OK." in clean.output
