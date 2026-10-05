"""Tests of GeoJsonRegistryStore and of the committed registry file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sivin.core.ids import SensorId
from sivin.registry.errors import RegistryError, RegistryFormatError
from sivin.registry.geojson import GeoJsonRegistryStore, render_json
from sivin.registry.registry import SensorRegistry
from sivin.registry.settings import CZECH_REPUBLIC, RegistrySettings

from .conftest import T_2026_03_01, PlacementFactory, SensorFactory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_REGISTRY = PROJECT_ROOT / "sensors" / "sensors.geojson"

GPX_SENSORS = {
    # serial: (lon_deg, lat_deg, elevation_m), copied by hand from sensor_location.gpx
    "77678271": (16.673002, 48.880215, 183.939606),
    "77680921": (16.672016, 48.879593, 201.622162),
    "77800065": (16.670900, 48.878895, 222.397003),
    "77799986": (16.648304, 48.883827, 219.241791),
}

SYNTHETIC_FILE = """\
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [
          16.61,
          48.81
        ]
      },
      "properties": {
        "id": "11112222",
        "portal_name": "8615620 11112222",
        "label": "11112222 (synthetic)",
        "site": "Synthetic site",
        "variety": "Ryzlink rýnský",
        "status": "active",
        "placements": [
          {
            "from": "2025-12-01T00:00:00Z",
            "to": "2026-03-01T00:00:00Z",
            "lon": 16.6,
            "lat": 48.8,
            "elevation_m": null,
            "note": null
          },
          {
            "from": "2026-03-01T00:00:00Z",
            "to": null,
            "lon": 16.61,
            "lat": 48.81,
            "elevation_m": 201.5,
            "note": "moved"
          }
        ],
        "notes": "synthetic"
      }
    }
  ]
}
"""
"""A synthetic registry file in canonical form (hand-written)."""


@pytest.fixture
def store() -> GeoJsonRegistryStore:
    return GeoJsonRegistryStore()


def _write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "sensors.geojson"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _synthetic_document() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(SYNTHETIC_FILE)
    return document


class TestRoundTrip:
    def test_synthetic_file_is_byte_identical(
        self, store: GeoJsonRegistryStore, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.geojson"
        source.write_bytes(SYNTHETIC_FILE.encode("utf-8"))
        registry = store.load(source)
        target = tmp_path / "out.geojson"
        store.save(registry, target)
        assert target.read_bytes() == source.read_bytes()
        assert not list(tmp_path.glob(".*.tmp"))

    def test_committed_file_is_byte_identical(
        self, store: GeoJsonRegistryStore, tmp_path: Path
    ) -> None:
        target = tmp_path / "sensors.geojson"
        store.save(store.load(COMMITTED_REGISTRY), target)
        assert target.read_bytes() == COMMITTED_REGISTRY.read_bytes()

    def test_saved_registry_loads_equal(
        self,
        store: GeoJsonRegistryStore,
        tmp_path: Path,
        make_sensor: SensorFactory,
        make_placement: PlacementFactory,
    ) -> None:
        registry = SensorRegistry(
            [make_sensor(), make_sensor("33334444", status="inactive")], area=CZECH_REPUBLIC
        ).with_moved(SensorId("11112222"), make_placement(from_utc=T_2026_03_01, lat_deg=48.9))
        path = tmp_path / "sensors.geojson"
        store.save(registry, path)
        assert store.load(path) == registry

    def test_geometry_is_last_placement(self, store: GeoJsonRegistryStore, tmp_path: Path) -> None:
        source = tmp_path / "in.geojson"
        source.write_text(SYNTHETIC_FILE, encoding="utf-8")
        document = json.loads(store.dumps(store.load(source)))
        assert document["features"][0]["geometry"]["coordinates"] == [16.61, 48.81]

    def test_save_failure_leaves_no_temporary(
        self, store: GeoJsonRegistryStore, tmp_path: Path
    ) -> None:
        target = tmp_path / "is_a_directory"
        (target / "child").mkdir(parents=True)
        with pytest.raises(OSError, match="directory"):
            store.save(SensorRegistry(), target)
        assert not (tmp_path / ".is_a_directory.tmp").exists()


class TestCommittedRegistry:
    """sensors/sensors.geojson must hold the four sensors of sensor_location.gpx."""

    def test_four_sensors_from_gpx(self, store: GeoJsonRegistryStore) -> None:
        registry = store.load(COMMITTED_REGISTRY)
        assert {str(i) for i in registry.ids()} == set(GPX_SENSORS)
        for sensor in registry:
            lon_deg, lat_deg, elevation_m = GPX_SENSORS[str(sensor.id)]
            placement = sensor.placements[0]
            assert (placement.lon_deg, placement.lat_deg) == (lon_deg, lat_deg)
            assert placement.elevation_m == elevation_m
            assert sensor.portal_name == f"8615620 {sensor.id}"
            assert sensor.label == f"{sensor.id} (VUT)"
            assert sensor.is_active


class TestInvalidFiles:
    def test_missing_file(self, store: GeoJsonRegistryStore, tmp_path: Path) -> None:
        with pytest.raises(RegistryFormatError, match="Cannot read"):
            store.load(tmp_path / "missing.geojson")

    def test_not_json(self, store: GeoJsonRegistryStore, tmp_path: Path) -> None:
        path = tmp_path / "bad.geojson"
        path.write_text("{", encoding="utf-8")
        with pytest.raises(RegistryFormatError, match="<root>"):
            store.load(path)

    def test_names_the_key_path(self, store: GeoJsonRegistryStore, tmp_path: Path) -> None:
        document = _synthetic_document()
        document["features"][0]["properties"]["placements"][0]["lat"] = 91.0
        with pytest.raises(
            RegistryFormatError, match=r"features\.0\.properties\.placements\.0\.lat"
        ):
            store.load(_write(tmp_path, document))

    def test_unknown_key(self, store: GeoJsonRegistryStore, tmp_path: Path) -> None:
        document = _synthetic_document()
        document["features"][0]["properties"]["colour"] = "red"
        with pytest.raises(RegistryFormatError, match="colour"):
            store.load(_write(tmp_path, document))

    def test_overlapping_placements(self, store: GeoJsonRegistryStore, tmp_path: Path) -> None:
        document = _synthetic_document()
        document["features"][0]["properties"]["placements"][0]["to"] = "2026-03-02T00:00:00Z"
        with pytest.raises(RegistryFormatError, match="overlap"):
            store.load(_write(tmp_path, document))

    def test_open_placement_not_last(self, store: GeoJsonRegistryStore, tmp_path: Path) -> None:
        document = _synthetic_document()
        document["features"][0]["properties"]["placements"][0]["to"] = None
        with pytest.raises(RegistryFormatError, match="not the last"):
            store.load(_write(tmp_path, document))

    @pytest.mark.parametrize(
        ("key", "value"),
        [("portal_name", None), ("portal_name", ...), ("site", ...), ("notes", ...)],
    )
    def test_sensor_keys_required_and_portal_name_not_null(
        self, store: GeoJsonRegistryStore, tmp_path: Path, key: str, value: object
    ) -> None:
        document = _synthetic_document()
        properties = document["features"][0]["properties"]
        if value is ...:
            del properties[key]
        else:
            properties[key] = value
        with pytest.raises(RegistryFormatError, match=rf"features\.0\.properties\.{key}"):
            store.load(_write(tmp_path, document))

    @pytest.mark.parametrize("key", ["to", "elevation_m", "note"])
    def test_placement_keys_required(
        self, store: GeoJsonRegistryStore, tmp_path: Path, key: str
    ) -> None:
        document = _synthetic_document()
        del document["features"][0]["properties"]["placements"][1][key]
        with pytest.raises(RegistryFormatError, match=rf"placements\.1\.{key}"):
            store.load(_write(tmp_path, document))

    def test_offset_other_than_z_rejected(
        self, store: GeoJsonRegistryStore, tmp_path: Path
    ) -> None:
        document = _synthetic_document()
        document["features"][0]["properties"]["placements"][1]["from"] = "2026-03-01T01:00:00+01:00"
        with pytest.raises(RegistryFormatError, match="UTC with 'Z'"):
            store.load(_write(tmp_path, document))

    def test_duplicate_id(self, store: GeoJsonRegistryStore, tmp_path: Path) -> None:
        document = _synthetic_document()
        document["features"].append(document["features"][0])
        with pytest.raises(RegistryError, match="Duplicate sensor id 11112222"):
            store.load(_write(tmp_path, document))

    def test_geometry_differs_from_last_placement(
        self, store: GeoJsonRegistryStore, tmp_path: Path
    ) -> None:
        document = _synthetic_document()
        document["features"][0]["geometry"]["coordinates"] = [16.6, 48.8]
        with pytest.raises(RegistryFormatError, match="differs from its last placement"):
            store.load(_write(tmp_path, document))

    def test_outside_allowed_area(self, tmp_path: Path) -> None:
        document = _synthetic_document()
        placement = document["features"][0]["properties"]["placements"][1]
        placement["lat"], placement["lon"] = 16.61, 48.81
        document["features"][0]["geometry"]["coordinates"] = [48.81, 16.61]
        path = _write(tmp_path, document)
        with pytest.raises(RegistryError, match="outside the allowed area"):
            GeoJsonRegistryStore().load(path)
        unchecked = GeoJsonRegistryStore(RegistrySettings(allowed_area=None)).load(path)
        assert unchecked.area is None
        assert len(unchecked) == 1


def test_render_json_format() -> None:
    assert (
        render_json({"b": [1, None], "a": "č"})
        == '{\n  "b": [\n    1,\n    null\n  ],\n  "a": "č"\n}\n'
    )
    with pytest.raises(ValueError, match="Out of range"):
        render_json(float("nan"))
