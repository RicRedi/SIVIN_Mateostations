"""Tests of header normalisation, column mapping and parser settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sivin.core.ids import SensorId
from sivin.ingest.parsers.columns import (
    CanonicalColumn,
    ColumnAliases,
    ColumnMapping,
    ParserSettings,
    normalize_label,
    normalize_unit,
)


def test_normalize_label() -> None:
    assert normalize_label("  Datum a  ČAS ") == "datum a cas"
    assert normalize_label("Relativní vlhkost") == "relativni vlhkost"
    assert normalize_unit("° C") == normalize_unit("℃") == "°c"


@pytest.mark.parametrize(
    ("header", "column", "accepted"),
    [
        ("Datum a čas", CanonicalColumn.TIMESTAMP, True),
        ("datum a cas", CanonicalColumn.TIMESTAMP, True),
        ("Teplota (°C)", CanonicalColumn.TEMP, True),
        ("TEPLOTA [℃]", CanonicalColumn.TEMP, True),
        ("Teplota (°F)", CanonicalColumn.TEMP, False),
        ("Vlhkost (%)", CanonicalColumn.RH, True),
        ("Luftfeuchtigkeit (%RH)", CanonicalColumn.RH, True),
        ("Relative humidity", CanonicalColumn.RH, True),
        ("Teplota rosného bodu (°C)", None, True),
        ("Poznámka", None, True),
        ("(°C)", None, True),
    ],
)
def test_classify(header: str, column: CanonicalColumn | None, accepted: bool) -> None:
    cell = ColumnMapping(ColumnAliases()).classify(header)
    assert (cell.column, cell.accepted) == (column, accepted)


def test_classify_non_strings() -> None:
    mapping = ColumnMapping(ColumnAliases())
    assert mapping.classify(None).column is None
    assert mapping.classify(12.5).text == "12.5"


def test_locate_header_skips_title_rows() -> None:
    rows = [("Meteo Data", None), (), ("Datum a čas", "Teplota (°C)", "x", "Vlhkost (%)")]
    match = ColumnMapping(ColumnAliases()).locate_header(rows, 10)
    assert match is not None
    assert match.row_index == 2
    assert dict(match.positions) == {
        CanonicalColumn.TIMESTAMP: 0,
        CanonicalColumn.TEMP: 1,
        CanonicalColumn.RH: 3,
    }
    assert match.is_complete
    assert ColumnMapping(ColumnAliases()).locate_header(rows, 2) is None


def test_custom_aliases() -> None:
    aliases = ColumnAliases(timestamp=("Zeit",), temp_c=("T",), rh_pct=("F",))
    match = ColumnMapping(aliases).locate_header([("zeit", "t", "f")], 1)
    assert match is not None
    assert match.is_complete


def test_parser_settings_defaults_and_validation() -> None:
    settings = ParserSettings()
    assert settings.source_timezone == "Europe/Prague"
    assert settings.legacy_sheet_ids == {}
    mapped = ParserSettings(legacy_sheet_sensors={"8271": "77678271"})
    assert mapped.legacy_sheet_ids == {"8271": SensorId("77678271")}
    with pytest.raises(ValidationError, match="unknown IANA"):
        ParserSettings(source_timezone="Europe/Brno")
    with pytest.raises(ValidationError, match="unknown text encoding"):
        ParserSettings(csv_encodings=("klingon",))
    with pytest.raises(ValidationError, match="8 digits"):
        ParserSettings(legacy_sheet_sensors={"8271": "8271"})
    with pytest.raises(ValidationError, match="one worksheet only"):
        ParserSettings(legacy_sheet_sensors={"a": "77678271", "b": "77678271"})
    with pytest.raises(ValidationError, match="Extra inputs"):
        ParserSettings(header_rows=3)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ParserSettings(header_search_rows=0)


def test_explicit_valid_settings() -> None:
    settings = ParserSettings(source_timezone="UTC", csv_encodings=("utf-8",))
    assert (settings.source_timezone, settings.csv_encodings) == ("UTC", ("utf-8",))
