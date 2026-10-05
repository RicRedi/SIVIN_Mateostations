"""Generate the SYNTHETIC export fixtures of WP-1.2 (deterministic, seeded).

Run from the project root::

    .venv/bin/python tests/fixtures/exports/make_fixtures.py

Every value written here is synthetic: a smooth diurnal curve plus seeded noise. Nothing is a
measurement of a real sensor; the serial numbers only give the files realistic names. The file
layouts are reconstructed from the legacy scripts and are NOT verified on a real export (owner
question Q1). See README.md in this directory for the list of files.
"""

from __future__ import annotations

import csv
import io
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import openpyxl

logger = logging.getLogger(__name__)

SEED: Final = 20261005
"""Seed of the noise; changing it changes every fixture."""

INTERVAL: Final = timedelta(seconds=1825)
"""Sampling interval of the synthetic series (the nominal interval of the real sensors)."""

PRAGUE: Final = ZoneInfo("Europe/Prague")

PORTAL_CSV_NAME: Final = "MeteoData_8615620 77678271 (VUT)_20260301_223857.csv"
PORTAL_XLSX_NAME: Final = "MeteoData_8615620 77678271.xlsx"
PORTAL_XLSX_TEXT_NAME: Final = "MeteoData_8615620 77680921  (VUT)_20260105_173301.xlsx"
DST_CSV_NAME: Final = "MeteoData_8615620 77678271 (VUT)_20261025_120000.csv"
LEGACY_NAME: Final = "data.xlsx"

TITLE: Final = "Meteo Data"
HEADER: Final = ("Datum a čas", "Teplota (°C)", "Vlhkost (%)")
LEGACY_HEADER: Final = ("Datum a čas", "Teplota", "Vlhkost")
FIXED_TIME: Final = datetime(2026, 10, 5, 12, 0, 0)
"""Workbook creation time written into the document properties (keeps them stable)."""


@dataclass(frozen=True)
class Samples:
    """A synthetic series: naive local wall-clock times, temperature (°C), humidity (%)."""

    local: tuple[datetime, ...]
    temp_c: tuple[float, ...]
    rh_pct: tuple[float, ...]


def synthetic_samples(start_utc: datetime, n_samples: int, rng: np.random.Generator) -> Samples:
    """Build ``n_samples`` synthetic samples every 1825 s from ``start_utc``.

    Temperature follows a 24 h sine (mean 6 °C, amplitude 5 °C) plus N(0, 0.3) noise; humidity
    is its mirror image (mean 80 %, amplitude 12 %) plus N(0, 1.5) noise, clipped to 30-99 %.
    Both are rounded to one decimal. Local times are Europe/Prague wall-clock times.
    """
    instants = [start_utc + k * INTERVAL for k in range(n_samples)]
    phase = np.array([(t.hour * 3600 + t.minute * 60 + t.second) / 86400 for t in instants])
    wave = np.sin(2 * np.pi * (phase - 0.375))
    temp_c = np.round(6.0 + 5.0 * wave + rng.normal(0.0, 0.3, n_samples), 1)
    rh_pct = np.round(np.clip(80.0 - 12.0 * wave + rng.normal(0.0, 1.5, n_samples), 30, 99), 1)
    local = tuple(t.astimezone(PRAGUE).replace(tzinfo=None) for t in instants)
    return Samples(local, tuple(temp_c.tolist()), tuple(rh_pct.tolist()))


def comma(value: float) -> str:
    """Format a number with a decimal comma, as the Czech exports do."""
    return f"{value:.1f}".replace(".", ",")


def iso(stamp: datetime) -> str:
    """Format a local time as in the legacy CSV (``%Y-%m-%d %H:%M:%S``)."""
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def day_first(stamp: datetime) -> str:
    """Format a local time day first without leading zeros (``5.1.2026 17:33:01``)."""
    return f"{stamp.day}.{stamp.month}.{stamp.year} {stamp:%H:%M:%S}"


