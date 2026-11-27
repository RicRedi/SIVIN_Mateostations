import type { DailyFile } from '../contract';
import { daysBetween } from './isoDates';
import { NOMINAL_STEP_S } from './Resampler';
import { SECONDS_PER_DAY } from './units';

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

/** Month-days that bound the halves of a season: spring Jan 1 – Jun 30, autumn Jul 1 – Dec 31. */
const SEASON_START_MONTH_DAY = '01-01';
const SPRING_LAST_MONTH_DAY = '06-30';
const AUTUMN_FIRST_MONTH_DAY = '07-01';
const SEASON_END_MONTH_DAY = '12-31';

/**
 * Share (0-1) of the days of a half season that must be complete for the half to count as
 * observed, so that "no frost" may be stated. The default of `analytics.min_season_coverage`
 * (0.9), the rule the indices use for a complete period. A frost on one of the missing days
 * can still be missed; the UI therefore names the days the statement rests on when the half is
 * not fully covered.
 */
export const HALF_OBSERVED_SHARE = 0.9;

/** A record value with the (first) local date on which it occurred. */
export interface DatedValue {
  readonly value: number;
  readonly date: string;
}

/** A calendar period (local dates, inclusive) and the complete days used in it. */
export interface DaySpan {
  readonly start: string;
  readonly end: string;
  /** Calendar days of the period. */
  readonly periodDays: number;
  /** Complete days in the period. */
  readonly daysUsed: number;
  /** First and last complete day; `null` without one. */
  readonly firstUsed: string | null;
  readonly lastUsed: string | null;
}

/**
 * The first or last frost of a half season:
 * - `found`: a complete day with `T_min <= 0 °C`; `observed` says whether the half was observed
 *   (otherwise an earlier / later frost may have been missed),
 * - `none`: the half was observed ({@link HALF_OBSERVED_SHARE}) and had no frost day,
 * - `noneInData`: complete days exist but do not cover the half; none of them had frost,
 * - `noData`: no complete day in the half.
 */
export type FrostFinding =
  | { readonly kind: 'found'; readonly date: string; readonly observed: boolean; readonly span: DaySpan }
  | { readonly kind: 'none'; readonly span: DaySpan }
  | { readonly kind: 'noneInData'; readonly span: DaySpan }
  | { readonly kind: 'noData'; readonly span: DaySpan };

/** Records and extremes of one sensor over a period. */
export interface RecordsSummary {
  /** Lowest daily minimum temperature (°C). */
  readonly tempMin: DatedValue | null;
  /** Highest daily maximum temperature (°C). */
  readonly tempMax: DatedValue | null;
  /** Highest daily mean temperature (°C). */
  readonly highestMean: DatedValue | null;
  /** Lowest daily mean temperature (°C). */
  readonly lowestMean: DatedValue | null;
  /** Highest daily precipitation sum (mm) of a day with complete precipitation; `null` if none. */
  readonly maxPrecip: DatedValue | null;
  /** Last frost of Jan 1 – Jun 30; only for a season. */
  readonly lastSpringFrost: FrostFinding | null;
  /** First frost of Jul 1 – Dec 31; only for a season. */
  readonly firstAutumnFrost: FrostFinding | null;
  /** The period (season: the calendar year; all data: first to last day of the file). */
  readonly span: DaySpan;
}

type Column = readonly (number | null)[];
type Pick = (candidate: number, best: number) => boolean;

const lower: Pick = (candidate, best) => candidate < best;
const higher: Pick = (candidate, best) => candidate > best;

/**
 * Records and extremes of a sensor computed from its `daily.json`. Temperatures use only
 * **complete** days (coverage at least `minDailyCoverage`, the `analytics.min_daily_coverage`
 * rule of the indices), so a day with a few hours of data cannot set a record. The daily
 * precipitation sum does not follow that coverage (WP-1.9); a day counts for it when its
 * `precip_n_samples` cover the same share of the day ({@link isCompletePrecipitationDay}).
 * Ties keep the earliest date.
 */
export class RecordsCalculator {
  /**
   * @param minDailyCoverage - Share (0-1) of a day with valid samples for it to count.
   */
  constructor(readonly minDailyCoverage: number) {}

