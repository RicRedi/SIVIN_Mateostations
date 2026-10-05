"""SiteBuilder orchestration with fake sources: incremental reuse, rebuilds, failures.

The QC source and the index source are fakes over SYNTHETIC series.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.site.helpers import OTHER, SENSOR, result, series

from sivin.analytics.base import IndexResult
from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.quality.events import EventKind
from sivin.quality.pipeline import QualityResult
from sivin.site.builder import SiteBuilder, SiteInputs
from sivin.site.events import SiteEventMapping
from sivin.site.files import SiteOutput
from sivin.site.indices import IndexBatch
from sivin.site.labels import IndexSpec
from sivin.site.sensor_builder import DailyAggregation, SensorSiteBuilder, SummaryBuilder
from sivin.site.sensor_files import default_sensor_writers
from sivin.site.site_files import default_site_writers
from sivin.site.state import STATE_FILE, StateFile, StoreFingerprints

NOW = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
PRAGUE = "Europe/Prague"
REGISTRY = b'{"type": "FeatureCollection", "features": []}\n'


class FakeSource:
    """QC results per sensor; raises for sensors listed in ``failing``."""

    def __init__(self) -> None:
        self.results: dict[SensorId, QualityResult] = {}
        self.failing: set[SensorId] = set()
        self.calls: list[SensorId] = []

    def checked(self, sensor_id: SensorId) -> QualityResult:
        self.calls.append(sensor_id)
        if sensor_id in self.failing:
            raise ValueError(f"synthetic failure of {sensor_id}")
        return self.results[sensor_id]


class FakeIndices:
    """One index, ``mean_t`` (°C): the mean temperature of the season's year, or a failure."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, tuple[SensorId, ...]]] = []
        self.fail_for: set[SensorId] = set()

    def specs(self) -> tuple[IndexSpec, ...]:
        return (IndexSpec("mean_t", "°C"),)

    def compute(self, season: int, checked: Mapping[SensorId, QualityResult]) -> IndexBatch:
        self.calls.append((season, tuple(checked)))
        results: dict[SensorId, dict[str, IndexResult]] = {}
        failures = []
        for sensor_id, qc in checked.items():
            if sensor_id in self.fail_for:
                failures.append(f"indices {sensor_id} mean_t: synthetic")
                continue
            frame = qc.series.frame
            in_year = frame[frame["timestamp_utc"].dt.year == season]
            if in_year.empty:
                continue
            value = float(in_year["temp_c"].mean())
            results[sensor_id] = {
                "mean_t": IndexResult("mean_t", sensor_id, season, value, "°C", 0.5, False)
            }
        failed = frozenset(self.fail_for & set(checked))
        return IndexBatch(results, tuple(failures), failed)


class Rig:
    """A builder over a temporary store directory and output."""

    def __init__(self, root: Path) -> None:
        self.raw = root / "store" / "raw"
        self.output = SiteOutput(root / "site" / "data")
        self.source = FakeSource()
        self.indices = FakeIndices()
        exclude = int(QcFlag.DEFAULT_EXCLUDE)
        self.builder = SiteBuilder(
            self.source,
            self.indices,
            SensorSiteBuilder(
                DailyAggregation(PRAGUE, 1830.0, exclude, int(QcFlag.PRE_DEPLOYMENT)),
                SummaryBuilder(PRAGUE, exclude),
                default_sensor_writers(SiteEventMapping([EventKind.OFF_SITE])),
            ),
            default_site_writers(129_600.0),
            StoreFingerprints(self.raw),
            StateFile(root / "derived" / STATE_FILE),
            lambda: self.now,
        )
        self.now = NOW
        self.statuses: dict[SensorId, str] = {}

    def add(self, sensor_id: SensorId, times: list[str], temps: list[float]) -> None:
        """Store (a stand-in file) and register a SYNTHETIC series."""
        self.source.results[sensor_id] = result(
            series(times, temps, [70.0] * len(temps), sensor_id=sensor_id)
        )
        directory = self.raw / str(sensor_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "2026.csv").write_text(repr((times, temps)), encoding="utf-8")
        self.statuses[sensor_id] = "active"

    def inputs(self, settings: str = "s1") -> SiteInputs:
        return SiteInputs(dict(self.statuses), REGISTRY, settings, PRAGUE)

    def files(self) -> dict[str, bytes]:
        root = self.output.root
        return {
            p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()
        }


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    made = Rig(tmp_path)
    made.add(SENSOR, ["2026-06-01T10:00:00", "2026-07-01T10:00:00"], [10.0, 20.0])
    made.add(OTHER, ["2026-06-01T10:00:00"], [15.0])
    return made


