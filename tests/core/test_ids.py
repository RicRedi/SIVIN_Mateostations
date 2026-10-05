"""Tests of SensorId parsing (MIGRATION_PLAN §2.4)."""

from __future__ import annotations

import dataclasses

import pytest

from sivin.core.ids import SensorId


@pytest.mark.parametrize(
    "text",
    [
        "77678271",
        "  77678271  ",
        "8615620 77678271",
        "77678271 (VUT)",
        "MeteoData_8615620 77678271 (VUT)_20260301_223857.csv",
        "MeteoData_8615620 77678271  (VUT)_20260301_223857.csv",
        "MeteoData_8615620 77678271 (VUT)_20260301_223857.xlsx",
        "/home/user/data/MeteoData_8615620 77678271  (VUT)_20260301_223857.csv",
        r"C:\Users\someone\Downloads\MeteoData_8615620 77678271 (VUT)_20260301_223857.csv",
    ],
)
def test_parse_accepts_every_known_spelling(text: str) -> None:
    assert SensorId.parse(text) == SensorId("77678271")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("8271", "legacy 4-digit"),
        ("7767827", "Cannot recognise"),
        ("776782710", "Cannot recognise"),
        ("", "Cannot recognise"),
        ("VUT", "Cannot recognise"),
        ("data.xlsx", "Cannot recognise"),
        ("MeteoData_8615620 (VUT)_20260301_223857.csv", "Cannot recognise"),
    ],
)
def test_parse_rejects_unknown_spellings(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SensorId.parse(text)


@pytest.mark.parametrize("serial", ["8271", "7767827a", " 77678271", "776782710"])
def test_constructor_requires_exactly_eight_digits(serial: str) -> None:
    with pytest.raises(ValueError, match="exactly 8 digits"):
        SensorId(serial)


def test_constructor_rejects_non_string() -> None:
    with pytest.raises(ValueError, match="exactly 8 digits"):
        SensorId(77678271)  # type: ignore[arg-type]


def test_str_and_legacy_suffix() -> None:
    sensor = SensorId("77678271")
    assert str(sensor) == "77678271"
    assert sensor.legacy_suffix == "8271"


def test_value_semantics() -> None:
    first, second = SensorId("77680921"), SensorId("77678271")
    assert sorted([first, second]) == [second, first]
    assert {first, SensorId("77680921")} == {first}
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.serial = "77678271"  # type: ignore[misc]
