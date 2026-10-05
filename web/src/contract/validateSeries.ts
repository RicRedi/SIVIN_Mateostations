import { FieldReader } from './FieldReader';
import { DAILY_VALUE_COLUMNS, type DailyFile, type DailyValueColumn, type RawMonthFile } from './types';

const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

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
 * @returns The typed file; `t` is strictly increasing and all columns have its length.
 * @throws ContractError if the file does not match the contract.
 */
export function parseRawMonthFile(value: unknown, file: string): RawMonthFile {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  const t = readStrictlyIncreasingTimes(reader, root.t);
  return {
    sensor_id: reader.string(root.sensor_id, '$.sensor_id'),
    t,
    temp_c: reader.list(root.temp_c, '$.temp_c', reader.nullableNumberItem, t.length),
    rh_pct: reader.list(root.rh_pct, '$.rh_pct', reader.nullableNumberItem, t.length),
    qc: reader.list(root.qc, '$.qc', reader.integerItem, t.length),
  };
}

/**
 * Validate `series/<sensor_id>/daily.json`.
 *
 * @param value - Parsed JSON.
 * @param file - File name used in error messages.
 * @returns The typed file; all columns have the length of `date`.
 * @throws ContractError if the file does not match the contract.
 */
export function parseDailyFile(value: unknown, file: string): DailyFile {
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
    coverage: reader.list(root.coverage, '$.coverage', reader.numberItem, date.length),
  };
}
