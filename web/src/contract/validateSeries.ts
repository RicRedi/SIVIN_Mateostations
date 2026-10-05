import { ContractError } from './ContractError';
import { FieldReader } from './FieldReader';
import { DAILY_VALUE_COLUMNS, type DailyFile, type DailyValueColumn, type RawMonthFile } from './types';
import type { ContractWarning } from './validateMeta';

const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** Optional columns of `raw/<YYYY-MM>.json` (WP-1.9). */
const OPTIONAL_RAW_COLUMNS = ['precip_mm', 'battery_v'] as const;

/** Optional columns of `daily.json` (WP-1.9; `precip_n_samples` WP-3.2). */
const OPTIONAL_DAILY_COLUMNS = ['precip_sum_mm', 'precip_n_samples', 'battery_min_v'] as const;

type NullableColumn = readonly (number | null)[];

const warnOnConsole: ContractWarning = (message) => {
  console.warn(message);
};

/**
 * Read the optional nullable number columns that are present. An absent field (or one that is
 * `undefined`) is left out of the result. A present but malformed field (not an array, a wrong
 * length, a non-number item) is also left out and reported to `warn`: tolerant reading of
 * optional contract fields (plan §0.5), so a broken optional column never hides the
 * temperature and humidity of the file.
 */
function readOptionalColumns<K extends string>(
  reader: FieldReader,
  root: Readonly<Record<string, unknown>>,
  names: readonly K[],
  length: number,
  warn: ContractWarning,
): Partial<Record<K, NullableColumn>> {
  const columns: Partial<Record<K, NullableColumn>> = {};
  for (const name of names) {
    if (root[name] === undefined) {
      continue;
    }
    try {
      columns[name] = reader.list(root[name], `$.${name}`, reader.nullableNumberItem, length);
    } catch (error) {
      if (!(error instanceof ContractError)) {
        throw error;
      }
      warn(`${error.message}; optional field ignored`);
    }
  }
  return columns;
}

function readStrictlyIncreasingTimes(reader: FieldReader, value: unknown): readonly number[] {
  const t = reader.list(value, '$.t', reader.integerItem);
  for (let i = 1; i < t.length; i++) {
    const previous = t[i - 1] ?? Number.NEGATIVE_INFINITY;
    if ((t[i] ?? previous) <= previous) {
      reader.fail(`$.t[${i}]`, `must be greater than the previous time ${previous}`);
    }
  }
  return t;
}

/**
 * Validate `series/<sensor_id>/raw/<YYYY-MM>.json`.
 *
 * @param value - Parsed JSON.
 * @param file - File name used in error messages.
 * @param warn - Receives warnings about ignored malformed optional fields; default `console.warn`.
 * @returns The typed file; `t` is strictly increasing and all columns have its length. The
 *   optional `precip_mm` and `battery_v` are present only if the file has them well-formed.
 * @throws ContractError if a required part of the file does not match the contract.
 */
export function parseRawMonthFile(value: unknown, file: string, warn: ContractWarning = warnOnConsole): RawMonthFile {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  const t = readStrictlyIncreasingTimes(reader, root.t);
  return {
    sensor_id: reader.string(root.sensor_id, '$.sensor_id'),
    t,
    temp_c: reader.list(root.temp_c, '$.temp_c', reader.nullableNumberItem, t.length),
    rh_pct: reader.list(root.rh_pct, '$.rh_pct', reader.nullableNumberItem, t.length),
    ...readOptionalColumns(reader, root, OPTIONAL_RAW_COLUMNS, t.length, warn),
    qc: reader.list(root.qc, '$.qc', reader.integerItem, t.length),
  };
}

/**
 * Validate `series/<sensor_id>/daily.json`.
 *
 * @param value - Parsed JSON.
 * @param file - File name used in error messages.
 * @param warn - Receives warnings about ignored malformed optional fields; default `console.warn`.
 * @returns The typed file; all columns have the length of `date`. The optional
 *   `precip_sum_mm`, `precip_n_samples` and `battery_min_v` are present only if the file has
 *   them well-formed.
 * @throws ContractError if a required part of the file does not match the contract.
 */
export function parseDailyFile(value: unknown, file: string, warn: ContractWarning = warnOnConsole): DailyFile {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  const date = reader.list(root.date, '$.date', (item, path) => {
    const text = reader.string(item, path);
    if (!ISO_DATE_PATTERN.test(text)) {
      reader.fail(path, `must be a date YYYY-MM-DD, got "${text}"`);
    }
    return text;
  });
  const columns = {} as Record<DailyValueColumn, readonly (number | null)[]>;
  for (const column of DAILY_VALUE_COLUMNS) {
    columns[column] = reader.list(root[column], `$.${column}`, reader.nullableNumberItem, date.length);
  }
  return {
    sensor_id: reader.string(root.sensor_id, '$.sensor_id'),
    date,
    ...columns,
    ...readOptionalColumns(reader, root, OPTIONAL_DAILY_COLUMNS, date.length, warn),
    coverage: reader.list(root.coverage, '$.coverage', reader.numberItem, date.length),
  };
}
