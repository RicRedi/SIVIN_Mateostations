"""Writers of the per-sensor files: ``series/<id>/raw/<YYYY-MM>.json``, ``series/<id>/daily.json``
and ``events/<id>.json`` (MIGRATION_PLAN §2.6, §2.8).

Each writer is one class behind :class:`SensorFileWriter`; a new per-sensor file kind is a new
writer handed to the builder, never a branch in it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Final

import pandas as pd

from sivin.core.schema import Column
from sivin.redaction import SecretRedactor
from sivin.site.columns import (
    SHARE_DECIMALS,
    VALUE_DECIMALS,
    iso_dates,
    rounded,
    unix_seconds,
    utc_month_keys,
)
from sivin.site.events import SiteEventMapping
from sivin.site.files import SiteFile, encode_json
from sivin.site.model import SensorData

RAW_OPTIONAL_COLUMNS: Final = (Column.PRECIP, Column.BATTERY)
"""Optional raw columns (WP-1.9); written only for a month with at least one value."""

DAILY_VALUE_COLUMNS: Final = ("temp_min", "temp_mean", "temp_max", "rh_min", "rh_mean", "rh_max")
"""Temperature (°C) and humidity (%) columns of ``daily.json`` (§2.6)."""

DAILY_PRECIP_COLUMNS: Final = ("precip_sum_mm", "precip_n_samples")
"""Optional precipitation columns of ``daily.json``: the sum (mm) and how many interval values
it holds (count, shows partial days); written only when some day has precipitation."""

DAILY_BATTERY_COLUMN: Final = "battery_min_v"
"""Optional column of ``daily.json``: daily minimum battery voltage (V)."""


def raw_month_path(sensor_id: str, month: str) -> str:
    """Return ``series/<sensor_id>/raw/<YYYY-MM>.json``."""
    return f"series/{sensor_id}/raw/{month}.json"


def daily_path(sensor_id: str) -> str:
    """Return ``series/<sensor_id>/daily.json``."""
    return f"series/{sensor_id}/daily.json"


def events_path(sensor_id: str) -> str:
    """Return ``events/<sensor_id>.json``."""
    return f"events/{sensor_id}.json"


class SensorFileWriter(ABC):
    """Builds the files of one kind for one sensor.

    Parameters
    ----------
    redactor : SecretRedactor, optional
        Applied to every string written; nothing is redacted when omitted.
    """

    __slots__ = ("_redactor",)

    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        self._redactor = redactor

    @abstractmethod
    def files(self, data: SensorData) -> list[SiteFile]:
        """Return the files of this kind for one sensor.

        Parameters
        ----------
        data : SensorData
            QC result and daily aggregates of the sensor.

        Returns
        -------
        list of SiteFile
            The files (possibly none).
        """

    def _file(self, path: str, document: dict[str, Any]) -> SiteFile:
        return SiteFile(path, encode_json(document, self._redactor))


class RawMonthsWriter(SensorFileWriter):
    """One file per UTC calendar month with samples: columnar ``t``, values and ``qc``.

    Every sample of the QC'd series is written, flagged ones included (the web hides them by
    their ``qc``); values set aside by QC are ``null``.
    """

    __slots__ = ()

    def files(self, data: SensorData) -> list[SiteFile]:
        """Return ``series/<id>/raw/<YYYY-MM>.json`` for every month with samples.

        Parameters
        ----------
        data : SensorData
            The sensor's data.

        Returns
        -------
        list of SiteFile
            In increasing month order.
        """
        frame = data.result.series.frame
        if frame.empty:
            return []
        keys = utc_month_keys(frame[Column.TIMESTAMP])
        return [
            self._file(raw_month_path(str(data.sensor_id), str(month)), self._document(data, rows))
            for month, rows in frame.groupby(keys, sort=True)
        ]

    @staticmethod
    def _document(data: SensorData, rows: pd.DataFrame) -> dict[str, Any]:
        document: dict[str, Any] = {
            "sensor_id": str(data.sensor_id),
            "t": unix_seconds(rows[Column.TIMESTAMP]),
            "temp_c": rounded(rows[Column.TEMP], VALUE_DECIMALS),
            "rh_pct": rounded(rows[Column.RH], VALUE_DECIMALS),
        }
        for column in RAW_OPTIONAL_COLUMNS:
            if rows[column].notna().any():
                document[str(column)] = rounded(rows[column], VALUE_DECIMALS)
        document["qc"] = [int(flags) for flags in rows[Column.QC]]
        return document


class DailyWriter(SensorFileWriter):
    """``series/<id>/daily.json``: one row per local day of the display time zone."""

    __slots__ = ()

    def files(self, data: SensorData) -> list[SiteFile]:
        """Return the daily file (none for a sensor without samples).

        Parameters
        ----------
        data : SensorData
            The sensor's data.

        Returns
        -------
        list of SiteFile
            ``[daily.json]`` or ``[]``.
        """
        daily = data.daily
        if len(daily) == 0:
            return []
        frame = daily.frame
        document: dict[str, Any] = {
            "sensor_id": str(data.sensor_id),
            "date": iso_dates(daily.dates),
        }
        for column in DAILY_VALUE_COLUMNS:
            document[column] = rounded(frame[column], VALUE_DECIMALS)
        document["coverage"] = rounded(frame["coverage"], SHARE_DECIMALS)
        if frame["precip_sum_mm"].notna().any():
            document["precip_sum_mm"] = rounded(frame["precip_sum_mm"], VALUE_DECIMALS)
            document["precip_n_samples"] = [int(n) for n in frame["precip_n_samples"]]
        if frame[DAILY_BATTERY_COLUMN].notna().any():
            document[DAILY_BATTERY_COLUMN] = rounded(frame[DAILY_BATTERY_COLUMN], VALUE_DECIMALS)
        return [self._file(daily_path(str(data.sensor_id)), document)]


class SiteEventsWriter(SensorFileWriter):
    """``events/<id>.json``: the published QC events (:class:`SiteEventMapping`).

    Parameters
    ----------
    mapping : SiteEventMapping
        Selects and converts the events.
    redactor : SecretRedactor, optional
        Applied to every string written.
    """

    __slots__ = ("_mapping",)

    def __init__(self, mapping: SiteEventMapping, redactor: SecretRedactor | None = None) -> None:
        super().__init__(redactor)
        self._mapping = mapping

    def files(self, data: SensorData) -> list[SiteFile]:
        """Return the events file (written even when it lists no event).

        Parameters
        ----------
        data : SensorData
            The sensor's data.

        Returns
        -------
        list of SiteFile
            ``[events/<id>.json]``.
        """
        document = {
            "sensor_id": str(data.sensor_id),
            "events": self._mapping.entries(data.result.events),
        }
        return [self._file(events_path(str(data.sensor_id)), document)]


def default_sensor_writers(
    mapping: SiteEventMapping, redactor: SecretRedactor | None = None
) -> tuple[SensorFileWriter, ...]:
    """Return the per-sensor writers of the contract: raw months, daily, events.

    Parameters
    ----------
    mapping : SiteEventMapping
        The published event kinds.
    redactor : SecretRedactor, optional
        Applied to every string written.

    Returns
    -------
    tuple of SensorFileWriter
        The writers, in this order.
    """
    return (RawMonthsWriter(redactor), DailyWriter(redactor), SiteEventsWriter(mapping, redactor))
