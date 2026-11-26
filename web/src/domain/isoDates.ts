import { MS_PER_SECOND, SECONDS_PER_DAY } from './units';

/**
 * Calendar arithmetic on local dates written as `YYYY-MM-DD` (the dates of `daily.json` and of
 * the index files). A calendar date has no time zone, so the arithmetic runs on UTC midnights,
 * where every day has exactly 86 400 s.
 */
const MS_PER_DAY = SECONDS_PER_DAY * MS_PER_SECOND;
const ISO_DATE_LENGTH = 10;

function toMs(isoDate: string): number {
  return Date.parse(`${isoDate}T00:00:00Z`);
}

/** The date `days` days after `isoDate` (negative: before). */
export function addDays(isoDate: string, days: number): string {
  return new Date(toMs(isoDate) + days * MS_PER_DAY).toISOString().slice(0, ISO_DATE_LENGTH);
}

/** Whole days from `start` to `end` (`end` − `start`; 0 for the same day). */
export function daysBetween(start: string, end: string): number {
  return Math.round((toMs(end) - toMs(start)) / MS_PER_DAY);
}

/** Every date from `start` to `end`, both inclusive; empty if `end` is before `start`. */
export function dateRange(start: string, end: string): readonly string[] {
  const count = daysBetween(start, end) + 1;
  return Array.from({ length: Math.max(0, count) }, (_, i) => addDays(start, i));
}

/** The calendar year of a date. */
export function yearOf(isoDate: string): number {
  return Number(isoDate.slice(0, 4));
}

/** Unix seconds of noon UTC of a date, for formatting a date without a time-zone shift. */
export function noonUtcSeconds(isoDate: string): number {
  return toMs(isoDate) / MS_PER_SECOND + SECONDS_PER_DAY / 2;
}
