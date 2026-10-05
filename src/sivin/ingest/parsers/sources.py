"""Reading the raw cells of export files: CSV text and Excel workbooks.

The readers only turn a file into :class:`CellGrid` objects (rows of raw cell values); they do
not interpret headers or values. A file that cannot be read raises :class:`GridReadError`,
which the parsers turn into a validation finding.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from pathlib import Path

import openpyxl  # type: ignore[import-untyped]  # no stubs installed (types-openpyxl)

logger = logging.getLogger(__name__)

type Cell = object
"""A raw cell value: ``str``, ``int``, ``float``, ``datetime``, ``None``, ..."""

type Row = tuple[Cell, ...]
"""The cells of one row, left to right."""


class GridReadError(Exception):
    """Raised when a file cannot be read into cells (corrupt, truncated, undecodable)."""


@dataclass(frozen=True)
class CellGrid:
    """The raw cells of one table.

    Attributes
    ----------
    name : str
        Table name: the worksheet name, or the file name for CSV files.
    rows : tuple of tuple of object
        The rows in file order; ``rows[i]`` is source row ``i + 1``.
    """

    name: str
    rows: tuple[Row, ...]


class CsvGridReader:
    """Read a delimited text file.

    Parameters
    ----------
    delimiter : str
        Field delimiter, e.g. ``";"``.
    encodings : tuple of str
        Text encodings tried in order.
    """

    __slots__ = ("_delimiter", "_encodings")

    def __init__(self, delimiter: str, encodings: tuple[str, ...]) -> None:
        self._delimiter = delimiter
        self._encodings = encodings

    def read(self, path: Path) -> CellGrid:
        """Read the file.

        Parameters
        ----------
        path : pathlib.Path
            The CSV file.

        Returns
        -------
        CellGrid
            One table named after the file; every cell is a string.

        Raises
        ------
        GridReadError
            If the file cannot be read or decoded, or is not valid CSV.
        """
        text = self._decode(path)
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=self._delimiter)
            rows = tuple(tuple(row) for row in reader)
        except csv.Error as error:
            raise GridReadError(f"invalid CSV: {error}") from error
        return CellGrid(path.name, rows)

    def _decode(self, path: Path) -> str:
        try:
            data = path.read_bytes()
        except OSError as error:
            raise GridReadError(str(error)) from error
        for encoding in self._encodings:
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                continue
            if "\x00" in text:
                raise GridReadError("binary content (NUL characters) in a text file")
            logger.debug("%s decoded as %s.", path.name, encoding)
            return text
        raise GridReadError(f"not valid text in any of the encodings {list(self._encodings)}")


class WorkbookReader:
    """Read all worksheets of an Excel workbook (``.xlsx``/``.xlsm``) with openpyxl.

    Cells are read as stored values (``data_only``): numbers, strings, ``datetime`` for cells
    with a date format, ``None`` for empty cells.
    """

    __slots__ = ()

    def read(self, path: Path) -> tuple[CellGrid, ...]:
        """Read every worksheet.

        Parameters
        ----------
        path : pathlib.Path
            The workbook.

        Returns
        -------
        tuple of CellGrid
            One table per worksheet, in workbook order.

        Raises
        ------
        GridReadError
            If the workbook cannot be opened or read (corrupt or truncated archive, not a
            workbook).
        """
        try:
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as error:
            # openpyxl and zipfile raise many unrelated exception types for damaged archives
            # (BadZipFile, KeyError, ValueError, TypeError, XML parse errors, ...); every one
            # of them means "this file is not a readable workbook".
            raise GridReadError(f"not a readable workbook: {error!r}") from error
        try:
            return tuple(
                CellGrid(
                    sheet.title, tuple(tuple(row) for row in sheet.iter_rows(values_only=True))
                )
                for sheet in workbook.worksheets
            )
        except Exception as error:
            # Same as above: damaged sheet XML surfaces as arbitrary exception types.
            raise GridReadError(f"damaged worksheet: {error!r}") from error
        finally:
            workbook.close()
