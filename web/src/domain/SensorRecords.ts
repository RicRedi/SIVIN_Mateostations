import type { DailyFile } from '../contract';
import { yearOf } from './isoDates';

/**
 * Frost threshold of the records in °C: a day with `T_min <= 0 °C` is a frost day for the first
 * and last frost (the frost threshold of plan §3.2 and of the frost hours in
 * `docs/indices/frost.md`, which also count `T <= 0 °C`).
 */
export const FROST_THRESHOLD_C = 0;

/**
 * Complete-day threshold used when the manifest has no `min_daily_coverage` (data built before
 * WP-3.4): the default of `analytics.min_daily_coverage` (0.9, `src/sivin/core/defaults.py`).
 */
export const DEFAULT_MIN_DAILY_COVERAGE = 0.9;

/** Last day (month-day) of the spring half of a season: the last spring frost is on or before it. */
const SPRING_LAST_MONTH_DAY = '06-30';
/** First day (month-day) of the autumn half of a season: the first autumn frost is on or after it. */
const AUTUMN_FIRST_MONTH_DAY = '07-01';

/** A record value with the (first) local date on which it occurred. */
export interface DatedValue {
  readonly value: number;
  readonly date: string;
}

/** Records and extremes of one sensor over a set of days. */
export interface RecordsSummary {
  /** Lowest daily minimum temperature (°C). */
  readonly tempMin: DatedValue | null;
  /** Highest daily maximum temperature (°C). */
  readonly tempMax: DatedValue | null;
  /** Highest daily mean temperature (°C). */
  readonly highestMean: DatedValue | null;
  /** Lowest daily mean temperature (°C). */
  readonly lowestMean: DatedValue | null;
  /** Highest daily precipitation sum (mm); `null` if the data have none. */
  readonly maxPrecip: DatedValue | null;
  /** Last day of Jan 1 – Jun 30 with `T_min <= 0 °C`; only for a season. */
  readonly lastSpringFrost: string | null;
  /** First day of Jul 1 – Dec 31 with `T_min <= 0 °C`; only for a season. */
  readonly firstAutumnFrost: string | null;
  /** Days with a row in `daily.json` in the range. */
  readonly daysTotal: number;
  /** Complete days (coverage at least the threshold) used for the records. */
  readonly daysUsed: number;
}

type Column = readonly (number | null)[];
type Pick = (candidate: number, best: number) => boolean;

const lower: Pick = (candidate, best) => candidate < best;
const higher: Pick = (candidate, best) => candidate > best;

/**
 * Records and extremes of a sensor computed from its `daily.json`: only **complete** days count
 * (coverage at least `minDailyCoverage`, the `analytics.min_daily_coverage` rule of the indices),
 * so a day with a few hours of data cannot set a record. Ties keep the earliest date.
 */
export class RecordsCalculator {
  /**
   * @param minDailyCoverage - Share (0-1) of a day with valid samples for it to count.
   */
  constructor(readonly minDailyCoverage: number) {}

  /** Records of the calendar year `season`, with the first and last frost. */
  season(daily: DailyFile, season: number): RecordsSummary {
    const rows = this.rows(daily, (date) => yearOf(date) === season);
    const complete = rows.filter((i) => this.isComplete(daily, i));
    const frost = complete.filter((i) => (daily.temp_min[i] ?? Number.POSITIVE_INFINITY) <= FROST_THRESHOLD_C);
    const frostDates = frost.map((i) => daily.date[i] ?? '');
    const spring = frostDates.filter((date) => date.slice(5) <= SPRING_LAST_MONTH_DAY);
    const autumn = frostDates.filter((date) => date.slice(5) >= AUTUMN_FIRST_MONTH_DAY);
    return {
      ...this.extremes(daily, complete, rows.length),
      lastSpringFrost: spring.at(-1) ?? null,
      firstAutumnFrost: autumn[0] ?? null,
    };
  }

  /** Records over every day of the file; no first or last frost (they belong to a season). */
  allData(daily: DailyFile): RecordsSummary {
    const rows = this.rows(daily, () => true);
    const complete = rows.filter((i) => this.isComplete(daily, i));
    return { ...this.extremes(daily, complete, rows.length), lastSpringFrost: null, firstAutumnFrost: null };
  }

  private rows(daily: DailyFile, keep: (date: string) => boolean): number[] {
    return daily.date.flatMap((date, i) => (keep(date) ? [i] : []));
  }

  private isComplete(daily: DailyFile, i: number): boolean {
    return (daily.coverage[i] ?? 0) >= this.minDailyCoverage;
  }

  private extremes(
    daily: DailyFile,
    complete: readonly number[],
    daysTotal: number,
  ): Omit<RecordsSummary, 'lastSpringFrost' | 'firstAutumnFrost'> {
    const best = (column: Column | undefined, pick: Pick): DatedValue | null => {
      let found: DatedValue | null = null;
      for (const i of complete) {
        const value = column?.[i] ?? null;
        if (value !== null && (found === null || pick(value, found.value))) {
          found = { value, date: daily.date[i] ?? '' };
        }
      }
      return found;
    };
    return {
      tempMin: best(daily.temp_min, lower),
      tempMax: best(daily.temp_max, higher),
      highestMean: best(daily.temp_mean, higher),
      lowestMean: best(daily.temp_mean, lower),
      maxPrecip: best(daily.precip_sum_mm, higher),
      daysTotal,
      daysUsed: complete.length,
    };
  }
}
