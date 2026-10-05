"""Encoding of a measurement series as a byte-stable CSV file (MIGRATION_PLAN §2.5).

The exact format is specified in ``docs/storage.md`` and implemented by :class:`CsvSeriesCodec`.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import IO, ClassVar, Final

import numpy as np
import pandas as pd

from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries, SchemaError
from sivin.storage.errors import StoreFormatError

logger = logging.getLogger(__name__)

STORED_COLUMNS: Final = (Column.TIMESTAMP, Column.TEMP, Column.RH, Column.SOURCE)
"""Columns of a stored file, in this order. ``qc`` is not stored (recomputed at build time)."""

FILE_ENCODING: Final = "utf-8"
"""Text encoding of stored files (no byte-order mark)."""

LINE_TERMINATOR: Final = "\n"
"""Line terminator of stored files (LF, also on Windows)."""

MIN_FRACTION_DIGITS: Final = 1
"""Minimum number of digits after the decimal point of a stored value.

Values are written in positional notation with the shortest digit string that reads back as the
same ``float64`` (so nothing is rounded away), but with at least one fractional digit, so a
whole number is written ``12.0`` and every value visibly is a decimal number.
"""

NANOSECONDS_PER_SECOND: Final = 1_000_000_000
"""Nanoseconds in one second (fractional seconds of a timestamp)."""

FRACTION_DIGITS_NS: Final = 9
"""Digits of a nanosecond fraction of a second."""

_TIMESTAMP_PATTERN: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z"
)
_VALUE_PATTERN: Final = re.compile(r"-?[0-9]+\.[0-9]+")


class SeriesCodec(ABC):
    """Extension point: conversion of a series to and from the bytes of one stored file."""

    file_suffix: ClassVar[str]
    """File-name suffix of the format, including the dot, e.g. ``".csv"``."""

    @abstractmethod
    def write(self, series: MeasurementSeries, stream: IO[bytes]) -> None:
        """Write ``series`` to a binary stream.

        Parameters
        ----------
        series : MeasurementSeries
            The rows to store; ``qc`` is not stored.
        stream : binary file object
            Destination, positioned at its start.
        """

    @abstractmethod
    def read(self, stream: IO[bytes], sensor_id: SensorId, origin: str) -> MeasurementSeries:
        """Read a series from a binary stream.

        Parameters
        ----------
        stream : binary file object
            Source, positioned at its start.
        sensor_id : SensorId
            The sensor the file belongs to.
        origin : str
            Name of the source (file path) used in error messages.

        Returns
        -------
        MeasurementSeries
            The stored rows with ``qc = 0``.

        Raises
        ------
        StoreFormatError
            If the content does not follow the format.
        """


class CsvSeriesCodec(SeriesCodec):
    """The CSV file format of the measurement store.

    One header line ``timestamp_utc,temp_c,rh_pct,source``, then one line per sample in
    strictly increasing time order; UTF-8 without BOM, LF line ends, ``,`` separator, RFC 4180
    quoting (only where needed, ``"`` doubled). Fields:

    * ``timestamp_utc``: ISO 8601 UTC with ``Z``, ``YYYY-MM-DDTHH:MM:SS``; a fraction of a second
      is appended only when non-zero, with trailing zeros removed (up to 9 digits).
    * ``temp_c`` (°C), ``rh_pct`` (%): ``.`` decimal point, positional notation, the shortest
      digits that read back as the same ``float64``, at least one fractional digit; an empty
      field means missing (``NaN``).
    * ``source``: name of the source file the row came from; empty when unknown.

    Encoding is a pure function of the data, so the same series always gives the same bytes,
    and ``read`` followed by ``write`` reproduces a file byte for byte.
    """

    file_suffix: ClassVar[str] = ".csv"

    def write(self, series: MeasurementSeries, stream: IO[bytes]) -> None:
        """Write ``series`` as CSV (see the class docstring for the format).

        Parameters
        ----------
        series : MeasurementSeries
            The rows to store; ``qc`` is dropped.
        stream : binary file object
            Destination.
        """
        text = io.TextIOWrapper(stream, encoding=FILE_ENCODING, newline="", write_through=True)
        try:
            writer = csv.writer(text, lineterminator=LINE_TERMINATOR)
            writer.writerow([str(column) for column in STORED_COLUMNS])
            writer.writerows(self._encoded_rows(series))
            text.flush()
        finally:
            text.detach()

    def read(self, stream: IO[bytes], sensor_id: SensorId, origin: str) -> MeasurementSeries:
        """Parse a CSV file written by :meth:`write`.

        Parameters
        ----------
        stream : binary file object
            Source.
        sensor_id : SensorId
            The sensor the file belongs to.
        origin : str
            File name for error messages.

        Returns
        -------
        MeasurementSeries
            The stored rows (always with a ``source`` column) and ``qc = 0``.

        Raises
        ------
        StoreFormatError
            On a wrong header, a wrong number of fields, a malformed timestamp or value, or
            timestamps that are not strictly increasing.
        """
        text = io.TextIOWrapper(stream, encoding=FILE_ENCODING, newline="")
        try:
            rows = list(csv.reader(text, strict=True))
        except (UnicodeDecodeError, csv.Error) as error:
            raise StoreFormatError(f"{origin}: not a readable CSV file: {error}") from error
        finally:
            text.detach()
        expected_header = [str(column) for column in STORED_COLUMNS]
        if not rows or rows[0] != expected_header:
            raise StoreFormatError(
                f"{origin}: header must be {','.join(expected_header)!r}, "
                f"got {','.join(rows[0]) if rows else 'an empty file'!r}."
            )
        return self._decoded_series(rows[1:], sensor_id, origin)

    def _encoded_rows(self, series: MeasurementSeries) -> Iterator[list[str]]:
        frame = series.frame
        timestamps = _format_timestamps(frame[Column.TIMESTAMP])
        temps = frame[Column.TEMP].to_numpy()
        humidities = frame[Column.RH].to_numpy()
        if Column.SOURCE in frame.columns:
            sources = frame[Column.SOURCE].astype("str").tolist()
        else:
            sources = [""] * len(frame)
        for timestamp, temp_c, rh_pct, source in zip(
            timestamps, temps, humidities, sources, strict=True
        ):
            yield [timestamp, _format_value(temp_c), _format_value(rh_pct), source]

    def _decoded_series(
        self, rows: list[list[str]], sensor_id: SensorId, origin: str
    ) -> MeasurementSeries:
        first_data_line = 2
        n_fields = len(STORED_COLUMNS)
        for line, row in enumerate(rows, start=first_data_line):
            if len(row) != n_fields:
                raise StoreFormatError(f"{origin}:{line}: expected {n_fields} fields, got {row}.")
            if _TIMESTAMP_PATTERN.fullmatch(row[0]) is None:
                raise StoreFormatError(f"{origin}:{line}: malformed timestamp {row[0]!r}.")
        try:
            timestamps = pd.to_datetime([row[0] for row in rows], format="ISO8601", utc=True)
        except ValueError as error:
            raise StoreFormatError(f"{origin}: invalid timestamp: {error}") from error
        if not (timestamps.is_monotonic_increasing and timestamps.is_unique):
            raise StoreFormatError(f"{origin}: timestamps are not strictly increasing.")
        temps = [_parse_value(row[1], origin, line) for line, row in enumerate(rows, 2)]
        humidities = [_parse_value(row[2], origin, line) for line, row in enumerate(rows, 2)]
        try:
            return MeasurementSeries.from_records(
                sensor_id,
                pd.DatetimeIndex(timestamps),
                temps,
                humidities,
                source=[row[3] for row in rows],
            )
        except SchemaError as error:
            raise StoreFormatError(f"{origin}: {error}") from error


def _format_timestamps(timestamps_utc: pd.Series) -> list[str]:
    """Format UTC timestamps as ISO 8601 with ``Z`` and an optional trimmed fraction."""
    seconds = timestamps_utc.dt.strftime("%Y-%m-%dT%H:%M:%S").tolist()
    instants_ns = timestamps_utc.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    fractions_ns = instants_ns.astype("datetime64[ns]").view(np.int64) % NANOSECONDS_PER_SECOND
    return [
        f"{whole}.{int(fraction):0{FRACTION_DIGITS_NS}d}".rstrip("0") + "Z"
        if fraction
        else f"{whole}Z"
        for whole, fraction in zip(seconds, fractions_ns, strict=True)
    ]


def _format_value(value: float) -> str:
    """Format one measured value; ``NaN`` becomes an empty field."""
    if math.isnan(value):
        return ""
    return np.format_float_positional(value, unique=True, trim="k", min_digits=MIN_FRACTION_DIGITS)


def _parse_value(text: str, origin: str, line: int) -> float:
    """Parse one stored value; an empty field is ``NaN``."""
    if not text:
        return math.nan
    if _VALUE_PATTERN.fullmatch(text) is None:
        raise StoreFormatError(f"{origin}:{line}: malformed value {text!r}.")
    return float(text)