def month_first_text(stamp: datetime) -> str:
    """Format a local time month first (``3/1/2026 00:00:07`` for 1 March), US style."""
    return f"{stamp.month}/{stamp.day}/{stamp.year} {stamp:%H:%M:%S}"


def csv_rows(samples: Samples) -> list[list[str]]:
    """Data rows of a portal CSV."""
    return [
        [iso(t), comma(temp), comma(rh)]
        for t, temp, rh in zip(samples.local, samples.temp_c, samples.rh_pct, strict=True)
    ]


def portal_csv_text(rows: Sequence[Sequence[str]], header: Sequence[str] = HEADER) -> str:
    """A portal CSV: title line ``Meteo Data;``, header line, data lines, ``;``-separated."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([TITLE, ""])
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def write_workbook(path: Path, sheets: Sequence[tuple[str, Sequence[Sequence[object]]]]) -> None:
    """Write a workbook with one worksheet per ``(name, rows)``."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets:
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(list(row))
    workbook.properties.created = FIXED_TIME
    workbook.properties.modified = FIXED_TIME
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def portal_csv_fixtures(root: Path, rng: np.random.Generator) -> None:
    """The valid portal CSV and its broken variants (all with the same file name)."""
    samples = synthetic_samples(datetime(2026, 2, 28, 23, 0, 7, tzinfo=UTC), 48, rng)
    rows = csv_rows(samples)
    write_text(root / "valid" / PORTAL_CSV_NAME, portal_csv_text(rows))

    broken = root / "broken"
    (broken / "empty").mkdir(parents=True, exist_ok=True)
    (broken / "empty" / PORTAL_CSV_NAME).write_bytes(b"")
    write_text(broken / "header_only" / PORTAL_CSV_NAME, portal_csv_text([]))
    write_text(
        broken / "missing_humidity" / PORTAL_CSV_NAME,
        portal_csv_text([row[:2] for row in rows], HEADER[:2]),
    )
    fraction = [
        [t, temp, f"{float(rh.replace(',', '.')) / 100:.3f}".replace(".", ",")]
        for t, temp, rh in rows
    ]
    write_text(broken / "rh_fraction" / PORTAL_CSV_NAME, portal_csv_text(fraction))
    garbage = [[t, "n/a" if k % 3 == 0 else temp, rh] for k, (t, temp, rh) in enumerate(rows)]
    write_text(broken / "garbage_numbers" / PORTAL_CSV_NAME, portal_csv_text(garbage))
    bad_times = [[f"{t}?" if k % 4 == 0 else t, temp, rh] for k, (t, temp, rh) in enumerate(rows)]
    write_text(broken / "garbage_timestamps" / PORTAL_CSV_NAME, portal_csv_text(bad_times))
    duplicated = [
        *rows[:10],
        rows[9],
        rows[9],
        *rows[10:20],
        [rows[19][0], "9,9", rows[19][2]],
        *rows[20:],
    ]
    write_text(broken / "duplicated_rows" / PORTAL_CSV_NAME, portal_csv_text(duplicated))
    unsorted = [*rows[:5], rows[6], rows[5], *rows[7:30], rows[31], rows[30], *rows[32:]]
    write_text(broken / "unsorted_rows" / PORTAL_CSV_NAME, portal_csv_text(unsorted))
    write_text(broken / "unknown_name" / "export.csv", portal_csv_text(rows))
    text = portal_csv_text(rows)
    write_text(broken / "truncated_csv" / PORTAL_CSV_NAME, text[: text.rindex(";")])
    fahrenheit = ("Datum a čas", "Teplota (°F)", "Vlhkost (%)")
    write_text(broken / "fahrenheit_header" / PORTAL_CSV_NAME, portal_csv_text(rows, fahrenheit))
    kelvin = [[t, comma(float(temp.replace(",", ".")) + 273.15), rh] for t, temp, rh in rows]
    write_text(broken / "kelvin_values" / PORTAL_CSV_NAME, portal_csv_text(kelvin, LEGACY_HEADER))
    every_third = [datetime(2026, 3, 1, 0, 0, 7) + 3 * k * INTERVAL for k in range(len(rows))]
    month_first = [
        [month_first_text(t), temp, rh] for t, (_, temp, rh) in zip(every_third, rows, strict=True)
    ]
    write_text(broken / "month_first" / PORTAL_CSV_NAME, portal_csv_text(month_first))


