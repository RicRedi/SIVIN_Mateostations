import { eventInWindow, type SensorEvent } from '../contract';
import type { DataClient } from '../data/DataClient';
import { dailyColumnSeries } from '../domain/dailyColumnSeries';
import type { RawColumn } from '../domain/RawSeries';
import type { Resampler } from '../domain/Resampler';
import type { TimeSeries } from '../domain/TimeSeries';
import type { TimeWindow } from '../domain/TimeWindow';
import type { TimeZone } from '../domain/TimeZone';
import { SECONDS_PER_DAY } from '../domain/units';

/** Daily points farther apart than 1.5 days (a missing day) are drawn with a gap. */
export const DAILY_GAP_THRESHOLD_S = 1.5 * SECONDS_PER_DAY;

/**
 * Chart input for one sensor, at the window's resolution. Precipitation is per sample (raw),
 * summed per hour (hourly) or the daily sum (daily); battery voltage is per sample, the hourly
 * mean or the daily minimum. An hourly precipitation sum is `null` unless the hour is complete
 * (`Resampler.hourlyPrecipitation`). Both are empty-valued (`null`) where the data have no such column.
 */
export interface SensorChartData {
  readonly sensorId: string;
  readonly temp_c: TimeSeries;
  readonly rh_pct: TimeSeries;
  readonly precip_mm: TimeSeries;
  readonly battery_v: TimeSeries;
  /** Events inside the window; `off_site` periods that overlap it. */
  readonly events: readonly SensorEvent[];
}

/** A sensor whose series could not be loaded. */
export interface SensorLoadFailure {
  readonly sensorId: string;
  readonly message: string;
}

/** Chart input for all selected sensors; a failing sensor does not hide the others. */
export interface ChartData {
  readonly window: TimeWindow;
  readonly sensors: readonly SensorChartData[];
  readonly failures: readonly SensorLoadFailure[];
}

/** Where non-fatal problems (e.g. an unreadable events file) are reported. */
export interface WarningSink {
  warn(message: string): void;
}

/** Column of `daily.json` shown for each raw column at daily resolution. */
const DAILY_COLUMN: Readonly<Record<RawColumn, 'temp_mean' | 'rh_mean' | 'precip_sum_mm' | 'battery_min_v'>> = {
  temp_c: 'temp_mean',
  rh_pct: 'rh_mean',
  precip_mm: 'precip_sum_mm',
  battery_v: 'battery_min_v',
};

type SeriesColumns = Record<RawColumn, TimeSeries>;

/**
 * Loads what the chart needs for a window, sensor by sensor: raw samples, hourly means or daily
 * means per the window's resolution, plus the sensor's events.
 *
 * A sensor whose series fail to load becomes a {@link SensorLoadFailure}; the other sensors are
 * still returned. Events are decoration: a missing or invalid events file is reported to the
 * warning sink and treated as "no events".
 */
export class ChartDataLoader {
  constructor(
    private readonly client: DataClient,
    private readonly resampler: Resampler,
    private readonly zone: TimeZone,
    private readonly warnings: WarningSink,
  ) {}

  async load(sensorIds: readonly string[], window: TimeWindow): Promise<ChartData> {
    const results = await Promise.allSettled(sensorIds.map((id) => this.loadSensor(id, window)));
    const sensors: SensorChartData[] = [];
    const failures: SensorLoadFailure[] = [];
    results.forEach((result, i) => {
      const sensorId = sensorIds[i] ?? '';
      if (result.status === 'fulfilled') {
        sensors.push(result.value);
      } else {
        const reason: unknown = result.reason;
        failures.push({ sensorId, message: reason instanceof Error ? reason.message : String(reason) });
      }
    });
    return { window, sensors, failures };
  }

  private async loadSensor(sensorId: string, window: TimeWindow): Promise<SensorChartData> {
    const [series, events] = await Promise.all([
      this.loadSeries(sensorId, window),
      this.loadEvents(sensorId, window),
    ]);
    return { sensorId, ...series, events };
  }

  private async loadEvents(sensorId: string, window: TimeWindow): Promise<readonly SensorEvent[]> {
    try {
      const file = await this.client.getEvents(sensorId);
      return file.events.filter((event) => eventInWindow(event, window.startT, window.endT));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.warnings.warn(`Events of sensor ${sensorId} ignored: ${message}`);
      return [];
    }
  }

  private async loadSeries(
    sensorId: string,
    window: TimeWindow,
  ): Promise<SeriesColumns> {
    const { startT, endT } = window;
    switch (window.resolution) {
      case 'daily': {
        const daily = await this.client.getDaily(sensorId);
        const column = (variable: RawColumn): TimeSeries =>
          dailyColumnSeries(daily, DAILY_COLUMN[variable], this.zone, startT, endT).withGapBreaks(
            DAILY_GAP_THRESHOLD_S,
          );
        return {
          temp_c: column('temp_c'),
          rh_pct: column('rh_pct'),
          precip_mm: column('precip_mm'),
          battery_v: column('battery_v'),
        };
      }
      case 'hourly': {
        const raw = await this.client.getRawRange(sensorId, startT, endT);
        return {
          temp_c: this.resampler.hourlyMeans(raw, 'temp_c', startT, endT),
          rh_pct: this.resampler.hourlyMeans(raw, 'rh_pct', startT, endT),
          precip_mm: this.resampler.hourlyPrecipitation(raw, startT, endT),
          battery_v: this.resampler.hourlyMeans(raw, 'battery_v', startT, endT),
        };
      }
      case 'raw': {
        const raw = await this.client.getRawRange(sensorId, startT, endT);
        return {
          temp_c: this.resampler.raw(raw, 'temp_c'),
          rh_pct: this.resampler.raw(raw, 'rh_pct'),
          precip_mm: this.resampler.raw(raw, 'precip_mm'),
          battery_v: this.resampler.raw(raw, 'battery_v'),
        };
      }
    }
  }
}
