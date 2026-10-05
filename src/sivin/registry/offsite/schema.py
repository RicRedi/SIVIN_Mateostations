"""JSON Schema of ``sensors/offsite_log.yaml``, generated from the pydantic models."""

from __future__ import annotations

from typing import Any, Final

from sivin.registry.geojson import render_json
from sivin.registry.offsite.model import OffSiteLogFile

SCHEMA_TITLE: Final = "SIVIN off-site log"
"""Title of the generated schema."""

SCHEMA_DESCRIPTION: Final = (
    "sensors/offsite_log.yaml: periods when a sensor was NOT measuring in the vineyard "
    "(MIGRATION_PLAN §2.8). Generated from sivin.registry.offsite; do not edit by hand."
)
"""Description of the generated schema."""

JSON_SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
"""JSON Schema dialect emitted by pydantic v2."""


def build_json_schema() -> dict[str, Any]:
    """Build the JSON Schema of the off-site log file.

    The schema checks the structure of every entry. Rules that relate entries (known sensor,
    no overlaps, open period last) and the daylight-saving checks of local times are applied
    by :class:`OffSiteLogStore` and documented in ``docs/sensors.md``.

    Returns
    -------
    dict
        JSON Schema (draft 2020-12) with the file's keys (``from``, ``to``).
    """
    generated = OffSiteLogFile.model_json_schema(by_alias=True, mode="validation")
    for definition in generated.get("$defs", {}).values():
        definition["description"] = definition.get("description", "").split("\n\n", 1)[0]
        definition["description"] = definition["description"].replace("\n", " ")
    generated["title"] = SCHEMA_TITLE
    generated["description"] = SCHEMA_DESCRIPTION
    return {"$schema": JSON_SCHEMA_DIALECT, **generated}


def render_json_schema() -> str:
    """Render :func:`build_json_schema` as the canonical text of ``offsite_log.schema.json``.

    Returns
    -------
    str
        JSON text with 2-space indentation and a trailing newline.
    """
    return render_json(build_json_schema())
