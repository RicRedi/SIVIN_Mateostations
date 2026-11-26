import { AUXILIARY_DISPLAY_EXCLUDE_MASK, QcMask } from './QcFlags';
import type { RawColumn, RawSeries } from './RawSeries';
import { TimeSeries } from './TimeSeries';
import { SECONDS_PER_HOUR } from './units';

/**
 * Nominal sampling step of the sensors: 1830 s, the median step of the first real export
 * (sensor 77799986, MIGRATION_PLAN.md §0.6.1; the legacy estimate was 1825 s). Mirrors the
 * default of `time.expected_interval_s` in `config/sivin.yaml`.
 */
export const NOMINAL_STEP_S = 1830;

/**
 * Raw samples farther apart than this are drawn with a gap: two missed samples plus slack for
 * clock drift.
 */
export const RAW_GAP_THRESHOLD_S = 3 * NOMINAL_STEP_S;

/**
 * A precipitation sample whose predecessor lies farther back than this covers at least one
 * missed sample (1.5 nominal steps leaves room for clock jitter); its hour is incomplete.
 */
export const MAX_PRECIP_INTERVAL_S = 1.5 * NOMINAL_STEP_S;

const HALF_HOUR_S = SECONDS_PER_HOUR / 2;
const HALF = 0.5;

/** UTC hour bins `[h, h + 3600)` covering a window, stamped at their centres. */
interface HourBins {
  readonly firstHourT: number;
  readonly count: number;
}

/**
 * Turns raw samples into chart series: QC-masked raw values, hourly means or hourly
 * precipitation sums. Daily
 * values are not computed here; they come from `daily.json` (see {@link dailyColumnSeries}).
 *
 * Temperature and humidity are masked with `mask`; the auxiliary precipitation and battery
 * voltage with `auxiliaryMask` (by default {@link AUXILIARY_DISPLAY_EXCLUDE_MASK}, as the pipeline).
 */
export class Resampler {
  /**
   * @param mask - Decides which QC flags exclude a temperature or humidity sample.
   * @param auxiliaryMask - Decides which QC flags exclude a precipitation or battery sample.
   */
  constructor(
    private readonly mask: QcMask,
    private readonly auxiliaryMask: QcMask = new QcMask(AUXILIARY_DISPLAY_EXCLUDE_MASK),
  ) {}

  /** Raw values with excluded samples set to `null` and gaps broken for drawing. */
  raw(series: RawSeries, variable: RawColumn): TimeSeries {
    return this.masked(series, variable).withGapBreaks(RAW_GAP_THRESHOLD_S);
  }

  /**
   * Hourly means over UTC hours `[h, h + 3600)` covering `[startT, endT)`.
   *
   * Each output time is the centre of its hour (`h + 1800`), so hourly means line up with raw
   * samples when the resolution changes. An hour without a valid (non-null, not excluded)
   * value is `null`, so gaps stay visible.
   *
   * @param series - Raw samples.
   * @param variable - Variable to average.
   * @param startT - Window start, Unix seconds UTC.
   * @param endT - Window end (exclusive), Unix seconds UTC.
   */
  hourlyMeans(series: RawSeries, variable: RawColumn, startT: number, endT: number): TimeSeries {
    const values = this.masked(series, variable);
    const bins = Resampler.bins(startT, endT);
    const sums = new Array<number>(bins.count).fill(0);
    const counts = new Array<number>(bins.count).fill(0);
    values.t.forEach((t, i) => {
      const value = values.values[i];
      const bin = Math.floor((t - bins.firstHourT) / SECONDS_PER_HOUR);
      if (value === null || value === undefined || t < startT || t >= endT || bin >= bins.count) {
        return;
      }
      sums[bin] = (sums[bin] ?? 0) + value;
      counts[bin] = (counts[bin] ?? 0) + 1;
    });
    return Resampler.stamped(bins, sums.map((sum, bin) => {
      const count = counts[bin] ?? 0;
      return count === 0 ? null : sum / count;
    }));
  }

  /**
   * Precipitation per UTC hour (mm), stamped like {@link hourlyMeans}.
   *
   * A sample's `precip_mm` is the rain **since the previous sample**, i.e. of the interval
   * `(t_prev, t]`; it is counted in the hour that contains the interval's midpoint
   * `t − (t − t_prev)/2` (the first loaded sample is assumed to cover one nominal step). An hour
   * is shown only if it is **complete**: every sample counted in it has a valid (non-null, not
   * masked) value and covers at most {@link MAX_PRECIP_INTERVAL_S}. Otherwise — and for an hour
   * without samples — it is `null`, so a partial sum never looks like a complete one.
   *
   * @param series - Raw samples.
   * @param startT - Window start, Unix seconds UTC.
   * @param endT - Window end (exclusive), Unix seconds UTC.
   */
  hourlyPrecipitation(series: RawSeries, startT: number, endT: number): TimeSeries {
    const values = this.masked(series, 'precip_mm');
    const bins = Resampler.bins(startT, endT);
    const sums = new Array<number>(bins.count).fill(0);
    const counts = new Array<number>(bins.count).fill(0);
    const incomplete = new Array<boolean>(bins.count).fill(false);
    values.t.forEach((t, i) => {
      const previous = values.t[i - 1];
      const intervalS = previous === undefined ? NOMINAL_STEP_S : t - previous;
      const midT = t - intervalS * HALF;
      const bin = Math.floor((midT - bins.firstHourT) / SECONDS_PER_HOUR);
      if (midT < startT || midT >= endT || bin < 0 || bin >= bins.count) {
        return;
      }
      const value = values.values[i] ?? null;
      if (value === null || intervalS > MAX_PRECIP_INTERVAL_S) {
        incomplete[bin] = true;
        return;
      }
      sums[bin] = (sums[bin] ?? 0) + value;
      counts[bin] = (counts[bin] ?? 0) + 1;
    });
    return Resampler.stamped(bins, sums.map((sum, bin) => ((counts[bin] ?? 0) === 0 || incomplete[bin] === true ? null : sum)));
  }

  private masked(series: RawSeries, variable: RawColumn): TimeSeries {
    const isAuxiliary = variable === 'precip_mm' || variable === 'battery_v';
    return series.variable(variable, isAuxiliary ? this.auxiliaryMask : this.mask);
  }

  private static bins(startT: number, endT: number): HourBins {
    const firstHourT = Math.floor(startT / SECONDS_PER_HOUR) * SECONDS_PER_HOUR;
    return { firstHourT, count: Math.max(0, Math.ceil((endT - firstHourT) / SECONDS_PER_HOUR)) };
  }

  private static stamped(bins: HourBins, values: readonly (number | null)[]): TimeSeries {
    return TimeSeries.of(
      values.map((_, bin) => bins.firstHourT + bin * SECONDS_PER_HOUR + HALF_HOUR_S),
      values,
    );
  }
}
