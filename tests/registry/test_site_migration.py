"""The registry keys ``municipality`` and ``track`` replace ``site`` (owner decision 2026-10-05).

All sensors and names here are synthetic.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from sivin.registry.errors import RegistryFormatError
from sivin.registry.geojson import GeoJsonRegistryStore
from sivin.registry.model import Sensor

from .conftest import SensorFactory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_REGISTRY = PROJECT_ROOT / "sensors" / "sensors.geojson"


def _old_properties(make_sensor: SensorFactory, site: str | None) -> dict[str, Any]:
    """Properties of a sensor as written before 2026-10-05: ``site`` instead of the new keys."""
    properties = make_sensor().model_dump(mode="json")
    del properties["municipality"], properties["track"]
    return properties | {"site": site}


def _old_file(tmp_path: Path, properties: dict[str, Any]) -> Path:
    last = properties["placements"][-1]
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [last["lon"], last["lat"]]},
                "properties": properties,
            }
        ],
    }
    path = tmp_path / "old.geojson"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class TestModel:
    def test_new_keys_in_file_order(self, make_sensor: SensorFactory) -> None:
        sensor = make_sensor(municipality="Obec A (synthetic)", track="Trať 1 (synthetic)")
        keys = list(sensor.model_dump(mode="json"))
        assert keys[keys.index("label") :][:4] == ["label", "municipality", "track", "variety"]
        assert (sensor.municipality, sensor.track) == ("Obec A (synthetic)", "Trať 1 (synthetic)")

    @pytest.mark.parametrize("key", ["municipality", "track"])
    def test_empty_string_rejected(self, make_sensor: SensorFactory, key: str) -> None:
        document = make_sensor().model_dump() | {key: ""}
        with pytest.raises(ValidationError, match=key):
            Sensor.model_validate(document)

    def test_site_is_read_as_track_with_a_warning(
        self, make_sensor: SensorFactory, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="sivin.registry.model"):
            sensor = Sensor.model_validate(_old_properties(make_sensor, "Trať 1 (synthetic)"))
        assert sensor.track == "Trať 1 (synthetic)"
        assert sensor.municipality is None
        assert "'site' is deprecated" in caplog.text
        assert "11112222" in caplog.text
        assert "site" not in sensor.model_dump()

    def test_null_site_is_read_as_null_track(self, make_sensor: SensorFactory) -> None:
        sensor = Sensor.model_validate(_old_properties(make_sensor, None))
        assert (sensor.municipality, sensor.track) == (None, None)

    @pytest.mark.parametrize("key", ["municipality", "track"])
    def test_site_together_with_a_new_key_is_an_error(
        self, make_sensor: SensorFactory, key: str
    ) -> None:
        document = make_sensor().model_dump() | {"site": "x"}
        if key == "municipality":
            del document["track"]
        else:
            del document["municipality"]
        with pytest.raises(ValidationError, match=rf"remove 'site'.*'{key}'"):
            Sensor.model_validate(document)

    def test_replaced_with_site_is_an_error(self, make_sensor: SensorFactory) -> None:
        with pytest.raises(ValidationError, match="replaced by 'municipality' and 'track'"):
            make_sensor().replaced(site="x")


class TestFile:
    def test_old_file_loads_and_saves_with_new_keys(
        self, make_sensor: SensorFactory, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        store = GeoJsonRegistryStore()
        path = _old_file(tmp_path, _old_properties(make_sensor, "Trať 2 (synthetic)"))
        with caplog.at_level(logging.WARNING):
            registry = store.load(path)
        assert "deprecated" in caplog.text
        store.save(registry, path)
        properties = json.loads(path.read_text(encoding="utf-8"))["features"][0]["properties"]
        assert "site" not in properties
        assert properties["municipality"] is None
        assert properties["track"] == "Trať 2 (synthetic)"

    def test_mixed_old_and_new_keys_name_the_sensor(
        self, make_sensor: SensorFactory, tmp_path: Path
    ) -> None:
        properties = make_sensor().model_dump(mode="json") | {"site": "x"}
        with pytest.raises(RegistryFormatError, match=r"features\.0\.properties: .*remove 'site'"):
            GeoJsonRegistryStore().load(_old_file(tmp_path, properties))

    def test_loads_bytes(self, make_sensor: SensorFactory, tmp_path: Path) -> None:
        store = GeoJsonRegistryStore()
        path = _old_file(tmp_path, make_sensor().model_dump(mode="json"))
        assert store.loads(path.read_bytes()) == store.load(path)
        with pytest.raises(RegistryFormatError, match="Invalid sensor registry inline"):
            store.loads(b"{}", "inline")

    def test_committed_registry_has_null_municipality_and_track(self) -> None:
        """The owner fills them in; nothing is guessed from the coordinates."""
        properties = [
            feature["properties"]
            for feature in json.loads(COMMITTED_REGISTRY.read_text(encoding="utf-8"))["features"]
        ]
        assert all(p["municipality"] is None and p["track"] is None for p in properties)
        assert all("site" not in p for p in properties)
