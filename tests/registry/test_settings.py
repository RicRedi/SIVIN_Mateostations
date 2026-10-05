"""Tests of GeoBounds and RegistrySettings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sivin.registry.settings import CZECH_REPUBLIC, GeoBounds, RegistrySettings


def test_contains_includes_edges() -> None:
    box = GeoBounds(min_lat_deg=48.0, max_lat_deg=49.0, min_lon_deg=16.0, max_lon_deg=17.0)
    assert box.contains(48.0, 16.0)
    assert box.contains(49.0, 17.0)
    assert box.contains(48.5, 16.5)
    assert not box.contains(47.99, 16.5)
    assert not box.contains(48.5, 17.01)


def test_czech_republic_holds_the_vineyard_and_rejects_swapped_coordinates() -> None:
    assert CZECH_REPUBLIC.contains(48.880215, 16.673002)
    assert not CZECH_REPUBLIC.contains(16.673002, 48.880215)
    assert not CZECH_REPUBLIC.contains(48.2, 16.37)  # Vienna, synthetic check point


@pytest.mark.parametrize(
    "bounds",
    [
        {"min_lat_deg": 49.0, "max_lat_deg": 48.0, "min_lon_deg": 16.0, "max_lon_deg": 17.0},
        {"min_lat_deg": 48.0, "max_lat_deg": 49.0, "min_lon_deg": 17.0, "max_lon_deg": 17.0},
        {"min_lat_deg": 48.0, "max_lat_deg": 91.0, "min_lon_deg": 16.0, "max_lon_deg": 17.0},
    ],
)
def test_rejects_invalid_bounds(bounds: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        GeoBounds.model_validate(bounds)


def test_settings_default_and_forbid_extra() -> None:
    assert RegistrySettings().allowed_area == CZECH_REPUBLIC
    with pytest.raises(ValidationError, match="Extra inputs"):
        RegistrySettings.model_validate({"allowed_aera": None})
