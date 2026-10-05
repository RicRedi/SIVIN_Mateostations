"""Daylight-saving fall-back of 2026-10-25 in a SYNTHETIC portal CSV (``dst/``)."""

from __future__ import annotations

import pandas as pd

from sivin.core.flags import QcFlag
from sivin.core.timeutil import ConversionResult, LocalTimeConverter
from sivin.ingest.parsers.columns import ParserSettings
from sivin.ingest.parsers.portal import PortalCsvParser
from sivin.ingest.parsers.tabular import TabularExportReader
from sivin.ingest.validation import Severity

from ..conftest import EXPORTS, PORTAL_CSV_NAME

DST_FILE = EXPORTS / "dst" / "MeteoData_8615620 77678271 (VUT)_20261025_120000.csv"

# The file holds 12 samples taken every 1825 s from 2026-10-24 22:00:13 UTC; the local wall
# clock repeats 02:00-03:00 (03:00 CEST -> 02:00 CET at 01:00 UTC).
EXPECTED_UTC = [
    pd.Timestamp("2026-10-24 22:00:13", tz="UTC") + k * pd.Timedelta(seconds=1825)
    for k in range(12)
]
AMBIGUOUS_ROWS = [4, 5, 6, 7]  # local 02:01:53, 02:32:18 (CEST), 02:02:43, 02:33:08 (CET)


class StrictOrderConverter(LocalTimeConverter):
    """Simulates the announced contract: a ValueError when the local times do not increase."""

    def to_utc(self, local_naive: pd.Series) -> ConversionResult:
        present = local_naive.dropna()
        if not present.is_monotonic_increasing or present.duplicated().any():
            raise ValueError("local timestamps are not increasing")
        return super().to_utc(local_naive)


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


def test_converter_refusing_the_order_drops_daylight_saving_rows() -> None:
    settings = ParserSettings()
    reader = TabularExportReader(settings, StrictOrderConverter(settings.source_timezone))
    result = PortalCsvParser(settings, reader=reader).parse(DST_FILE)
    assert result.is_accepted
    frame = result.series[0].frame
    kept = [EXPECTED_UTC[k] for k in range(12) if k not in AMBIGUOUS_ROWS]
    assert frame["timestamp_utc"].tolist() == kept
    (issue,) = result.report.issues
    assert "4 unresolved row(s) dropped" in issue.message


def test_converter_refusing_unsorted_rows_still_sorts_them() -> None:
    settings = ParserSettings()
    reader = TabularExportReader(settings, StrictOrderConverter(settings.source_timezone))
    path = EXPORTS / "broken" / "unsorted_rows" / PORTAL_CSV_NAME
    result = PortalCsvParser(settings, reader=reader).parse(path)
    assert result.is_accepted
    assert len(result.series[0]) == 48
    assert result.report.rules() == {"monotonic-order"}
