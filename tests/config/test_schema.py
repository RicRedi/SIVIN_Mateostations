"""JSON schema and Markdown reference of the configuration."""

from __future__ import annotations

import json

from sivin.analytics.base import index_registry
from sivin.config.schema import ConfigReference, ConfigSchema, ReferenceRow, _cell
from sivin.quality.checks.base import check_registry


def test_json_schema_lists_the_registered_settings() -> None:
    schema = ConfigSchema().json_schema()
    definitions = schema["$defs"]
    assert schema["title"] == "SivinConfig"
    assert set(schema["properties"]) == {
        "paths",
        "time",
        "registry",
        "offsite_log",
        "ingest",
        "storage",
        "quality",
        "alignment",
        "analytics",
        "site",
    }
    checks = definitions["QualityPipelineSettings"]["properties"]["check_settings"]
    assert set(checks["properties"]) == set(check_registry.ids())
    assert checks["additionalProperties"] is False
    assert checks["properties"]["battery"] == {"$ref": "#/$defs/BatterySettings"}
    indices = definitions["AnalyticsConfig"]["properties"]["indices"]
    assert set(indices["properties"]) == set(index_registry.ids())
    params = definitions["AlignmentConfig"]["properties"]["params"]
    assert {"$ref": "#/$defs/LinearParams"} in params["anyOf"]
    assert {"$ref": "#/$defs/NearestParams"} in params["anyOf"]
    assert "SivinConfig" not in definitions


def test_schema_text_is_json() -> None:
    text = ConfigSchema().text()
    assert text.endswith("}\n")
    assert json.loads(text)["title"] == "SivinConfig"


def test_reference_rows_cover_every_section_once() -> None:
    rows = ConfigReference().rows()
    paths = [row.path for row in rows]
    assert len(paths) == len(set(paths))
    sections = list(dict.fromkeys(path.split(".", 1)[0] for path in paths))
    assert sections == [
        "paths",
        "time",
        "registry",
        "offsite_log",
        "ingest",
        "storage",
        "quality",
        "alignment",
        "analytics",
        "site",
    ]
    by_path = {row.path: row for row in rows}
    assert by_path["time.expected_interval_s"].default == "`1830.0`"
    assert by_path["ingest.parsers.expected_interval_s"].default == "= `time.expected_interval_s`"
    assert by_path["quality.deployment.display_timezone"].default == "= `time.display_timezone`"
    assert by_path["quality.check_settings.battery.low_battery_v"].default == "`3.3`"
    assert by_path["analytics.indices.huglin.k_override"].default == "`null`"
    assert "alignment.params (linear_interpolation).max_gap_s" in by_path
    assert by_path["paths.data_dir"].description.startswith("Measurement store directory")


def test_reference_markdown_has_one_table_per_section() -> None:
    markdown = ConfigReference().markdown()
    assert markdown.startswith("### `paths`\n\n| Key | Default | Description |\n|---|---|---|\n")
    assert markdown.count("### `") == 10
    assert markdown.endswith("|\n")
    assert "| `analytics.indices.gsr.targets` | `[]` |" in markdown


def test_cells_are_escaped() -> None:
    assert _cell("a | b\nc") == "a \\| b c"
    row = ReferenceRow("x", "`1`", "d")
    assert (row.path, row.default, row.description) == ("x", "`1`", "d")
