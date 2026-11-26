/** Byte order mark: makes Excel read the file as UTF-8 (otherwise it guesses a legacy code page). */
export const UTF8_BOM = '﻿';

/** Field separator, decimal mark and line end of a CSV file. */
export interface CsvFormat {
  readonly separator: string;
  readonly decimalMark: string;
  readonly lineEnd: string;
}

/**
 * The export format: `;` as separator, which Excel in Czech and German locales expects and which
 * never collides with a decimal comma, and CRLF line ends (RFC 4180). The portal exports with a
 * decimal comma in every UI language (owner decision 2026-11-26).
 */
export function csvFormat(decimalMark: string): CsvFormat {
  return { separator: ';', decimalMark, lineEnd: '\r\n' };
}

/**
 * First characters that make Excel or LibreOffice read a cell as a formula (OWASP "CSV
 * injection"): `=`, `+`, `-`, `@`, tab and carriage return.
 */
const FORMULA_START = /^[=+\-@\t\r]/;
/** A plain number as {@link CsvWriter.number} writes it; never neutralised, so it stays numeric. */
const PLAIN_NUMBER = /^-?\d+(?:[.,]\d+)?$/;
/** Prefix that makes a spreadsheet show a cell as text. */
const TEXT_PREFIX = "'";

/** Characters besides the separator that force a quoted field. */
const NEEDS_QUOTES = /["\r\n]/;

/**
 * Writes a table as CSV text: a UTF-8 BOM, a header row and data rows. Fields that contain the
 * separator, a quote or a line break are quoted (RFC 4180), so labels such as
 * "Obec A; trať 2" stay one field. A text field that a spreadsheet would read as a formula
 * (starting with `=`, `+`, `-`, `@`, tab or CR, e.g. a sensor label `=HYPERLINK(…)` or `-5 m`)
 * is prefixed with `'`; plain numbers such as `-0,25` are left numeric. Numbers have a fixed number of decimals, no thousands
 * separator and the format's decimal mark.
 */
export class CsvWriter {
  constructor(private readonly format: CsvFormat) {}

  /**
   * @param value - Number to write; `null` / `undefined` / non-finite give an empty field.
   * @param decimals - Decimals after rounding.
   */
  number(value: number | null | undefined, decimals: number): string {
    if (value === null || value === undefined || !Number.isFinite(value)) {
      return '';
    }
    const text = value.toFixed(decimals);
    const unsigned = Number(text) === 0 ? text.replace(/^-/, '') : text;
    return unsigned.replace('.', this.format.decimalMark);
  }

  /** The complete file content, BOM first. */
  write(header: readonly string[], rows: readonly (readonly string[])[]): string {
    const lines = [header, ...rows].map((row) => row.map((field) => this.field(field)).join(this.format.separator));
    return `${UTF8_BOM}${lines.join(this.format.lineEnd)}${this.format.lineEnd}`;
  }

  private field(value: string): string {
    const text = FORMULA_START.test(value) && !PLAIN_NUMBER.test(value) ? `${TEXT_PREFIX}${value}` : value;
    return NEEDS_QUOTES.test(text) || text.includes(this.format.separator) ? `"${text.replaceAll('"', '""')}"` : text;
  }
}
