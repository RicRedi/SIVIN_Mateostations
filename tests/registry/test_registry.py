"""Tests of SensorRegistry (synthetic sensors, plus the four real serials for name variants)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sivin.core.ids import SensorId
from sivin.registry.errors import AmbiguousSensorNameError, RegistryError, SensorLookupError
from sivin.registry.registry import SensorRegistry
from sivin.registry.settings import CZECH_REPUBLIC

from .conftest import T_2025_12_01, T_2026_03_01, PlacementFactory, SensorFactory


@pytest.fixture
def registry(make_sensor: SensorFactory) -> SensorRegistry:
    """Two real serials (identity only) and one synthetic inactive sensor."""
    return SensorRegistry(
        [
            make_sensor("77678271", portal_name="8615620 77678271"),
            make_sensor("77680921", portal_name="8615620 77680921"),
            make_sensor("11112222", status="inactive"),
        ]
    )


class TestConstruction:
    def test_rejects_duplicate_id(self, make_sensor: SensorFactory) -> None:
        with pytest.raises(RegistryError, match="Duplicate sensor id 11112222"):
            SensorRegistry([make_sensor("11112222"), make_sensor("11112222")])

    def test_rejects_duplicate_portal_name(self, make_sensor: SensorFactory) -> None:
        # A portal name contains the serial (checked by Sensor), so equal portal names mean
        # equal ids and the registry rejects them as duplicates.
        first = make_sensor("11112222", portal_name="8615620 11112222")
        second = make_sensor("11112222", portal_name="8615620 11112222", status="inactive")
        with pytest.raises(RegistryError, match="Duplicate sensor id 11112222"):
            SensorRegistry([first, second])

    def test_empty_registry(self) -> None:
        registry = SensorRegistry()
        assert len(registry) == 0
        assert list(registry) == []
        assert registry.area is None

    def test_area_check(self, make_sensor: SensorFactory, make_placement: PlacementFactory) -> None:
        inside = make_sensor()
        swapped = make_sensor(placements=(make_placement(lat_deg=16.60, lon_deg=48.80),))
        assert len(SensorRegistry([inside], area=CZECH_REPUBLIC)) == 1
        assert len(SensorRegistry([swapped])) == 1
        with pytest.raises(RegistryError, match="outside the allowed area"):
            SensorRegistry([swapped], area=CZECH_REPUBLIC)


class TestCollection:
    def test_iteration_keeps_order(self, registry: SensorRegistry) -> None:
        assert [str(s.id) for s in registry] == ["77678271", "77680921", "11112222"]
        assert registry.ids() == (SensorId("77678271"), SensorId("77680921"), SensorId("11112222"))
        assert len(registry) == 3

    def test_active(self, registry: SensorRegistry) -> None:
        assert [str(s.id) for s in registry.active()] == ["77678271", "77680921"]

    def test_contains(self, registry: SensorRegistry) -> None:
        assert "8615620 77678271" in registry
        assert SensorId("11112222") in registry
        assert "99998888" not in registry
        assert 77678271 not in registry

    def test_equality_and_repr(self, registry: SensorRegistry, make_sensor: SensorFactory) -> None:
        assert registry == SensorRegistry(list(registry))
        assert registry != SensorRegistry(list(registry), area=CZECH_REPUBLIC)
        assert registry != list(registry)
        assert repr(registry) == "SensorRegistry([77678271, 77680921, 11112222])"


class TestGet:
    @pytest.mark.parametrize(
        "name",
        [
            "77678271",
            SensorId("77678271"),
            "8615620 77678271",
            "77678271 (VUT)",
            "MeteoData_8615620 77678271  (VUT)_20260301_223857.csv",
            "/data/exports/MeteoData_8615620 77678271 (VUT)_20260301_223857 (1).xlsx",
            "8271",
            " 8271 ",
        ],
    )
    def test_resolves_every_variant(self, registry: SensorRegistry, name: SensorId | str) -> None:
        assert registry.get(name).id == SensorId("77678271")

    def test_unknown_serial(self, registry: SensorRegistry) -> None:
        with pytest.raises(SensorLookupError, match=r"99998888 .* not in the registry"):
            registry.get("99998888")
        with pytest.raises(SensorLookupError, match="not in the registry"):
            registry.get(SensorId("99998888"))

    def test_unknown_suffix(self, registry: SensorRegistry) -> None:
        with pytest.raises(SensorLookupError, match="ending in 9999"):
            registry.get("9999")

    def test_unrecognised_name(self, registry: SensorRegistry) -> None:
        with pytest.raises(SensorLookupError, match="Cannot recognise"):
            registry.get("VUT")

    def test_ambiguous_legacy_suffix(self, make_sensor: SensorFactory) -> None:
        registry = SensorRegistry([make_sensor("11118271"), make_sensor("22228271")])
        with pytest.raises(AmbiguousSensorNameError, match="11118271, 22228271"):
            registry.get("8271")
        assert registry.get("22228271").id == SensorId("22228271")


class TestChanges:
    def test_with_sensor_adds(self, registry: SensorRegistry, make_sensor: SensorFactory) -> None:
        bigger = registry.with_sensor(make_sensor("33334444"))
        assert [str(i) for i in bigger.ids()][-1] == "33334444"
        assert len(registry) == 3

    def test_with_sensor_replaces_in_place(
        self, registry: SensorRegistry, make_sensor: SensorFactory
    ) -> None:
        updated = registry.get("77680921").replaced(site="Synthetic site")
        changed = registry.with_sensor(updated)
        assert changed.ids() == registry.ids()
        assert changed.get("77680921").site == "Synthetic site"
        assert registry.get("77680921").site is None

    def test_without(self, registry: SensorRegistry) -> None:
        smaller = registry.without(SensorId("77680921"))
        assert [str(i) for i in smaller.ids()] == ["77678271", "11112222"]
        with pytest.raises(SensorLookupError):
            smaller.without(SensorId("77680921"))

    def test_changes_keep_area(self, make_sensor: SensorFactory) -> None:
        registry = SensorRegistry([make_sensor()], area=CZECH_REPUBLIC)
        assert registry.with_sensor(make_sensor("33334444")).area == CZECH_REPUBLIC
        assert registry.without(SensorId("11112222")).area == CZECH_REPUBLIC

    def test_with_moved_and_placement_at_across_the_move(
        self, registry: SensorRegistry, make_placement: PlacementFactory
    ) -> None:
        moved = registry.with_moved(
            SensorId("77678271"), make_placement(from_utc=T_2026_03_01, lat_deg=48.9)
        )
        sensor = moved.get("77678271")
        assert [p.to_utc for p in sensor.placements] == [T_2026_03_01, None]
        before = sensor.placement_at(datetime(2026, 2, 28, 23, 59, tzinfo=UTC))
        after = sensor.placement_at(T_2026_03_01)
        assert before is not None
        assert after is not None
        assert (before.lat_deg, after.lat_deg) == (48.80, 48.9)
        assert sensor.deployed_since == T_2025_12_01
        assert registry.get("77678271").current_placement is not None
        assert len(registry.get("77678271").placements) == 1

    def test_with_moved_outside_area(
        self, make_sensor: SensorFactory, make_placement: PlacementFactory
    ) -> None:
        registry = SensorRegistry([make_sensor()], area=CZECH_REPUBLIC)
        with pytest.raises(RegistryError, match="outside"):
            registry.with_moved(
                SensorId("11112222"), make_placement(from_utc=T_2026_03_01, lat_deg=52.0)
            )

    def test_with_moved_before_start(
        self, registry: SensorRegistry, make_placement: PlacementFactory
    ) -> None:
        with pytest.raises(ValidationError):
            registry.with_moved(SensorId("77678271"), make_placement(from_utc=T_2025_12_01))

    def test_with_moved_unknown(
        self, registry: SensorRegistry, make_placement: PlacementFactory
    ) -> None:
        with pytest.raises(SensorLookupError):
            registry.with_moved(SensorId("99998888"), make_placement())
