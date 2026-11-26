import type { ChartData } from '../app/ChartDataLoader';
import type { ChartQuantity } from '../app/ChartQuantities';
import { alignSeries } from '../domain/alignSeries';
import { wetIntervals, type TimeInterval } from '../domain/derivedSeries';
import type { TimeWindow } from '../domain/TimeWindow';
import { RESOLUTION_STEP_S, ViewRange } from '../domain/ViewRange';
import { offSiteBands, withoutBands, type ChartEvent, type OffSiteBand } from './EventMarkers';

/** One drawn series: a quantity of one sensor on the model's time axis. */
export interface ChartColumn {
  readonly sensorId: string;
  readonly quantity: ChartQuantity;
  /** Aligned values: `null` = gap, `undefined` = no sample of this series at that time. */
  readonly values: readonly (number | null | undefined)[];
}

/** Leaf-wetness intervals of one sensor, drawn as a band. */
export interface WetLane {
  readonly sensorId: string;
  readonly intervals: readonly TimeInterval[];
}

/** Half of a point's spacing: how far a wet point's band reaches to each side. */
const HALF = 0.5;

/**
 * Everything the chart draws and the CSV export writes, built once per render from the loaded
 * data and the shown quantities: one aligned time axis, one column per sensor and quantity
 * (sensor by sensor, quantities in registry order), the off-site bands and the wetness bands.
 *
 * Inside a sensor's off-site period all its columns are blanked (`withoutBands`), so neither the
 * chart nor the export shows values the sensor did not measure in the vineyard.
 */
export class ChartModel {
  private constructor(
    readonly window: TimeWindow,
    readonly t: readonly number[],
    readonly columns: readonly ChartColumn[],
    readonly events: readonly ChartEvent[],
    readonly offSiteBands: readonly OffSiteBand[],
    readonly wetLanes: readonly WetLane[],
  ) {}

  /**
   * @param data - Loaded chart data (window, sensors, events).
   * @param quantities - Quantities to show, in display order.
   */
  static build(data: ChartData, quantities: readonly ChartQuantity[]): ChartModel {
    const events = data.sensors.flatMap((s) => s.events.map((event) => ({ event, sensorId: s.sensorId })));
    const bands = offSiteBands(events, data.window.startT, data.window.endT);
    const halfWidthS = RESOLUTION_STEP_S[data.window.resolution] * HALF;
    const series = data.sensors.flatMap((sensor) => {
      const own = bands.filter((band) => band.sensorId === sensor.sensorId);
      return quantities.map((quantity) => ({
        sensorId: sensor.sensorId,
        quantity,
        series: withoutBands(quantity.series(sensor), own),
      }));
    });
    const aligned = alignSeries(series.map((s) => s.series));
    const columns = series.map(({ sensorId, quantity }, i) => ({ sensorId, quantity, values: aligned.columns[i] ?? [] }));
    const wetLanes = series
      .filter((s) => s.quantity.display.axis === 'band')
      .map((s) => ({ sensorId: s.sensorId, intervals: wetIntervals(s.series, halfWidthS) }));
    return new ChartModel(data.window, aligned.t, columns, events, bands, wetLanes);
  }

  /** The loaded window as the largest view. */
  get bounds(): ViewRange {
    return new ViewRange(this.window.startT, this.window.endT);
  }

  /** True if any column has a value. */
  get hasValues(): boolean {
    return this.columns.some((column) => column.values.some((value) => typeof value === 'number'));
  }

  /**
   * Indices of the times inside `view` (`startT <= t < endT`) at which at least one column has a
   * value; gap breaks and samples without any shown value are skipped.
   */
  rowsWithin(view: ViewRange): number[] {
    const rows: number[] = [];
    this.t.forEach((t, i) => {
      if (t >= view.startT && t < view.endT && this.columns.some((column) => typeof column.values[i] === 'number')) {
        rows.push(i);
      }
    });
    return rows;
  }
}