  /** Records of the calendar year `season`, with the first and last frost. */
  season(daily: DailyFile, season: number): RecordsSummary {
    const year = String(season);
    const at = (monthDay: string): string => `${year}-${monthDay}`;
    return {
      ...this.extremes(daily, at(SEASON_START_MONTH_DAY), at(SEASON_END_MONTH_DAY)),
      lastSpringFrost: this.frost(daily, at(SEASON_START_MONTH_DAY), at(SPRING_LAST_MONTH_DAY), 'last'),
      firstAutumnFrost: this.frost(daily, at(AUTUMN_FIRST_MONTH_DAY), at(SEASON_END_MONTH_DAY), 'first'),
    };
  }

  /** Records over every day of the file; no first or last frost (they belong to a season). */
  allData(daily: DailyFile): RecordsSummary {
    const start = daily.date[0] ?? '';
    const end = daily.date.at(-1) ?? '';
    return { ...this.extremes(daily, start, end), lastSpringFrost: null, firstAutumnFrost: null };
  }

  /**
   * Whether the precipitation sum of row `i` covers the complete-day share: `precip_n_samples`
   * × the nominal step (1830 s) ≥ `minDailyCoverage` × 86 400 s. Without `precip_n_samples`
   * (data before WP-3.2) no day qualifies.
   */
  isCompletePrecipitationDay(daily: DailyFile, i: number): boolean {
    const samples = daily.precip_n_samples?.[i] ?? null;
    return samples !== null && samples * NOMINAL_STEP_S >= this.minDailyCoverage * SECONDS_PER_DAY;
  }

  private completeRows(daily: DailyFile, start: string, end: string): number[] {
    return daily.date.flatMap((date, i) =>
      date >= start && date <= end && (daily.coverage[i] ?? 0) >= this.minDailyCoverage ? [i] : [],
    );
  }

  private span(daily: DailyFile, start: string, end: string, rows: readonly number[]): DaySpan {
    const first = rows[0];
    const last = rows.at(-1);
    return {
      start,
      end,
      periodDays: start === '' ? 0 : daysBetween(start, end) + 1,
      daysUsed: rows.length,
      firstUsed: first === undefined ? null : (daily.date[first] ?? null),
      lastUsed: last === undefined ? null : (daily.date[last] ?? null),
    };
  }

  private frost(daily: DailyFile, start: string, end: string, which: 'first' | 'last'): FrostFinding {
    const rows = this.completeRows(daily, start, end);
    const span = this.span(daily, start, end, rows);
    const observed = span.daysUsed >= HALF_OBSERVED_SHARE * span.periodDays;
    const frostDates = rows
      .filter((i) => (daily.temp_min[i] ?? Number.POSITIVE_INFINITY) <= FROST_THRESHOLD_C)
      .map((i) => daily.date[i] ?? '');
    const date = which === 'first' ? frostDates[0] : frostDates.at(-1);
    if (date !== undefined) {
      return { kind: 'found', date, observed, span };
    }
    if (rows.length === 0) {
      return { kind: 'noData', span };
    }
    return observed ? { kind: 'none', span } : { kind: 'noneInData', span };
  }

  private extremes(daily: DailyFile, start: string, end: string): Omit<RecordsSummary, 'lastSpringFrost' | 'firstAutumnFrost'> {
    const complete = this.completeRows(daily, start, end);
    const best = (rows: readonly number[], column: Column | undefined, pick: Pick): DatedValue | null => {
      let found: DatedValue | null = null;
      for (const i of rows) {
        const value = column?.[i] ?? null;
        if (value !== null && (found === null || pick(value, found.value))) {
          found = { value, date: daily.date[i] ?? '' };
        }
      }
      return found;
    };
    const precipRows = daily.date.flatMap((date, i) =>
      date >= start && date <= end && this.isCompletePrecipitationDay(daily, i) ? [i] : [],
    );
    return {
      tempMin: best(complete, daily.temp_min, lower),
      tempMax: best(complete, daily.temp_max, higher),
      highestMean: best(complete, daily.temp_mean, higher),
      lowestMean: best(complete, daily.temp_mean, lower),
      maxPrecip: best(precipRows, daily.precip_sum_mm, higher),
      span: this.span(daily, start, end, complete),
    };
  }
}
