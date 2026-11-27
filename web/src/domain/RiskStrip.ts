import type { IndexDaily } from '../contract';
import { dateRange } from './isoDates';

/**
 * Traffic-light tone of a daily risk level: the lowest level is `low` (green), the highest of
 * three or more levels `high` (red), every other level `elevated` (amber). With two levels the
 * upper one is `elevated`: a two-level scale (e.g. "no wetness" / "wetness") says that
 * something happened, not that the risk is high.
 */
export type RiskTone = 'low' | 'elevated' | 'high';

/** Fewest levels for which the highest one is shown as `high`. */
const MIN_LEVELS_WITH_HIGH = 3;

/** Tone of the level at position `rank` (0 = lowest) of `levelCount` ascending levels. */
export function toneForRank(rank: number, levelCount: number): RiskTone {
  if (rank <= 0) {
    return 'low';
  }
  return rank === levelCount - 1 && levelCount >= MIN_LEVELS_WITH_HIGH ? 'high' : 'elevated';
}

/** A level with its tone (`null` = no data). */
export interface LevelTone {
  readonly level: string | null;
  readonly tone: RiskTone | null;
}

/** The levels in order with their tones, then "no data" (the legend of a strip). */
export function levelTones(levels: readonly string[]): readonly LevelTone[] {
  return [...levels.map((level, rank) => ({ level, tone: toneForRank(rank, levels.length) })), { level: null, tone: null }];
}

/** One day of a risk strip; `level` and `tone` are `null` on a day without enough data. */
export interface RiskDay {
  readonly date: string;
  readonly level: string | null;
  readonly value: number | null;
  readonly tone: RiskTone | null;
}

/** Number of days per level (`null` = no data), in the order of the levels, no data last. */
export interface LevelCount extends LevelTone {
  readonly days: number;
}

/**
 * The daily risk of one index and sensor over the whole index period: one {@link RiskDay} per
 * day from `start` to `end`. A day the file does not list, or lists with `level: null`, has no
 * data (shown grey, never green).
 */
export class RiskStrip {
  private constructor(
    readonly levels: readonly string[],
    readonly days: readonly RiskDay[],
  ) {}

  static fromDaily(daily: IndexDaily): RiskStrip {
    const byDate = new Map<string, { level: string | null; value: number | null }>();
    daily.date.forEach((date, i) => {
      byDate.set(date, { level: daily.level[i] ?? null, value: daily.value[i] ?? null });
    });
    const tone = (level: string | null): RiskTone | null =>
      level === null ? null : toneForRank(daily.levels.indexOf(level), daily.levels.length);
    const days = dateRange(daily.start, daily.end).map((date) => {
      const entry = byDate.get(date);
      const level = entry?.level ?? null;
      return { date, level, value: level === null ? null : (entry?.value ?? null), tone: tone(level) };
    });
    return new RiskStrip(daily.levels, days);
  }

  /** Days per level in level order, then the days without data. */
  counts(): readonly LevelCount[] {
    const count = (level: string | null): number => this.days.filter((day) => day.level === level).length;
    return levelTones(this.levels).map((entry) => ({ ...entry, days: count(entry.level) }));
  }

  /** The last day with data, or `null`. */
  lastKnown(): RiskDay | null {
    return [...this.days].reverse().find((day) => day.level !== null) ?? null;
  }
}
