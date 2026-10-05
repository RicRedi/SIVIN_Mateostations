import { MS_PER_SECOND } from '../domain/units';

const MONTH_KEY_LENGTH = 'YYYY-MM'.length;

/**
 * `YYYY-MM` keys of all UTC calendar months that overlap `[startT, endT)`.
 *
 * @param startT - Window start, Unix seconds UTC.
 * @param endT - Window end (exclusive), Unix seconds UTC.
 * @returns Keys in ascending order; empty if `endT <= startT`.
 */
export function utcMonthKeys(startT: number, endT: number): readonly string[] {
  if (endT <= startT) {
    return [];
  }
  const start = new Date(startT * MS_PER_SECOND);
  const last = new Date((endT - 1) * MS_PER_SECOND);
  const keys: string[] = [];
  let year = start.getUTCFullYear();
  let monthIndex = start.getUTCMonth();
  while (year < last.getUTCFullYear() || (year === last.getUTCFullYear() && monthIndex <= last.getUTCMonth())) {
    keys.push(new Date(Date.UTC(year, monthIndex, 1)).toISOString().slice(0, MONTH_KEY_LENGTH));
    monthIndex += 1;
    if (monthIndex === MONTHS_PER_YEAR) {
      monthIndex = 0;
      year += 1;
    }
  }
  return keys;
}

const MONTHS_PER_YEAR = 12;