def test_first_build_is_full(rig: Rig) -> None:
    report = rig.builder.build(rig.output, rig.inputs())
    assert report.full
    assert report.built == (SENSOR, OTHER)
    assert report.reused == ()
    assert report.seasons == (2026,)
    assert report.failures == ()
    indices = json.loads(rig.files()["indices/2026.json"])
    assert indices["sensors"]["77678271"]["mean_t"]["value"] == 15.0
    assert STATE_FILE not in rig.files()  # the state is kept outside the published data
    assert rig.builder._state_file.path.is_file()


def test_unchanged_sensors_are_reused(rig: Rig) -> None:
    rig.builder.build(rig.output, rig.inputs())
    before = rig.files()
    rig.source.calls.clear()
    report = rig.builder.build(rig.output, rig.inputs())
    assert not report.full
    assert report.built == ()
    assert set(report.reused) == {SENSOR, OTHER}
    assert report.written == ()
    assert rig.source.calls == []
    assert rig.files() == before


def test_a_changed_sensor_is_rebuilt_alone(rig: Rig) -> None:
    rig.builder.build(rig.output, rig.inputs())
    rig.add(OTHER, ["2026-06-01T10:00:00", "2026-06-01T10:30:30"], [15.0, 17.0])
    rig.indices.calls.clear()
    report = rig.builder.build(rig.output, rig.inputs())
    assert report.built == (OTHER,)
    assert report.reused == (SENSOR,)
    assert rig.indices.calls == [(2026, (OTHER,))]
    assert set(report.written) == {
        "series/77680921/raw/2026-06.json",
        "series/77680921/daily.json",
        "manifest.json",
        "latest.json",
        "indices/2026.json",
    }
    indices = json.loads(rig.files()["indices/2026.json"])["sensors"]
    assert (indices["77678271"]["mean_t"]["value"], indices["77680921"]["mean_t"]["value"]) == (
        15.0,
        16.0,
    )


def test_tampered_output_is_rebuilt(rig: Rig) -> None:
    rig.builder.build(rig.output, rig.inputs())
    (rig.output.root / "series" / "77678271" / "daily.json").unlink()
    report = rig.builder.build(rig.output, rig.inputs())
    assert report.built == (SENSOR,)
    assert (rig.output.root / "series" / "77678271" / "daily.json").exists()


def test_changed_settings_or_full_rebuild_everything(rig: Rig) -> None:
    rig.builder.build(rig.output, rig.inputs())
    assert rig.builder.build(rig.output, rig.inputs("s2")).full
    report = rig.builder.build(rig.output, rig.inputs("s2"), full=True)
    assert report.full
    assert set(report.built) == {SENSOR, OTHER}


def test_new_seasons_rebuild_every_sensor(rig: Rig) -> None:
    rig.builder.build(rig.output, rig.inputs())
    report = rig.builder.build(rig.output, rig.inputs(), seasons=[2026, 2025, 2026])
    assert report.seasons == (2025, 2026)
    assert set(report.built) == {SENSOR, OTHER}
    assert json.loads(rig.files()["indices/2025.json"])["sensors"] == {}
    again = rig.builder.build(rig.output, rig.inputs(), seasons=[2025, 2026])
    assert again.built == ()


def test_a_removed_sensor_is_pruned(rig: Rig) -> None:
    rig.builder.build(rig.output, rig.inputs())
    del rig.statuses[OTHER]
    report = rig.builder.build(rig.output, rig.inputs())
    assert "events/77680921.json" in report.removed
    assert not (rig.output.root / "series" / "77680921").exists()
    assert "77680921" not in json.loads(rig.files()["manifest.json"])["sensors"]


def test_failed_sensor_keeps_its_previous_output(rig: Rig) -> None:
    rig.builder.build(rig.output, rig.inputs())
    before = rig.files()
    rig.add(OTHER, ["2026-06-01T10:00:00", "2026-06-01T10:30:30"], [15.0, 17.0])
    rig.source.failing.add(OTHER)
    report = rig.builder.build(rig.output, rig.inputs())
    assert report.failures == ("site 77680921: synthetic failure of 77680921",)
    assert rig.files()["series/77680921/daily.json"] == before["series/77680921/daily.json"]
    # The old fingerprint stays in the state, so the next build tries again.
    rig.source.failing.clear()
    assert rig.builder.build(rig.output, rig.inputs()).built == (OTHER,)


