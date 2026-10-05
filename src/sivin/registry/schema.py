"""JSON Schema of the registry file, generated from the pydantic models.

``sensors/sensors.schema.json`` is the output of :func:`render_json_schema`; a test keeps the
committed file equal to it. The schema describes the structure of the file (types, required
keys, ranges). Rules that relate several values (placement order and overlaps, status versus
open placement, unique ids, allowed area, geometry equal to the last placement) are checked by
:class:`~sivin.registry.geojson.GeoJsonRegistryStore` and documented in ``docs/sensors.md``.
"""

from __future__ import annotations

from typing import Any, Final

from sivin.registry.geojson import SensorCollection, render_json

JSON_SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
"""JSON Schema dialect emitted by pydantic v2."""

SCHEMA_TITLE: Final = "SIVIN sensor registry"
"""Title of the generated schema."""

SCHEMA_DESCRIPTION: Final = (
    "sensors/sensors.geojson: one GeoJSON Point feature per sensor with its placement history "
    "(MIGRATION_PLAN §2.4). Generated from sivin.registry; do not edit by hand."
)
"""Description of the generated schema."""


def build_json_schema() -> dict[str, Any]:
    """Build the JSON Schema of the registry file.

    Returns
    -------
    dict
        JSON Schema (draft 2020-12) of :class:`~sivin.registry.geojson.SensorCollection`,
        using the file's keys (``from``, ``to``, ``lon``, ``lat``).
    """
    generated = SensorCollection.model_json_schema(by_alias=True, mode="validation")
    for definition in generated.get("$defs", {}).values():
        definition["description"] = _summary(definition.get("description", ""))
    generated["title"] = SCHEMA_TITLE
    generated["description"] = SCHEMA_DESCRIPTION
    return {"$schema": JSON_SCHEMA_DIALECT, **generated}


def _summary(docstring: str) -> str:
    """Keep the first paragraph of a class docstring (drop the NumPy sections)."""
    return docstring.split("\n\n", 1)[0].replace("\n", " ")


def render_json_schema() -> str:
    """Render :func:`build_json_schema` as the canonical text of ``sensors.schema.json``.

    Returns
    -------
    str
        JSON text with 2-space indentation and a trailing newline.
    """
    return render_json(build_json_schema())
