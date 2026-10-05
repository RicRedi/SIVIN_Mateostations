"""Site-wide files and the build state (hand-computed; data synthetic)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.site.helpers import OTHER, SENSOR

from sivin.site.files import SiteFile
from sivin.site.labels import IndexCatalog, IndexSpec
from sivin.site.model import LatestSample, PublishedSensor, SensorSummary, SiteSnapshot
from sivin.site.site_files import (
    LatestWriter,
    ManifestWriter,
    RegistryCopyWriter,
    SeasonIndicesWriter,
    default_site_writers,
)
from sivin.site.state import BuildState, SensorState, StoreFingerprints, fingerprint

GENERATED = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
GENERATED_S = 1_791_172_800
"""2026-10-05T04:00Z: 2026-01-01 (1 767 225 600) + 277 days + 4 h."""
STALE_AFTER_S = 129_600.0
HUGLIN = {"value": 1834.2, "unit": "°C·d", "coverage": 0.97, "complete": True,
          "class": "temperate_warm", "estimated": False}  # fmt: skip


def summary(latest_t: int | None) -> SensorSummary:
    latest = None if latest_t is None else LatestSample(latest_t, 12.4, 81.0, 0)
    return SensorSummary(1_780_272_000, GENERATED_S, ("2026-06",), latest, (2026,))


def snapshot(latest_a: int | None, latest_b: int | None) -> SiteSnapshot:
    return SiteSnapshot(
        GENERATED,
        "Europe/Prague",
        (
            PublishedSensor(SENSOR, "active", summary(latest_a), {2026: {"huglin": HUGLIN}}),
            PublishedSensor(OTHER, "retired", summary(latest_b)),
        ),
        (2025, 2026),
        (IndexSpec("huglin", "°C·d"),),
        b'{"type": "FeatureCollection", "features": []}\n',
    )


def test_hand_computed_generated_time() -> None:
    assert GENERATED_S == 1_767_225_600 + 277 * 86_400 + 4 * 3600


def test_manifest() -> None:
    (file,) = ManifestWriter(IndexCatalog()).files(snapshot(GENERATED_S, None))
    manifest = json.loads(file.content)
    assert file.path == "manifest.json"
    assert list(manifest) == [
        "schema_version", "generated_at", "display_timezone", "variables", "sensors",
        "seasons", "indices",
    ]  # fmt: skip
    assert manifest["schema_version"] == 1
    assert manifest["generated_at"] == "2026-10-05T04:00:00Z"
    assert manifest["sensors"]["77680921"] == {
        "first_t": 1_780_272_000,
        "last_t": GENERATED_S,
        "raw_months": ["2026-06"],
        "status": "retired",
    }
    assert manifest["seasons"] == [2025, 2026]
    assert [index["id"] for index in manifest["indices"]] == ["huglin"]


def test_latest_staleness_threshold() -> None:
    fresh_t = GENERATED_S - int(STALE_AFTER_S)  # exactly 36 h old: not yet stale
    (file,) = LatestWriter(STALE_AFTER_S).files(snapshot(fresh_t, fresh_t - 1))
    latest = json.loads(file.content)
    assert latest["generated_at"] == "2026-10-05T04:00:00Z"
    assert latest["sensors"]["77678271"] == {
        "t": fresh_t, "temp_c": 12.4, "rh_pct": 81.0, "qc": 0, "stale": False,
    }  # fmt: skip
    assert latest["sensors"]["77680921"]["stale"] is True


def test_latest_leaves_out_sensors_without_a_valid_sample() -> None:
    (file,) = LatestWriter(STALE_AFTER_S).files(snapshot(None, GENERATED_S))
    assert list(json.loads(file.content)["sensors"]) == ["77680921"]


def test_indices_per_season() -> None:
    files = SeasonIndicesWriter().files(snapshot(None, None))
    assert [file.path for file in files] == ["indices/2025.json", "indices/2026.json"]
    assert json.loads(files[0].content) == {
        "season": 2025, "computed_at": "2026-10-05T04:00:00Z", "sensors": {},
    }  # fmt: skip
    assert json.loads(files[1].content)["sensors"] == {"77678271": {"huglin": HUGLIN}}


def test_registry_is_copied_byte_for_byte() -> None:
    (file,) = RegistryCopyWriter().files(snapshot(None, None))
    assert file == SiteFile("sensors.geojson", b'{"type": "FeatureCollection", "features": []}\n')


def test_default_site_writers() -> None:
    paths = [
        f.path for w in default_site_writers(STALE_AFTER_S) for f in w.files(snapshot(None, None))
    ]
    assert paths == [
        "manifest.json", "sensors.geojson", "latest.json", "indices/2025.json", "indices/2026.json",
    ]  # fmt: skip


def test_fingerprint_is_unambiguous() -> None:
    assert fingerprint([b"ab", b"c"]) != fingerprint([b"a", b"bc"])
    assert fingerprint([]) == fingerprint([])


def test_store_fingerprints_follow_the_files(tmp_path: Path) -> None:
    fingerprints = StoreFingerprints(tmp_path / "raw")
    nothing = fingerprints.of(SENSOR)
    directory = tmp_path / "raw" / str(SENSOR)
    directory.mkdir(parents=True)
    (directory / "2026.csv").write_bytes(b"a")
    one = fingerprints.of(SENSOR)
    (directory / "2026.csv").write_bytes(b"b")
    changed = fingerprints.of(SENSOR)
    (directory / "2025.csv").write_bytes(b"a")
    assert len({nothing, one, changed, fingerprints.of(SENSOR)}) == 4
    assert fingerprints.of(OTHER) == nothing


def test_state_round_trip() -> None:
    sensor_state = SensorState.of(
        "abc",
        [SiteFile("events/77678271.json", b"{}\n")],
        summary(GENERATED_S),
        {2026: {"huglin": HUGLIN}},
    )
    state = BuildState("settings", (2025, 2026), {"77678271": sensor_state})
    parsed = BuildState.parse(state.to_file().content)
    assert parsed == state
    assert state.to_file().path == ".build-state.json"


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"[]",
        b'{"format": 1}',
        b'{"format": 1, "settings": "s", "seasons": [], "sensors": {"x": {}}}',
    ],
)
def test_unreadable_state_is_ignored(content: bytes) -> None:
    assert BuildState.parse(content) is None


def test_state_of_another_format_is_ignored() -> None:
    assert BuildState.parse(b'{"format": 99}') is None
    assert BuildState.parse(None) is None
