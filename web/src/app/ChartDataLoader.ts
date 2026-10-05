import type { SensorEvent } from '../contract';
import type { DataClient } from '../data/DataClient';
import { dailyColumnSeries } from '../domain/dailyColumnSeries';
import type { Resampler } from '../domain/Resampler';
import type { RawVariable } from '../domain/RawSeries';
import type { TimeSeries } from '../domain/TimeSeries';
import type { TimeWindow } from '../domain/TimeWindow';
import type { TimeZone } from '../domain/TimeZone';
import { SECONDS_PER_DAY } from '../domain/units';

/** Daily points farther apart than 1.5 days (a missing day) are drawn with a gap. */
export const DAILY_GAP_THRESHOLD_S = 1.5 * SECONDS_PER_DAY;

/** Chart input for one sensor. */
export interface SensorChartData {
  readonly sensorId: string;
  readonly temp_c: TimeSeries;
  readonly rh_pct: TimeSeries;
  /** Events with `t` inside the window. */
  readonly events: readonly SensorEvent[];
}

/** Chart input for all selected sensors. */
export interface ChartData {
  readonly window: TimeWindow;
  readonly sensors: readonly SensorChartData[];
}

const DAILY_COLUMN: Readonly<Record<RawVariable, 'temp_mean' | 'rh_mean'>> = {
  temp_c: 'temp_mean',
  rh_pct: 'rh_mean',
};

/**
 * Loads what the chart needs for a window: raw samples, hourly means or daily means per the
 * window's resolution, plus the sensors' events.
 */
export class ChartDataLoader {
  constructor(
    private readonly client: DataClient,
    private readonly resampler: Resampler,
    private readonly zone: TimeZone,
  ) {}

  async load(sensorIds: readonly string[], window: TimeWindow): Promise<ChartData> {
    const sensors = await Promise.all(sensorIds.map((id) => this.loadSensor(id, window)));
    return { window, sensors };
  }

  private async loadSensor(sensorId: string, window: TimeWindow): Promise<SensorChartData> {
    const [series, eventsFile] = await Promise.all([
      this.loadSeries(sensorId, window),
      this.client.getEvents(sensorId),
    ]);
    const events = eventsFile.events.filter((event) => window.contains(event.t));
    return { sensorId, ...series, events };
  }

  private async loadSeries(
    sensorId: string,
    window: TimeWindow,
  ): Promise<Record<RawVariable, TimeSeries>> {
    const { startT, endT } = window;
    switch (window.resolution) {
      case 'daily': {
        const daily = await this.client.getDaily(sensorId);
        const column = (variable: RawVariable): TimeSeries =>
          dailyColumnSeries(daily, DAILY_COLUMN[variable], this.zone, startT, endT).withGapBreaks(
            DAILY_GAP_THRESHOLD_S,
          );
        return { temp_c: column('temp_c'), rh_pct: column('rh_pct') };
      }
      case 'hourly': {
        const raw = await this.client.getRawRange(sensorId, startT, endT);
        return {
          temp_c: this.resampler.hourlyMeans(raw, 'temp_c', startT, endT),
          rh_pct: this.resampler.hourlyMeans(raw, 'rh_pct', startT, endT),
        };
      }
      case 'raw': {
        const raw = await this.client.getRawRange(sensorId, startT, endT);
        return { temp_c: this.resampler.raw(raw, 'temp_c'), rh_pct: this.resampler.raw(raw, 'rh_pct') };
      }
    }
  }
}
