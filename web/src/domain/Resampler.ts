import { QcMask } from './QcFlags';
import type { RawSeries, RawVariable } from './RawSeries';
import { TimeSeries } from './TimeSeries';
import { SECONDS_PER_HOUR } from './units';

/**
 * Nominal sampling step of the sensors (MIGRATION_PLAN.md §2.7: "periodou ~1825 s").
 */
export const NOMINAL_STEP_S = 1825;

/**
 * Raw samples farther apart than this are drawn with a gap: two missed samples plus slack for
 * clock drift.
 */
export const RAW_GAP_THRESHOLD_S = 3 * NOMINAL_STEP_S;

/**
 * Turns raw samples into chart series: QC-masked raw values or hourly means. Daily values are
 * not computed here; they come from `daily.json` (see {@link dailyColumnSeries}).
 */
export class Resampler {
  /** @param mask - Decides which QC flags exclude a sample. */
  constructor(private readonly mask: QcMask) {}

  /** Raw values with excluded samples set to `null` and gaps broken for drawing. */
  raw(series: RawSeries, variable: RawVariable): TimeSeries {
    return series.variable(variable, this.mask).withGapBreaks(RAW_GAP_THRESHOLD_S);
  }

  /**
   * Hourly means over UTC hours `[h, h + 3600)` covering `[startT, endT)`.
   *
   * Each output time is the start of its hour. An hour without a valid (non-null, not excluded)
   * value is `null`, so gaps stay visible.
   *
   * @param series - Raw samples.
   * @param variable - Variable to average.
   * @param startT - Window start, Unix seconds UTC.
   * @param endT - Window end (exclusive), Unix seconds UTC.
   */
  hourlyMeans(series: RawSeries, variable: RawVariable, startT: number, endT: number): TimeSeries {
    const values = series.variable(variable, this.mask);
    const firstHourT = Math.floor(startT / SECONDS_PER_HOUR) * SECONDS_PER_HOUR;
    const hourCount = Math.max(0, Math.ceil((endT - firstHourT) / SECONDS_PER_HOUR));
    const sums = new Array<number>(hourCount).fill(0);
    const counts = new Array<number>(hourCount).fill(0);
    values.t.forEach((t, i) => {
      const value = values.values[i];
      const bin = Math.floor((t - firstHourT) / SECONDS_PER_HOUR);
      if (value === null || value === undefined || t < startT || t >= endT || bin >= hourCount) {
        return;
      }
      sums[bin] = (sums[bin] ?? 0) + value;
      counts[bin] = (counts[bin] ?? 0) + 1;
    });
    const t = sums.map((_, bin) => firstHourT + bin * SECONDS_PER_HOUR);
    const means = sums.map((sum, bin) => {
      const count = counts[bin] ?? 0;
      return count === 0 ? null : sum / count;
    });
    return TimeSeries.of(t, means);
  }
}
