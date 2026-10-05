"""Randomised robustness test (fixed seed): no file content may crash a parser.

The inputs are SYNTHETIC: the committed fixtures with random byte damage, and random grids of
cells of every type a CSV or workbook reader can return.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl
import pytest

from sivin.ingest.parsers.base import ParsedExport, parser_registry
from sivin.ingest.parsers.columns import ParserSettings

from .conftest import EXPORTS, LEGACY_SHEETS, PORTAL_CSV_NAME

SEED = 1825
N_BYTE_MUTATIONS = 60
N_RANDOM_GRIDS = 40

SOURCES = (
    f"valid/{PORTAL_CSV_NAME}",
    "valid/MeteoData_8615620 77678271.xlsx",
    "legacy/data.xlsx",
    "dst/MeteoData_8615620 77678271 (VUT)_20261025_120000.csv",
)

TOKENS: tuple[object, ...] = (
    "Datum a čas",
    "Teplota (°C)",
    "Vlhkost (%)",
    "Teplota",
    "Vlhkost",
    "Meteo Data",
    "2026-10-25 02:30:00",
    "25.10.2026 02:30",
    "1.1.1600 00:00",
    "12,5",
    "-1e308",
    "1e400",
    "nan",
    "",
    " ",
    None,
    0,
    -40.5,
    1e300,
    True,
    datetime(2026, 3, 29, 2, 30),
    datetime(1900, 1, 1),
    timedelta(hours=1),
)


def check(result: ParsedExport) -> None:
    assert isinstance(result, ParsedExport)
    if result.is_accepted:
        for series in result.series:
            assert series.timestamps.is_monotonic_increasing
    else:
        assert result.series == ()


def mutate(data: bytes, rng: random.Random) -> bytes:
    damaged = bytearray(data)
    for _ in range(rng.randint(1, 20)):
        operation = rng.choice(("flip", "cut", "insert", "delete"))
        position = rng.randrange(max(len(damaged), 1))
        if operation == "flip" and damaged:
            damaged[position] = rng.randrange(256)
        elif operation == "cut":
            del damaged[position:]
        elif operation == "insert":
            damaged[position:position] = rng.choice((b";", b"\r\n", b",", b'"', b"\x00", b"\xff"))
        elif damaged:
            del damaged[position]
    return bytes(damaged)


@pytest.mark.parametrize("relative", SOURCES)
def test_damaged_files_never_crash(relative: str, tmp_path: Path) -> None:
    rng = random.Random(f"{SEED}-{relative}")
    source = EXPORTS / relative
    settings = ParserSettings(legacy_sheet_sensors=LEGACY_SHEETS)
    parser = parser_registry.for_file(source, settings)
    original = source.read_bytes()
    for index in range(N_BYTE_MUTATIONS):
        target = tmp_path / str(index) / source.name
        target.parent.mkdir()
        target.write_bytes(mutate(original, rng))
        check(parser.parse(target))


def random_rows(rng: random.Random) -> list[list[object]]:
    n_columns = rng.randint(0, 5)
    return [
        [rng.choice(TOKENS) for _ in range(rng.randint(0, n_columns))]
        for _ in range(rng.randint(0, 12))
    ]


def test_random_grids_never_crash(tmp_path: Path) -> None:
    rng = random.Random(SEED)
    settings = ParserSettings(legacy_sheet_sensors=LEGACY_SHEETS, header_search_rows=3)
    for index in range(N_RANDOM_GRIDS):
        folder = tmp_path / str(index)
        folder.mkdir()
        rows = random_rows(rng)
        csv_path = folder / PORTAL_CSV_NAME
        csv_path.write_text(
            "\r\n".join(";".join("" if c is None else str(c) for c in row) for row in rows),
            encoding="utf-8",
        )
        check(parser_registry.for_file(csv_path, settings).parse(csv_path))
        workbook = openpyxl.Workbook()
        workbook.active.title = rng.choice(("8271", "0921"))
        for row in rows:
            workbook.active.append([c if not isinstance(c, timedelta) else str(c) for c in row])
        for name in ("MeteoData_8615620 77678271.xlsx", "data.xlsx"):
            path = folder / name
            workbook.save(path)
            check(parser_registry.for_file(path, settings).parse(path))
