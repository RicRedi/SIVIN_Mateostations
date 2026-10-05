"""The committed JSON Schema must equal the one generated from the models."""

from __future__ import annotations

import json
from pathlib import Path

from sivin.registry.model import UTC_TIMESTAMP_PATTERN
from sivin.registry.schema import JSON_SCHEMA_DIALECT, build_json_schema, render_json_schema

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "sensors" / "sensors.schema.json"


def test_committed_schema_is_in_sync() -> None:
    # Regenerate with:
    # .venv/bin/python -c "from sivin.registry.schema import render_json_schema as r; \
    #   open('sensors/sensors.schema.json', 'w', encoding='utf-8').write(r())"
    assert SCHEMA_FILE.read_text(encoding="utf-8") == render_json_schema()


def test_schema_uses_file_keys() -> None:
    schema = build_json_schema()
    assert schema["$schema"] == JSON_SCHEMA_DIALECT
    placement = schema["$defs"]["Placement"]
    assert list(placement["properties"]) == ["from", "to", "lon", "lat", "elevation_m", "note"]
    assert placement["required"] == ["from", "to", "lon", "lat", "elevation_m", "note"]
    sensor = schema["$defs"]["Sensor"]
    assert sensor["required"] == list(sensor["properties"])
    assert sensor["properties"]["portal_name"] == {
        "description": "Device name in the provider's portal, e.g. '8615620 77678271'.",
        "minLength": 1,
        "title": "Portal Name",
        "type": "string",
    }
    assert placement["properties"]["from"]["pattern"] == UTC_TIMESTAMP_PATTERN
    assert placement["properties"]["to"]["anyOf"] == [
        {"format": "date-time", "pattern": UTC_TIMESTAMP_PATTERN, "type": "string"},
        {"type": "null"},
    ]
    assert placement["additionalProperties"] is False
    sensor_id = schema["$defs"]["Sensor"]["properties"]["id"]
    assert sensor_id["pattern"] == "^[0-9]{8}$"
    assert "\n" not in schema["$defs"]["Sensor"]["description"]


def test_rendered_schema_is_json() -> None:
    assert json.loads(render_json_schema()) == build_json_schema()