def test_failed_sensor_survives_a_full_build(rig: Rig) -> None:
    """Reviewer's reproduction: a broken store file, then a changed off-site log (full build)."""
    rig.builder.build(rig.output, rig.inputs())
    before = rig.files()
    rig.add(OTHER, ["2026-06-01T10:00:00", "2026-06-01T10:30:30"], [15.0, 17.0])
    rig.source.failing.add(OTHER)
    rig.now = datetime(2026, 10, 6, 4, 0, tzinfo=UTC)
    assert rig.builder.build(rig.output, rig.inputs()).failures
    for settings, full in (("s2", False), ("s2", True)):
        report = rig.builder.build(rig.output, rig.inputs(settings), full=full)
        assert report.full
        assert report.failures == ("site 77680921: synthetic failure of 77680921",)
        assert report.removed == ()
        files = rig.files()
        for path in ("series/77680921/daily.json", "events/77680921.json"):
            assert files[path] == before[path]
        manifest = json.loads(files["manifest.json"])["sensors"]
        assert manifest["77680921"]["data_status"] == "error"
        assert manifest["77680921"]["last_built_at"] == "2026-10-05T04:00:00Z"
        assert "data_status" not in manifest["77678271"]
        indices = json.loads(files["indices/2026.json"])["sensors"]
        assert indices["77680921"]["mean_t"]["value"] == 15.0


def test_failed_sensor_is_retried_until_it_succeeds(rig: Rig) -> None:
    rig.builder.build(rig.output, rig.inputs())
    rig.source.failing.add(OTHER)
    rig.builder.build(rig.output, rig.inputs(), full=True)
    rig.source.calls.clear()
    # Same fingerprint as the earlier successful build, but the failure is never reused.
    again = rig.builder.build(rig.output, rig.inputs())
    assert again.failures
    assert rig.source.calls == [OTHER]
    rig.source.failing.clear()
    fixed = rig.builder.build(rig.output, rig.inputs())
    assert (fixed.built, fixed.failures) == ((OTHER,), ())
    assert "data_status" not in json.loads(rig.files()["manifest.json"])["sensors"]["77680921"]


def test_failed_index_is_retried_and_fails_every_run(rig: Rig) -> None:
    rig.indices.fail_for.add(SENSOR)
    for expected in ((SENSOR, OTHER), (SENSOR,)):
        report = rig.builder.build(rig.output, rig.inputs())
        assert report.built == expected
        assert report.failures == ("indices 77678271 mean_t: synthetic",)
    rig.indices.fail_for.clear()
    fixed = rig.builder.build(rig.output, rig.inputs())
    assert (fixed.built, fixed.failures) == ((SENSOR,), ())
    assert "77678271" in json.loads(rig.files()["indices/2026.json"])["sensors"]
    assert rig.builder.build(rig.output, rig.inputs()).built == ()


def test_failed_new_sensor_is_not_published(rig: Rig) -> None:
    rig.source.failing.add(OTHER)
    report = rig.builder.build(rig.output, rig.inputs())
    assert report.built == (SENSOR,)
    assert list(json.loads(rig.files()["manifest.json"])["sensors"]) == ["77678271"]


def test_index_failures_are_reported(rig: Rig) -> None:
    rig.indices.fail_for.add(SENSOR)
    report = rig.builder.build(rig.output, rig.inputs())
    assert report.failures == ("indices 77678271 mean_t: synthetic",)
    assert list(json.loads(rig.files()["indices/2026.json"])["sensors"]) == ["77680921"]


def test_given_qc_results_are_used(rig: Rig) -> None:
    given = {SENSOR: rig.source.results[SENSOR]}
    rig.builder.build(rig.output, rig.inputs(), checked=given)
    assert rig.source.calls == [OTHER]


def test_sensor_without_rows_is_not_published(rig: Rig) -> None:
    rig.source.results[OTHER] = result(series([], [], [], sensor_id=OTHER))
    report = rig.builder.build(rig.output, rig.inputs())
    assert report.built == (SENSOR,)
    assert not any(path.startswith("series/77680921") for path in rig.files())


def test_no_sensors(tmp_path: Path) -> None:
    empty = Rig(tmp_path)
    report = empty.builder.build(empty.output, empty.inputs())
    assert report.seasons == ()
    assert sorted(empty.files()) == ["latest.json", "manifest.json", "sensors.geojson"]
