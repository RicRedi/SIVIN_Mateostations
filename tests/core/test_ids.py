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
        "MeteoData_8615620 77678271 (VUT)_20260301_223857 (1).xlsx",
        "MeteoData_8615620 77678271  (VUT)_20260301_223857 (12).csv",
        r"C:\Users\someone\Downloads\MeteoData_8615620 77678271 (VUT)_20260301_223857.csv",
    ],
)
def test_parse_accepts_every_known_spelling(text: str) -> None:
    assert SensorId.parse(text) == SensorId("77678271")


@pytest.mark.parametrize(
    "text",
    [
        "MeteoData_8615620_77799986_VUT_20260301_223842.csv",
        "MeteoData_8615620_77799986_VUT_20260301_223842.xlsx",
        "MeteoData_8615620_77799986_20260301_223842.csv",
        "MeteoData_8615620_77799986_VUT.csv",
        "MeteoData_8615620_77799986.xlsx",
        "MeteoData_77799986_VUT_20260301_223842.csv",
        "MeteoData_8615620_77799986_VUT_20260301_223842 (1).csv",
        "/home/user/data/MeteoData_8615620_77799986_VUT_20260301_223842.csv",
        r"C:\Users\someone\Downloads\MeteoData_8615620_77799986_VUT_20260301_223842.csv",
        "  MeteoData_8615620_77799986_VUT_20260301_223842.csv  ",
    ],
)
def test_parse_accepts_file_names_with_underscores(text: str) -> None:
    # Spelling of the first real export (owner question Q8).
    assert SensorId.parse(text) == SensorId("77799986")


@pytest.mark.parametrize(
    "text",
    [
        # The export time must never be read as a serial.
        "MeteoData_8615620_20260301_223842.csv",
        "MeteoData_20260301_223842.csv",
        "MeteoData_77799986_20260301.csv",
        # The device number is shorter than a serial; two 8-digit runs are ambiguous.
        "MeteoData_12345678_77799986_VUT.csv",
        # A label starts with a letter.
        "MeteoData_8615620_77799986_1VUT.csv",
        # Underscores without the export prefix are not a known spelling.
        "8615620_77799986",
        "77799986_VUT",
        "MeteoData_8615620_77799986_VUT_20260301.csv",
    ],
)
def test_parse_rejects_ambiguous_underscore_names(text: str) -> None:
    with pytest.raises(ValueError, match="Cannot recognise"):
        SensorId.parse(text)


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
        ("\u0667\u0667\u0666\u0667\u0668\u0662\u0667\u0661", "Cannot recognise"),
        ("\u0668\u0662\u0667\u0661", "Cannot recognise"),
        ("MeteoData_8615620 77678271 (VUT)_20260301_223857 (x).csv", "Cannot recognise"),
    ],
)
def test_parse_rejects_unknown_spellings(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SensorId.parse(text)


@pytest.mark.parametrize(
    "serial",
    [
        "8271",
        "7767827a",
        " 77678271",
        "776782710",
        "\u0667\u0667\u0666\u0667\u0668\u0662\u0667\u0661",
    ],
)
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
