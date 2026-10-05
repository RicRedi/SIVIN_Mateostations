"""The public projection of the registry: internal notes are not published (synthetic data)."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from sivin.redaction import SecretRedactor
from sivin.registry.errors import RegistryFormatError
from sivin.registry.geojson import GeoJsonRegistryStore
from sivin.registry.model import Placement, Sensor
from sivin.registry.registry import SensorRegistry
from sivin.site.public_registry import PublicRegistryProjection
from sivin.site.site_files import PublicRegistryWriter

from .test_site_files import snapshot

SENSOR_NOTE = "internal: key under the third post (synthetic)"
PLACEMENT_NOTES = ("internal: moved after hail (synthetic)", "internal: borrowed pole (synthetic)")


def _placement(from_utc: str, to_utc: str | None, note: str) -> dict[str, Any]:
    return {"from": from_utc, "to": to_utc, "lon": 16.6, "lat": 48.8, "elevation_m": 200.0,
            "note": note}  # fmt: skip


def _sensor() -> Sensor:
    return Sensor.model_validate(
        {
            "id": "11112222",
            "portal_name": "8615620 11112222",
            "label": "11112222 (synthetic)",
            "municipality": "Obec A (synthetic)",
            "track": "Trať 1 (synthetic)",
            "variety": "Ryzlink rýnský",
            "status": "active",
            "placements": [
                _placement("2025-12-01T00:00:00Z", "2026-03-01T00:00:00Z", PLACEMENT_NOTES[0]),
                _placement("2026-03-01T00:00:00Z", None, PLACEMENT_NOTES[1]),
            ],
            "notes": SENSOR_NOTE,
        }
    )


def _registry_bytes() -> bytes:
    return GeoJsonRegistryStore().dumps(SensorRegistry([_sensor()])).encode("utf-8")


def test_sensor_projection_drops_only_the_notes() -> None:
    sensor = _sensor()
    public = PublicRegistryProjection.sensor(sensor)
    assert public.notes is None
    assert [p.note for p in public.placements] == [None, None]
    assert public.replaced(notes=SENSOR_NOTE, placements=sensor.placements) == sensor
    assert public.portal_name == "8615620 11112222"
    assert (public.municipality, public.track) == ("Obec A (synthetic)", "Trať 1 (synthetic)")


def test_placement_projection() -> None:
    placement = _sensor().placements[0]
    public = PublicRegistryProjection.placement(placement)
    assert public.note is None
    assert isinstance(public, Placement)
    assert public.model_dump() == placement.model_dump() | {"note": None}


def test_document_has_no_note_text() -> None:
    document = PublicRegistryProjection().document(_registry_bytes())
    text = json.dumps(document, ensure_ascii=False)
    for note in (SENSOR_NOTE, *PLACEMENT_NOTES):
        assert note not in text
    properties = document["features"][0]["properties"]
    assert properties["notes"] is None
    assert [p["note"] for p in properties["placements"]] == [None, None]
    assert list(properties) == [
        "id", "portal_name", "label", "municipality", "track", "variety", "status",
        "placements", "notes",
    ]  # fmt: skip


def test_projection_ignores_the_allowed_area() -> None:
    """The registry was validated with the configured area already (e.g. area check off)."""
    outside = _sensor().model_dump(mode="json")
    for placement in outside["placements"]:
        placement["lat"] = 10.0
    feature = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [16.6, 10.0]},
               "properties": outside}  # fmt: skip
    content = json.dumps({"type": "FeatureCollection", "features": [feature]}).encode("utf-8")
    document = PublicRegistryProjection().document(content)
    assert document["features"][0]["geometry"]["coordinates"] == [16.6, 10.0]


def test_invalid_registry_is_an_error() -> None:
    with pytest.raises(RegistryFormatError, match="registry file of the site build"):
        PublicRegistryProjection().document(b'{"type": "FeatureCollection"}')


def test_writer_writes_canonical_public_registry() -> None:
    with_registry = replace(snapshot(None, None), registry=_registry_bytes())
    (file,) = PublicRegistryWriter().files(with_registry)
    assert file.path == "sensors.geojson"
    text = file.content.decode("utf-8")
    assert text.startswith('{\n  "type": "FeatureCollection",\n')
    assert not [note for note in (SENSOR_NOTE, *PLACEMENT_NOTES) if note in text]
    expected = GeoJsonRegistryStore().dumps(
        SensorRegistry([PublicRegistryProjection.sensor(_sensor())])
    )
    assert text == expected


def test_writer_applies_the_redactor() -> None:
    with_registry = replace(snapshot(None, None), registry=_registry_bytes())
    redactor = SecretRedactor.of({"SIVIN_USER": "Ryzlink"})
    (file,) = PublicRegistryWriter(redactor=redactor).files(with_registry)
    assert "Ryzlink" not in file.content.decode("utf-8")
