import type { Resolution } from './TimeWindow';
import type { ResolutionChoice } from './WindowSpec';
import { SECONDS_PER_DAY, SECONDS_PER_HOUR } from './units';

/**
 * Longest window shown as raw samples automatically: 8 days, so that a 7-day window across a
 * DST change (7 d + 1 h) still shows raw data (~380 samples per sensor).
 */
export const MAX_RAW_WINDOW_S = 8 * SECONDS_PER_DAY;

/** Longest window shown as hourly means automatically: about two months (~1500 points). */
export const MAX_HOURLY_WINDOW_S = 62 * SECONDS_PER_DAY + SECONDS_PER_HOUR;

/**
 * Point cap for an explicitly chosen raw resolution: 31 days (+1 h for DST), about 1466 samples
 * per sensor at the nominal 1830 s step. Longer windows fall back to hourly means.
 */
export const MAX_EXPLICIT_RAW_WINDOW_S = 31 * SECONDS_PER_DAY + SECONDS_PER_HOUR;

/**
 * Point cap for an explicitly chosen hourly resolution: 92 days (+1 h), at most 2209 points per
 * sensor. Longer windows fall back to daily values.
 */
export const MAX_EXPLICIT_HOURLY_WINDOW_S = 92 * SECONDS_PER_DAY + SECONDS_PER_HOUR;

/** Picks a resolution that keeps the number of plotted points readable and bounded. */
export class ResolutionPolicy {
  /** Automatic resolution for a window of `durationS` seconds. */
  resolutionFor(durationS: number): Resolution {
    if (durationS <= MAX_RAW_WINDOW_S) {
      return 'raw';
    }
    return durationS <= MAX_HOURLY_WINDOW_S ? 'hourly' : 'daily';
  }

  /**
   * Resolution actually used: the automatic one for `auto`, otherwise the user's choice made
   * coarser where it would exceed the point caps.
   */
  resolve(choice: ResolutionChoice, durationS: number): Resolution {
    if (choice === 'auto') {
      return this.resolutionFor(durationS);
    }
    if (choice === 'raw' && durationS > MAX_EXPLICIT_RAW_WINDOW_S) {
      return this.resolve('hourly', durationS);
    }
    if (choice === 'hourly' && durationS > MAX_EXPLICIT_HOURLY_WINDOW_S) {
      return 'daily';
    }
    return choice;
  }
}
