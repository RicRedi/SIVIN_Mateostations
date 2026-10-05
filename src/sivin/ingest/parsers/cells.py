"""Reading single cells of export tables: numbers with a decimal comma and local timestamps.

Both readers accept every cell type a CSV or spreadsheet reader can return (``str``,
``int``, ``float``, ``datetime``, ``None``, ...) and never raise for bad content: a cell they
cannot read is reported as unparseable.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Final

import numpy as np
import pandas as pd

from sivin.ingest.validation import BoolArray, FloatArray

_NUMBER: Final = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
"""A decimal number after the decimal comma was replaced by a point (no thousands separator)."""

_MINUS_SIGNS: Final = str.maketrans({chr(0x2212): "-", chr(0x2013): "-"})
"""Typographic minus and en dash, which spreadsheets sometimes write for negative numbers."""

_EARLIEST_TIMESTAMP: Final = datetime(1678, 1, 1)
_LATEST_TIMESTAMP: Final = datetime(2262, 1, 1)
"""Timestamps outside this range do not fit ``datetime64[ns]`` (1677-09-21 to 2262-04-11)."""

_ISO_FORMATS: Final = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
)
"""Year-first formats, e.g. ``2026-03-01 22:38:57`` (legacy ``generate_animation.py``)."""

_DAY_FIRST_FORMATS: Final = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
)
"""Day-first formats, e.g. ``5.1.2026 17:33:01`` (legacy ``sampl_freq_basic.py``)."""

_SPACE_AFTER_DOT: Final = re.compile(r"\.\s+(?=\d)")
"""Czech typography writes ``5. 1. 2026``; the space after the dot is removed before parsing."""


class NumberParser:
    """Read measured values written with a decimal comma or a decimal point.

    Empty cells are missing values; anything that is not a plain decimal number (text, a
    number with both ``,`` and ``.``, ``NaN``/``inf`` written as text, booleans, dates) is
    unparseable.
    """

    __slots__ = ()

    def parse(self, cells: Sequence[object]) -> tuple[FloatArray, BoolArray]:
        """Read a column of cells.

        Parameters
        ----------
        cells : sequence of object
            The cells of one column, one per data row.

        Returns
        -------
        tuple of numpy.ndarray
            ``(values, unparseable)``: ``float64`` values (``NaN`` where empty or
            unparseable) and a boolean mask of the unparseable cells.
        """
        values = np.full(len(cells), np.nan, dtype=np.float64)
        unparseable = np.zeros(len(cells), dtype=np.bool_)
        for position, cell in enumerate(cells):
            if _is_empty(cell):
                continue
            value = self.parse_cell(cell)
            if value is None:
                unparseable[position] = True
            else:
                values[position] = value
        return values, unparseable

    @staticmethod
    def parse_cell(cell: object) -> float | None:
        """Read one non-empty cell.

        Parameters
        ----------
        cell : object
            The cell value.

        Returns
        -------
        float or None
            The finite number, or ``None`` if the cell is not a number.
        """
        if isinstance(cell, bool):
            return None
        if isinstance(cell, int | float):
            try:
                number = float(cell)
            except OverflowError:
                return None
            return number if math.isfinite(number) else None
        if not isinstance(cell, str):
            return None
        text = "".join(cell.translate(_MINUS_SIGNS).split())
        if "," in text and "." in text:
            return None
        text = text.replace(",", ".")
        if _NUMBER.fullmatch(text) is None:
            return None
        number = float(text)
        return number if math.isfinite(number) else None


class TimestampParser:
    """Read naive local wall-clock timestamps from cells.

    Accepted are spreadsheet date-time cells and text in ISO form (``2026-03-01 22:38:57``) or
    numeric day-first form (``5.1.2026 17:33:01``; month first if ``day_first`` is false),
    with or without seconds. Date-only text (``2026-01-05``), ``datetime.date`` and
    ``datetime.time`` values, timezone-aware values and dates outside the ``datetime64[ns]``
    range are unparseable. A spreadsheet cell formatted as a date only is returned by openpyxl
    as a ``datetime`` at midnight and is therefore read as local midnight.

    Parameters
    ----------
    day_first : bool
        Read numeric dates with ``.`` or ``/`` day first.
    """

    __slots__ = ("_formats",)

    def __init__(self, day_first: bool) -> None:
        numeric = _DAY_FIRST_FORMATS if day_first else _month_first(_DAY_FIRST_FORMATS)
        self._formats = (*_ISO_FORMATS, *numeric)

    @property
    def formats(self) -> tuple[str, ...]:
        """The ``strptime`` formats tried in order."""
        return self._formats

    def parse(self, cells: Sequence[object]) -> pd.Series:
        """Read a column of cells.

        Parameters
        ----------
        cells : sequence of object
            The cells of one column, one per data row.

        Returns
        -------
        pandas.Series
            Naive ``datetime64[ns]`` timestamps; ``NaT`` where a cell is empty or unparseable.
        """
        stamps = [self.parse_cell(cell) for cell in cells]
        return pd.Series(pd.DatetimeIndex(stamps, dtype="datetime64[ns]"), dtype="datetime64[ns]")

    def parse_cell(self, cell: object) -> datetime | None:
        """Read one cell.

        Parameters
        ----------
        cell : object
            The cell value.

        Returns
        -------
        datetime.datetime or None
            The naive local timestamp, or ``None``.
        """
        stamp: datetime | None = None
        if isinstance(cell, datetime):
            stamp = cell if cell.tzinfo is None else None
        elif isinstance(cell, str):
            stamp = self._parse_text(cell)
        if stamp is None or not _EARLIEST_TIMESTAMP <= stamp < _LATEST_TIMESTAMP:
            return None
        return stamp

    def _parse_text(self, text: str) -> datetime | None:
        cleaned = " ".join(_SPACE_AFTER_DOT.sub(".", text).split())
        for timestamp_format in self._formats:
            try:
                return datetime.strptime(cleaned, timestamp_format)
            except ValueError:
                continue
        return None


class DateOrderCheck:
    """Guard against day and month swapped in numeric text dates.

    A month-first file whose days are all 12 or less is read day first without any parse
    error, but every change of day becomes a step of about one month. The check counts the
    *long* steps (longer than ``max_regular_step_s``) between consecutive timestamps under the
    configured and the alternative date order. The date order is ambiguous if the alternative
    order reads more cells, or reads as many and has fewer long steps.

    Parameters
    ----------
    day_first : bool
        The configured date order.
    max_regular_step_s : float
        Steps longer than this (in seconds) count as long.
    """

    __slots__ = ("_alternative", "_max_step")

    def __init__(self, day_first: bool, max_regular_step_s: float) -> None:
        self._alternative = TimestampParser(not day_first)
        self._max_step = pd.Timedelta(seconds=max_regular_step_s)

    def problem(self, cells: Sequence[object], parsed: pd.Series) -> str | None:
        """Return why the date order is ambiguous, or ``None``.

        Parameters
        ----------
        cells : sequence of object
            The timestamp cells, one per data row.
        parsed : pandas.Series
            The cells read with the configured date order.

        Returns
        -------
        str or None
            A message if the alternative date order fits the data clearly better.
        """
        n_parsed = int(parsed.notna().sum())
        if n_parsed < len(cells):
            alternative = self._alternative.parse(cells)
            n_alternative = int(alternative.notna().sum())
            if n_alternative > n_parsed:
                return (
                    f"Ambiguous date order: {n_parsed} of {len(cells)} timestamp(s) read as "
                    f"configured, {n_alternative} with day and month swapped. Check 'day_first'."
                )
        long_steps = self._long_steps(parsed)
        if not long_steps:
            return None
        alternative = self._alternative.parse(cells)
        if int(alternative.notna().sum()) < n_parsed:
            return None
        alternative_long = self._long_steps(alternative)
        if alternative_long >= long_steps:
            return None
        return (
            f"Ambiguous date order: read as configured, {long_steps} step(s) between consecutive "
            f"timestamps are longer than {self._max_step}; with day and month swapped only "
            f"{alternative_long}. Check 'day_first'."
        )

    def _long_steps(self, parsed: pd.Series) -> int:
        steps = parsed.dropna().diff().abs()
        return int((steps > self._max_step).sum())


def _month_first(formats: Sequence[str]) -> tuple[str, ...]:
    return tuple(fmt.replace("%d", "%_").replace("%m", "%d").replace("%_", "%m") for fmt in formats)


def _is_empty(cell: object) -> bool:
    return cell is None or (isinstance(cell, str) and not cell.strip())
