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

const HALF_HOUR_S = SECONDS_PER_HOUR / 2;

/** How the values of one hour are combined. */
type HourlyAggregate = 'mean' | 'sum';

/**
 * Turns raw samples into chart series: QC-masked raw values, hourly means or hourly sums. Daily
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
    return this.hourly(series, variable, startT, endT, 'mean');
  }

  /**
   * Hourly sums over UTC hours, stamped like {@link hourlyMeans}; for precipitation per hour (mm).
   * An hour without a valid value is `null`, not 0, so missing data stay visible.
   */
  hourlySums(series: RawSeries, variable: RawColumn, startT: number, endT: number): TimeSeries {
    return this.hourly(series, variable, startT, endT, 'sum');
  }

  private masked(series: RawSeries, variable: RawColumn): TimeSeries {
    const isAuxiliary = variable === 'precip_mm' || variable === 'battery_v';
    return series.variable(variable, isAuxiliary ? this.auxiliaryMask : this.mask);
  }

  private hourly(
    series: RawSeries,
    variable: RawColumn,
    startT: number,
    endT: number,
    aggregate: HourlyAggregate,
  ): TimeSeries {
    const values = this.masked(series, variable);
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
    const t = sums.map((_, bin) => firstHourT + bin * SECONDS_PER_HOUR + HALF_HOUR_S);
    const aggregated = sums.map((sum, bin) => {
      const count = counts[bin] ?? 0;
      if (count === 0) {
        return null;
      }
      return aggregate === 'sum' ? sum : sum / count;
    });
    return TimeSeries.of(t, aggregated);
  }
}
