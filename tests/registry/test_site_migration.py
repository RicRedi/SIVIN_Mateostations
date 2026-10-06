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

    @pytest.mark.parametrize(
        ("present", "fix"),
        [
            (("municipality",), "remove 'site' and add 'track' (null if unknown)"),
            (("track",), "remove 'site' and add 'municipality' (null if unknown)"),
            (("municipality", "track"), "remove 'site'"),
        ],
    )
    def test_site_together_with_a_new_key_names_the_fix(
        self, make_sensor: SensorFactory, present: tuple[str, ...], fix: str
    ) -> None:
        document = _old_properties(make_sensor, "x") | {key: None for key in present}
        with pytest.raises(ValidationError) as caught:
            Sensor.model_validate(document)
        (error,) = caught.value.errors()
        assert error["msg"].endswith(fix)
        assert "replaced by 'municipality' and 'track'" in error["msg"]

    @pytest.mark.parametrize("site", ["", "   ", 7])
    def test_bad_site_value_is_reported_on_site(
        self, make_sensor: SensorFactory, site: object
    ) -> None:
        with pytest.raises(ValidationError) as caught:
            Sensor.model_validate(_old_properties(make_sensor, None) | {"site": site})
        (error,) = caught.value.errors()
        assert (
            "'site' (deprecated, read as 'track') must be a non-empty string or null"
            in (error["msg"])
        )
        assert "track" not in [str(part) for part in error["loc"]]

    def test_site_value_is_normalised(self, make_sensor: SensorFactory) -> None:
        sensor = Sensor.model_validate(_old_properties(make_sensor, "  Trať   1 "))
        assert sensor.track == "Trať 1"

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

    def test_committed_registry_has_the_owner_supplied_municipality_and_track(self) -> None:
        """Values supplied by the owner on 2026-10-06; nothing is guessed from the coordinates."""
        properties = [
            feature["properties"]
            for feature in json.loads(COMMITTED_REGISTRY.read_text(encoding="utf-8"))["features"]
        ]
        assert {p["id"]: (p["municipality"], p["track"]) for p in properties} == {
            "77678271": ("Dolní Věstonice", "Nad Silnicí"),
            "77680921": ("Dolní Věstonice", "Nad Silnicí"),
            "77800065": ("Dolní Věstonice", "Nad Silnicí"),
            "77799986": ("Dolní Věstonice", "U Kapličky"),
        }
        assert all("site" not in p for p in properties)


class TestWhitespace:
    @pytest.mark.parametrize("key", ["label", "municipality", "track", "variety"])
    def test_names_are_stripped_and_collapsed_with_a_warning(
        self, make_sensor: SensorFactory, key: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        document = make_sensor().model_dump() | {key: "  Obec \t A  (synthetic) "}
        with caplog.at_level(logging.WARNING, logger="sivin.registry.sensor_input"):
            sensor = Sensor.model_validate(document)
        assert getattr(sensor, key) == "Obec A (synthetic)"
        assert f"'{key}' '  Obec \\t A  (synthetic) ' has extra whitespace" in caplog.text
        assert "11112222" in caplog.text

    def test_clean_names_do_not_warn(
        self, make_sensor: SensorFactory, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            make_sensor(municipality="Obec A", track="Trať 1")
        assert caplog.text == ""

    def test_whitespace_only_is_rejected(self, make_sensor: SensorFactory) -> None:
        with pytest.raises(ValidationError, match="municipality"):
            Sensor.model_validate(make_sensor().model_dump() | {"municipality": "   "})

    def test_file_with_padded_names_saves_cleaned(
        self, make_sensor: SensorFactory, tmp_path: Path
    ) -> None:
        properties = make_sensor().model_dump(mode="json") | {"municipality": "Mikulov "}
        path = _old_file(tmp_path, properties)
        store = GeoJsonRegistryStore()
        store.save(store.load(path), path)
        saved = json.loads(path.read_text(encoding="utf-8"))["features"][0]["properties"]
        assert saved["municipality"] == "Mikulov"


def test_non_mapping_input_is_left_to_pydantic() -> None:
    with pytest.raises(ValidationError, match="valid dictionary"):
        Sensor.model_validate("not a sensor")
