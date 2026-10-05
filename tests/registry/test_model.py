"""Tests of Placement and Sensor (synthetic sensors only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.core.ids import SensorId
from sivin.registry.model import Placement, Sensor, format_utc

from .conftest import T_2025_12_01, T_2026_03_01, T_2026_06_01, PlacementFactory, SensorFactory

CET = timezone(timedelta(hours=1))


class TestPlacement:
    def test_converts_any_offset_to_utc(self, make_placement: PlacementFactory) -> None:
        placement = make_placement(from_utc=datetime(2026, 3, 1, 1, 30, tzinfo=CET))
        assert placement.from_utc == datetime(2026, 3, 1, 0, 30, tzinfo=UTC)
        assert placement.from_utc.tzinfo is UTC

    def test_rejects_naive_datetime(self, make_placement: PlacementFactory) -> None:
        with pytest.raises(ValidationError, match="timezone"):
            make_placement(from_utc=datetime(2026, 3, 1))

    @pytest.mark.parametrize("to_utc", [T_2025_12_01, T_2025_12_01 - timedelta(seconds=1)])
    def test_rejects_end_not_after_start(
        self, make_placement: PlacementFactory, to_utc: datetime
    ) -> None:
        with pytest.raises(ValidationError, match="must be before"):
            make_placement(to_utc=to_utc)

    @pytest.mark.parametrize(
        ("lat_deg", "lon_deg"),
        [(90.1, 16.0), (-90.1, 16.0), (48.0, 180.1), (48.0, -180.1), (float("nan"), 16.0)],
    )
    def test_rejects_coordinates_out_of_range(
        self, make_placement: PlacementFactory, lat_deg: float, lon_deg: float
    ) -> None:
        with pytest.raises(ValidationError):
            make_placement(lat_deg=lat_deg, lon_deg=lon_deg)

    def test_accepts_range_limits(self, make_placement: PlacementFactory) -> None:
        placement = make_placement(lat_deg=-90.0, lon_deg=180.0)
        assert (placement.lat_deg, placement.lon_deg) == (-90.0, 180.0)

    def test_rejects_unknown_key(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs"):
            Placement.model_validate(
                {"from": "2025-12-01T00:00:00Z", "lat": 48.8, "lon": 16.6, "x": 1}
            )

    def test_reads_file_keys(self) -> None:
        placement = Placement.model_validate(
            {
                "from": "2025-12-01T00:00:00Z",
                "to": "2026-03-01T00:00:00+01:00",
                "lat": 48.8,
                "lon": 16.6,
            }
        )
        assert placement.from_utc == T_2025_12_01
        assert placement.to_utc == datetime(2026, 2, 28, 23, tzinfo=UTC)
        assert placement.elevation_m is None

    def test_serialises_with_file_keys_and_z(self, make_placement: PlacementFactory) -> None:
        placement = make_placement(to_utc=T_2026_03_01, note="n")
        assert placement.model_dump(mode="json") == {
            "from": "2025-12-01T00:00:00Z",
            "to": "2026-03-01T00:00:00Z",
            "lon": 16.60,
            "lat": 48.80,
            "elevation_m": 200.0,
            "note": "n",
        }

    def test_contains_is_half_open(self, make_placement: PlacementFactory) -> None:
        placement = make_placement(to_utc=T_2026_03_01)
        assert placement.contains(T_2025_12_01)
        assert placement.contains(T_2026_03_01 - timedelta(microseconds=1))
        assert not placement.contains(T_2026_03_01)
        assert not placement.contains(T_2025_12_01 - timedelta(seconds=1))

    def test_closed_at(self, make_placement: PlacementFactory) -> None:
        closed = make_placement().closed_at(T_2026_03_01)
        assert closed.to_utc == T_2026_03_01
        assert not closed.is_open

    def test_is_frozen(self, make_placement: PlacementFactory) -> None:
        with pytest.raises(ValidationError, match="frozen"):
            make_placement().lat_deg = 0.0  # type: ignore[misc]


def test_format_utc_fractional_and_offset() -> None:
    assert (
        format_utc(datetime(2026, 1, 1, 1, 0, 0, 500, tzinfo=CET)) == "2026-01-01T00:00:00.000500Z"
    )


class TestSensor:
    def test_minimal_sensor(self, make_sensor: SensorFactory) -> None:
        sensor = make_sensor()
        assert sensor.id == SensorId("11112222")
        assert sensor.is_active
        assert sensor.deployed_since == T_2025_12_01
        assert sensor.current_placement is sensor.placements[0]
        assert sensor.last_placement is sensor.placements[0]

    def test_id_serialises_as_string(self, make_sensor: SensorFactory) -> None:
        assert make_sensor().model_dump(mode="json")["id"] == "11112222"
        assert make_sensor().model_dump()["id"] == "11112222"

    @pytest.mark.parametrize("bad_id", ["8615620 11112222", "1111222", 11112222])
    def test_id_must_be_canonical_string(self, make_sensor: SensorFactory, bad_id: object) -> None:
        with pytest.raises(ValidationError):
            make_sensor(bad_id)  # type: ignore[arg-type]

    def test_accepts_sensor_id_instance(self, make_placement: PlacementFactory) -> None:
        sensor = Sensor(
            id=SensorId("11112222"), label="x", status="active", placements=(make_placement(),)
        )
        assert sensor.id == SensorId("11112222")

    def test_requires_a_placement(self, make_sensor: SensorFactory) -> None:
        with pytest.raises(ValidationError, match="at least 1"):
            make_sensor(placements=())

    def test_rejects_unsorted_placements(
        self, make_sensor: SensorFactory, make_placement: PlacementFactory
    ) -> None:
        first = make_placement(from_utc=T_2026_03_01, to_utc=T_2026_06_01)
        second = make_placement(from_utc=T_2025_12_01, to_utc=T_2026_03_01)
        with pytest.raises(ValidationError, match="not sorted"):
            make_sensor(status="inactive", placements=(first, second))

    def test_rejects_overlapping_placements(
        self, make_sensor: SensorFactory, make_placement: PlacementFactory
    ) -> None:
        first = make_placement(to_utc=T_2026_03_01 + timedelta(hours=1))
        second = make_placement(from_utc=T_2026_03_01)
        with pytest.raises(ValidationError, match="overlap"):
            make_sensor(placements=(first, second))

    def test_rejects_open_placement_that_is_not_last(
        self, make_sensor: SensorFactory, make_placement: PlacementFactory
    ) -> None:
        first = make_placement()
        second = make_placement(from_utc=T_2026_03_01)
        with pytest.raises(ValidationError, match=r"open .* not the\s+last"):
            make_sensor(placements=(first, second))

    def test_accepts_gap_and_touching_placements(
        self, make_sensor: SensorFactory, make_placement: PlacementFactory
    ) -> None:
        sensor = make_sensor(
            placements=(
                make_placement(to_utc=T_2026_03_01),
                make_placement(from_utc=T_2026_03_01, to_utc=T_2026_06_01 - timedelta(days=10)),
                make_placement(from_utc=T_2026_06_01),
            )
        )
        assert len(sensor.placements) == 3

    def test_portal_name_must_name_the_same_serial(self, make_sensor: SensorFactory) -> None:
        assert make_sensor(portal_name="8615620 11112222").portal_name == "8615620 11112222"
        with pytest.raises(ValidationError, match="names sensor 33334444"):
            make_sensor(portal_name="8615620 33334444")
        with pytest.raises(ValidationError, match="Cannot recognise"):
            make_sensor(portal_name="station one")

    def test_active_needs_open_placement(
        self, make_sensor: SensorFactory, make_placement: PlacementFactory
    ) -> None:
        closed = (make_placement(to_utc=T_2026_03_01),)
        with pytest.raises(ValidationError, match="active but its last placement is closed"):
            make_sensor(placements=closed)
        assert make_sensor(status="inactive", placements=closed).current_placement is None
        assert make_sensor(status="retired", placements=closed).last_placement == closed[0]

    def test_retired_needs_closed_placement(self, make_sensor: SensorFactory) -> None:
        with pytest.raises(ValidationError, match="retired but its last placement is open"):
            make_sensor(status="retired")
        assert not make_sensor(status="inactive").is_active

    def test_rejects_unknown_status(self, make_sensor: SensorFactory) -> None:
        with pytest.raises(ValidationError):
            make_sensor(status="broken")


class TestPlacementHistory:
    """A synthetic sensor that moved on 2026-03-01 and was serviced 2026-05-01..06-01."""

    @pytest.fixture
    def moved(self, make_sensor: SensorFactory, make_placement: PlacementFactory) -> Sensor:
        return make_sensor(
            placements=(
                make_placement(to_utc=T_2026_03_01, lat_deg=48.80),
                make_placement(
                    from_utc=T_2026_03_01, to_utc=datetime(2026, 5, 1, tzinfo=UTC), lat_deg=48.81
                ),
                make_placement(from_utc=T_2026_06_01, lat_deg=48.82),
            )
        )

    @pytest.mark.parametrize(
        ("instant", "lat_deg"),
        [
            (T_2025_12_01, 48.80),
            (T_2026_03_01 - timedelta(seconds=1), 48.80),
            (T_2026_03_01, 48.81),
            (datetime(2026, 4, 30, 23, 59, tzinfo=UTC), 48.81),
            (T_2026_06_01, 48.82),
            (datetime(2030, 1, 1, tzinfo=UTC), 48.82),
        ],
    )
    def test_placement_at(self, moved: Sensor, instant: datetime, lat_deg: float) -> None:
        placement = moved.placement_at(instant)
        assert placement is not None
        assert placement.lat_deg == lat_deg

    @pytest.mark.parametrize(
        "instant",
        [
            T_2025_12_01 - timedelta(seconds=1),
            datetime(2026, 5, 1, tzinfo=UTC),
            datetime(2026, 5, 15, tzinfo=UTC),
        ],
    )
    def test_placement_at_outside_any_placement(self, moved: Sensor, instant: datetime) -> None:
        assert moved.placement_at(instant) is None

    def test_placement_at_other_zone_and_pandas(self, moved: Sensor) -> None:
        local = datetime(2026, 3, 1, 0, 30, tzinfo=CET)
        placement = moved.placement_at(local)
        assert placement is not None
        assert placement.lat_deg == 48.80
        stamp = pd.Timestamp("2026-03-01T00:00:00Z")
        stamped = moved.placement_at(stamp)
        assert stamped is not None
        assert stamped.lat_deg == 48.81

    def test_placement_at_rejects_naive(self, moved: Sensor) -> None:
        with pytest.raises(ValueError, match="time-zone aware"):
            moved.placement_at(datetime(2026, 3, 1))

    def test_deployed_since_is_first_from(self, moved: Sensor) -> None:
        assert moved.deployed_since == T_2025_12_01


class TestMovedTo:
    def test_closes_open_placement(
        self, make_sensor: SensorFactory, make_placement: PlacementFactory
    ) -> None:
        sensor = make_sensor()
        moved = sensor.moved_to(make_placement(from_utc=T_2026_03_01, lat_deg=48.9))
        assert [p.to_utc for p in moved.placements] == [T_2026_03_01, None]
        assert moved.current_placement is not None
        assert moved.current_placement.lat_deg == 48.9
        assert sensor.placements[0].is_open

    def test_appends_after_closed_history(
        self, make_sensor: SensorFactory, make_placement: PlacementFactory
    ) -> None:
        sensor = make_sensor(status="inactive", placements=(make_placement(to_utc=T_2026_03_01),))
        moved = sensor.moved_to(make_placement(from_utc=T_2026_06_01))
        assert len(moved.placements) == 2
        assert moved.status == "inactive"

    def test_rejects_move_before_current_start(
        self, make_sensor: SensorFactory, make_placement: PlacementFactory
    ) -> None:
        sensor = make_sensor(placements=(make_placement(from_utc=T_2026_03_01),))
        with pytest.raises(ValidationError, match="must be before"):
            sensor.moved_to(make_placement(from_utc=T_2025_12_01))

    def test_replaced_revalidates(self, make_sensor: SensorFactory) -> None:
        sensor = make_sensor()
        assert sensor.replaced(site="Synthetic site").site == "Synthetic site"
        with pytest.raises(ValidationError):
            sensor.replaced(status="retired")
