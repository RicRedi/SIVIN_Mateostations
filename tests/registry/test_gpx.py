"""Tests of GpxImporter (synthetic GPX documents and the repository's sensor_location.gpx)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from sivin.core.ids import SensorId
from sivin.registry.errors import GpxFormatError
from sivin.registry.gpx import GpxImporter, GpxWaypoint

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOYED = datetime(2025, 12, 1, tzinfo=UTC)

GPX_11 = """<?xml version="1.0" encoding="utf-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="synthetic">
  <wpt lat="48.81" lon="16.61"><ele>201.5</ele><name>11112222 (synthetic)</name></wpt>
  <wpt lat="48.82" lon="16.62"><name> 33334444 </name></wpt>
</gpx>
"""
"""Synthetic GPX 1.1 with two waypoints, one without elevation."""


def _gpx(tmp_path: Path, text: str, name: str = "synthetic.gpx") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_waypoints_namespace_aware(tmp_path: Path) -> None:
    waypoints = GpxImporter("8615620").waypoints(_gpx(tmp_path, GPX_11))
    assert waypoints == (
        GpxWaypoint("11112222 (synthetic)", 48.81, 16.61, 201.5),
        GpxWaypoint("33334444", 48.82, 16.62, None),
    )


def test_waypoints_without_namespace(tmp_path: Path) -> None:
    text = '<gpx><wpt lat="48.81" lon="16.61"><name>11112222</name></wpt></gpx>'
    assert len(GpxImporter("8615620").waypoints(_gpx(tmp_path, text))) == 1


def test_read_builds_sensors(tmp_path: Path) -> None:
    sensors = GpxImporter(portal_prefix="8615620").read(_gpx(tmp_path, GPX_11), DEPLOYED)
    first, second = sensors
    assert first.id == SensorId("11112222")
    assert first.label == "11112222 (synthetic)"
    assert first.portal_name == "8615620 11112222"
    assert first.status == "active"
    (placement,) = first.placements
    assert placement.from_utc == DEPLOYED
    assert placement.to_utc is None
    assert (placement.lat_deg, placement.lon_deg, placement.elevation_m) == (48.81, 16.61, 201.5)
    assert placement.note == "imported from synthetic.gpx"
    assert second.placements[0].elevation_m is None


def test_read_with_note_suffix(tmp_path: Path) -> None:
    sensors = GpxImporter("1").read(_gpx(tmp_path, GPX_11), DEPLOYED, note_suffix="placeholder")
    assert sensors[0].portal_name == "1 11112222"
    assert sensors[0].placements[0].note == "imported from synthetic.gpx; placeholder"


def test_read_repository_gpx() -> None:
    sensors = GpxImporter(portal_prefix="8615620").read(
        PROJECT_ROOT / "sensor_location.gpx", DEPLOYED
    )
    assert [str(s.id) for s in sensors] == ["77678271", "77680921", "77800065", "77799986"]
    assert sensors[0].placements[0].elevation_m == 183.939606


@pytest.mark.parametrize("prefix", ["", "86 15620", "abc"])
def test_rejects_bad_prefix(prefix: str) -> None:
    with pytest.raises(ValueError, match="digits"):
        GpxImporter(portal_prefix=prefix)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("<gpx><wpt", "Cannot read GPX"),
        ("<kml/>", "not a GPX file"),
        ('<gpx><wpt lat="48.8" lon="16.6"/></gpx>', "has no <name>"),
        ('<gpx><wpt lat="48.8"><name>11112222</name></wpt></gpx>', "missing or invalid"),
        ('<gpx><wpt lat="x" lon="16.6"><name>11112222</name></wpt></gpx>', "missing or invalid"),
        (
            '<gpx><wpt lat="48.8" lon="16.6"><ele>high</ele><name>11112222</name></wpt></gpx>',
            "missing or invalid",
        ),
    ],
)
def test_rejects_broken_gpx(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(GpxFormatError, match=message):
        GpxImporter("8615620").waypoints(_gpx(tmp_path, text))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GpxFormatError, match="Cannot read GPX"):
        GpxImporter("8615620").waypoints(tmp_path / "missing.gpx")


def test_name_without_sensor_id(tmp_path: Path) -> None:
    text = '<gpx><wpt lat="48.8" lon="16.6"><name>Kostel</name></wpt></gpx>'
    with pytest.raises(ValueError, match="Cannot recognise"):
        GpxImporter("8615620").read(_gpx(tmp_path, text), DEPLOYED)


def test_naive_deployment_instant(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="timezone"):
        GpxImporter("8615620").read(_gpx(tmp_path, GPX_11), datetime(2025, 12, 1))
