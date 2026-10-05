import type { Resolution } from './TimeWindow';
import { SECONDS_PER_DAY, SECONDS_PER_HOUR } from './units';

/**
 * Longest window shown as raw samples: 8 days, so that a 7-day window across a DST change
 * (7 d + 1 h) still shows raw data (~380 samples per sensor).
 */
export const MAX_RAW_WINDOW_S = 8 * SECONDS_PER_DAY;

/** Longest window shown as hourly means: about two months (~1500 points per sensor). */
export const MAX_HOURLY_WINDOW_S = 62 * SECONDS_PER_DAY + SECONDS_PER_HOUR;

/** Picks a resolution that keeps the number of plotted points readable. */
export class ResolutionPolicy {
  constructor(
    private readonly maxRawS: number = MAX_RAW_WINDOW_S,
    private readonly maxHourlyS: number = MAX_HOURLY_WINDOW_S,
  ) {}

  /** @param durationS - Window length in seconds. */
  resolutionFor(durationS: number): Resolution {
    if (durationS <= this.maxRawS) {
      return 'raw';
    }
    return durationS <= this.maxHourlyS ? 'hourly' : 'daily';
  }
}