def portal_xlsx_fixtures(root: Path, rng: np.random.Generator) -> None:
    """Valid portal workbooks (datetime cells; day-first text newest first) and a truncated one."""
    samples = synthetic_samples(datetime(2026, 1, 5, 9, 0, 3, tzinfo=UTC), 48, rng)
    rows: list[Sequence[object]] = [(TITLE,), HEADER]
    rows += list(zip(samples.local, samples.temp_c, samples.rh_pct, strict=True))
    valid = root / "valid" / PORTAL_XLSX_NAME
    write_workbook(valid, [("Meteo Data", rows)])

    text_samples = synthetic_samples(datetime(2026, 1, 5, 9, 57, 36, tzinfo=UTC), 14, rng)
    text_rows: list[Sequence[object]] = [(TITLE,), HEADER]
    text_rows += [
        (day_first(t), comma(temp), comma(rh))
        for t, temp, rh in zip(
            text_samples.local, text_samples.temp_c, text_samples.rh_pct, strict=True
        )
    ][::-1]
    write_workbook(root / "valid" / PORTAL_XLSX_TEXT_NAME, [("Meteo Data", text_rows)])

    data = valid.read_bytes()
    truncated = root / "broken" / "truncated_xlsx" / PORTAL_XLSX_NAME
    truncated.parent.mkdir(parents=True, exist_ok=True)
    truncated.write_bytes(data[: len(data) // 2])

    formulas: list[Sequence[object]] = [(TITLE,), HEADER]
    formulas += [
        (t, f"=0+{temp}", f"=0+{rh}")
        for t, temp, rh in zip(samples.local, samples.temp_c, samples.rh_pct, strict=True)
    ]
    write_workbook(
        root / "broken" / "formula_values" / PORTAL_XLSX_NAME, [("Meteo Data", formulas)]
    )


def legacy_fixture(root: Path, rng: np.random.Generator) -> None:
    """Legacy ``data.xlsx``: sheet ``8271`` with cell values, ``0921`` with Czech text."""
    first = synthetic_samples(datetime(2026, 1, 1, 0, 0, 11, tzinfo=UTC), 24, rng)
    second = synthetic_samples(datetime(2026, 1, 1, 0, 10, 42, tzinfo=UTC), 24, rng)
    sheet_8271: list[Sequence[object]] = [LEGACY_HEADER]
    sheet_8271 += list(zip(first.local, first.temp_c, first.rh_pct, strict=True))
    sheet_0921: list[Sequence[object]] = [LEGACY_HEADER]
    sheet_0921 += [
        (day_first(t), comma(temp), comma(rh))
        for t, temp, rh in zip(second.local, second.temp_c, second.rh_pct, strict=True)
    ]
    write_workbook(root / "legacy" / LEGACY_NAME, [("8271", sheet_8271), ("0921", sheet_0921)])


def dst_fixture(root: Path, rng: np.random.Generator) -> None:
    """Portal CSV spanning the fall-back of 2026-10-25 (03:00 CEST -> 02:00 CET)."""
    samples = synthetic_samples(datetime(2026, 10, 24, 22, 0, 13, tzinfo=UTC), 12, rng)
    write_text(root / "dst" / DST_CSV_NAME, portal_csv_text(csv_rows(samples)))


GENERATORS: Final[tuple[Callable[[Path, np.random.Generator], None], ...]] = (
    portal_csv_fixtures,
    portal_xlsx_fixtures,
    legacy_fixture,
    dst_fixture,
)


def generate(root: Path) -> None:
    """Write every fixture below ``root`` (one shared, seeded random generator)."""
    rng = np.random.default_rng(SEED)
    for generator in GENERATORS:
        generator(root, rng)
    logger.info("Synthetic export fixtures written to %s.", root)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generate(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
