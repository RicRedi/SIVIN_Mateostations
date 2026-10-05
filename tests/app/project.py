"""A temporary SIVIN project for the application, CLI and end-to-end tests.

The sensor registry is a copy of the repository's ``sensors/sensors.geojson`` (sensor identity
and positions only). Measurements come from the trimmed **real** export of sensor 77799986
(public by owner decision 2026-10-05) or from :func:`write_synthetic_export`, which writes
**SYNTHETIC** exports in the portal's CSV layout.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
REGISTRY: Final = REPO_ROOT / "sensors" / "sensors.geojson"
OFFSITE_LOG: Final = REPO_ROOT / "sensors" / "offsite_log.yaml"
REAL_EXPORT: Final = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "exports"
    / "real"
    / "MeteoData_8615620_77799986_VUT_20260301_223842.csv"
)
"""Trimmed real export of sensor 77799986 (300 rows, 2025-07-30 .. 2026-03-01)."""

REAL_SENSOR: Final = "77799986"
OUTDOOR_SENSOR: Final = "77678271"

EMPTY_OFFSITE_LOG: Final = "entries: []\n"

TEST_CONFIG: Final = """\
ingest:
  parsers:
    latest_timestamp: "2030-01-01T00:00:00"
  portal:
    timeouts:
      element_wait_s: 0.2
      download_wait_s: 3.0
      poll_interval_s: 0.01
      device_settle_s: 0.0
      tab_settle_s: 0.0
      list_check_s: 0.05
"""
"""Fixes the parsers' 'future timestamp' limit so the tests do not depend on today's date, and
shortens the portal waits for the fake browser (no real sleeping)."""

HEADER: Final = (
    "Datum a čas;Teplota (°C);Vlhkost (%);Srážky (mm);Celkové srážky (mm);Nabití baterie (V)"
)
"""Column header of the real export (MIGRATION_PLAN §0.6.1)."""

STEP_S: Final = 1830
"""Sampling step of the synthetic exports in seconds (the measured median)."""


@dataclass(frozen=True)
class Project:
    """A temporary project directory.

    Attributes
    ----------
    root : pathlib.Path
        The project root (contains ``pyproject.toml``).
    """

    root: Path

    @property
    def downloads(self) -> Path:
        """The default download directory."""
        return self.root / "data" / "downloads"

    def write_config(self, text: str) -> Path:
        """Write ``config/sivin.yaml``."""
        path = self.root / "config" / "sivin.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_offsite_log(self, text: str) -> Path:
        """Write ``sensors/offsite_log.yaml``."""
        path = self.root / "sensors" / "offsite_log.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def real_export(self, directory: Path | None = None) -> Path:
        """Copy the real export into ``directory`` (the download directory by default)."""
        target_dir = directory if directory is not None else self.downloads
        target_dir.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy2(REAL_EXPORT, target_dir / REAL_EXPORT.name))


def make_project(root: Path, offsite_log: str | None = None, config: str = TEST_CONFIG) -> Project:
    """Create a project with the registry, an off-site log and a configuration.

    Parameters
    ----------
    root : pathlib.Path
        Empty directory.
    offsite_log : str, optional
        Text of the off-site log; a copy of the repository's log (with the real Q10 entry of
        sensor 77799986) when omitted.
    config : str, optional
        Text of ``config/sivin.yaml``.

    Returns
    -------
    Project
        The project.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'test-project'\n", encoding="utf-8")
    sensors = root / "sensors"
    sensors.mkdir()
    shutil.copy2(REGISTRY, sensors / REGISTRY.name)
    project = Project(root)
    if offsite_log is None:
        shutil.copy2(OFFSITE_LOG, sensors / OFFSITE_LOG.name)
    else:
        project.write_offsite_log(offsite_log)
    project.write_config(config)
    return project


def write_synthetic_export(
    directory: Path,
    serial: str = OUTDOOR_SENSOR,
    start_local: datetime = datetime(2026, 6, 1, 0, 0, 10),
    days: int = 3,
    stamp: str = "20260605_060000",
    precip_spike_at: int | None = None,
) -> Path:
    """Write a SYNTHETIC outdoor export in the portal's CSV layout (newest row first).

    Temperature follows a daily cycle of 15 ± 6 °C (minimum at 03:00), humidity 75 ∓ 15 %,
    precipitation 0.0 mm (or 80 mm at row ``precip_spike_at``, an implausible value), the
    counter adds the interval values to 100.0 mm, battery 3.6 V. Rows every 1830 s.

    Parameters
    ----------
    directory : pathlib.Path
        Target directory (created).
    serial : str, optional
        Sensor serial.
    start_local : datetime.datetime, optional
        First local wall-clock time (Europe/Prague).
    days : int, optional
        Length in days.
    stamp : str, optional
        Export time in the file name, ``YYYYMMDD_HHMMSS``.
    precip_spike_at : int, optional
        Index (oldest = 0) of a row with an implausible 80 mm interval value.

    Returns
    -------
    pathlib.Path
        ``MeteoData_8615620 <serial> (VUT)_<stamp>.csv``.
    """
    n_rows = days * 86_400 // STEP_S
    lines = []
    counter_mm = 100.0
    for index in range(n_rows):
        moment = start_local + timedelta(seconds=index * STEP_S)
        hours = moment.hour + moment.minute / 60
        phase = 2 * math.pi * (hours - 9.0) / 24
        temp_c = 15.0 + 6.0 * math.sin(phase)
        rh_pct = 75.0 - 15.0 * math.sin(phase)
        precip_mm = 80.0 if index == precip_spike_at else 0.0
        counter_mm += precip_mm
        values = (_decimal(temp_c, 2), _decimal(rh_pct, 1), _decimal(precip_mm, 1))
        lines.append(
            f"{moment:%Y-%m-%d %H:%M:%S};{';'.join(values)};{_decimal(counter_mm, 1)};3,60"
        )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"MeteoData_8615620 {serial} (VUT)_{stamp}.csv"
    text = "\r\n".join(["Meteo Data;", HEADER, *reversed(lines), ";"]) + "\r\n"
    path.write_text(text, encoding="utf-8")
    return path


def _decimal(value: float, digits: int) -> str:
    """Format a number with a decimal comma, as the portal does."""
    return f"{value:.{digits}f}".replace(".", ",")
