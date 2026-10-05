"""Daylight-saving fall-back of 2026-10-25 in a SYNTHETIC portal CSV (``dst/``)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sivin.core.flags import QcFlag
from sivin.ingest.parsers.portal import PortalCsvParser
from sivin.ingest.validation import Severity

from ..conftest import EXPORTS

DST_FILE = EXPORTS / "dst" / "MeteoData_8615620 77678271 (VUT)_20261025_120000.csv"

# The file holds 12 samples taken every 1825 s from 2026-10-24 22:00:13 UTC; the local wall
# clock repeats 02:00-03:00 (03:00 CEST -> 02:00 CET at 01:00 UTC).
EXPECTED_UTC = [
    pd.Timestamp("2026-10-24 22:00:13", tz="UTC") + k * pd.Timedelta(seconds=1825)
    for k in range(12)
]
AMBIGUOUS_ROWS = [4, 5, 6, 7]  # local 02:01:53, 02:32:18 (CEST), 02:02:43, 02:33:08 (CET)


def test_fall_back_gives_strictly_increasing_utc_with_flags() -> None:
    result = PortalCsvParser().parse(DST_FILE)
    assert result.is_accepted
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == EXPECTED_UTC
    assert frame["timestamp_utc"].is_monotonic_increasing
    suspect = [k for k, qc in enumerate(frame["qc"]) if qc & QcFlag.TIMESTAMP_SUSPECT]
    assert suspect == AMBIGUOUS_ROWS
    (issue,) = result.report.issues
    assert (issue.rule, issue.severity, issue.row) == ("daylight-saving", Severity.WARNING, 7)
    assert issue.message.startswith("4 local time(s)")
    assert "0 unresolved row(s) dropped" in issue.message


def test_newest_first_file_across_fall_back(tmp_path: Path) -> None:
    lines = DST_FILE.read_text(encoding="utf-8").splitlines()
    reversed_file = tmp_path / DST_FILE.name
    reversed_file.write_text("\n".join([*lines[:2], *lines[:1:-1]]), encoding="utf-8")
    result = PortalCsvParser().parse(reversed_file)
    frame = result.series[0].frame
    assert frame["timestamp_utc"].tolist() == EXPECTED_UTC
    suspect = [k for k, qc in enumerate(frame["qc"]) if qc & QcFlag.TIMESTAMP_SUSPECT]
    assert suspect == AMBIGUOUS_ROWS
    assert result.report.rules() == {"daylight-saving"}
