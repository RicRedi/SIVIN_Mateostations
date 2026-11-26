import uPlot, { type Axis, type Scale, type Series } from 'uplot';
import type { QuantityAxis, QuantityRegistry, QuantityStyle } from '../app/ChartQuantities';
import type { SensorCatalog } from '../app/SensorCatalog';
import { WET } from '../domain/derivedSeries';
import type { Resolution } from '../domain/TimeWindow';
import type { I18n } from '../i18n/I18n';
import type { ChartColumn, ChartModel } from './ChartModel';
import type { QuantityLabels } from './QuantityLabels';
import { withAlpha } from './WetnessBands';

/** Relative humidity axis range, %. */
const RH_RANGE_PCT: [number, number] = [0, 100];
/** Range of the hidden scale of the 0/1 leaf-wetness indicator. */
const WET_RANGE: [number, number] = [0, 1];
/** Headroom above the largest precipitation bar (share of the maximum). */
const BAR_HEADROOM = 0.1;
/** Precipitation axis maximum when the visible range has no precipitation, mm. */
const EMPTY_BAR_MAX = 1;
/** Bar width: share of the point spacing, and the largest width in px. */
const BAR_WIDTH_SHARE = 0.6;
const BAR_MAX_WIDTH_PX = 12;
const BAR_FILL_ALPHA = 0.55;
const BAR_OUTLINE_PX = 1;
/** Most decimals of an axis tick label. */
const MAX_TICK_DECIMALS = 3;
/** Tolerance for floating-point tick spacings such as 0.1 + 0.2. */
const TICK_EPSILON = 1e-9;
const DECIMAL_BASE = 10;
/** Width of a value axis (ticks and unit label), px: uPlot's default and the narrow variant. */
const AXIS_SIZE_PX = 50;
const AXIS_SIZE_NARROW_PX = 38;
/** Space for an axis' unit label, px (uPlot's default 30). */
const AXIS_LABEL_SIZE_PX = 30;
const AXIS_LABEL_SIZE_NARROW_PX = 18;
const NO_VALUE = '–';

/** Line width and dash pattern (px) of each line style; the colour is the sensor's. */
export const LINE_STYLES: Readonly<Record<Exclude<QuantityStyle, 'bars' | 'band'>, { width: number; dash: number[] }>> = {
  solid: { width: 2, dash: [] },
  dashed: { width: 1.5, dash: [6, 4] },
  dotted: { width: 1.5, dash: [2, 3] },
  dashDot: { width: 1.5, dash: [8, 3, 2, 3] },
};

/** uPlot scale of each axis kind. */
export const SCALE: Readonly<Record<QuantityAxis, string>> = { temp: 'temp', rh: 'rh', extra: 'extra', band: 'wet' };

/** `uPlot.Axis.Side.Right`; the ambient const enum cannot be referenced under `isolatedModules`. */
// eslint-disable-next-line @typescript-eslint/no-unsafe-enum-assignment -- numeric value of Side.Right
const AXIS_SIDE_RIGHT = 1 as uPlot.Axis.Side;

/**
 * Decimals that tell ticks apart: as many as the tick spacing needs (0.05 → 2, 2.5 → 1, 5 → 0),
 * at most {@link MAX_TICK_DECIMALS}.
 */
export function tickDecimals(ticks: readonly number[]): number {
  const [first, second] = ticks;
  if (first === undefined || second === undefined || second === first) {
    return 0;
  }
  const step = Math.abs(second - first);
  for (let decimals = 0; decimals < MAX_TICK_DECIMALS; decimals++) {
    const scaled = step * DECIMAL_BASE ** decimals;
    if (Math.abs(scaled - Math.round(scaled)) < TICK_EPSILON) {
      return decimals;
    }
  }
  return MAX_TICK_DECIMALS;
}

/** y range of precipitation bars: from 0 to the largest visible value plus headroom. */
export const barRange: Scale.Range = (_u, _min, max) => [0, max > 0 ? max * (1 + BAR_HEADROOM) : EMPTY_BAR_MAX];

/**
 * uPlot scales, value axes and series of a {@link ChartModel}: the colour identifies the sensor,
 * the line style the quantity; temperature-like quantities share the °C axis (left), humidity the
 * % axis (right), the single extra-axis quantity a third axis (right), leaf wetness a hidden 0–1
 * scale (drawn as bands by `WetnessBands`, shown as "wet/dry" in the legend).
 */
export class ChartSeriesFactory {
  /** @param colorFor - Line colour of a sensor. */
  constructor(
    private readonly i18n: I18n,
    private readonly catalog: SensorCatalog,
    private readonly registry: QuantityRegistry,
    private readonly labels: QuantityLabels,
    private readonly colorFor: (sensorId: string) => string,
  ) {}

  /** y scales (the x scale is the caller's). */
  scales(model: ChartModel): Record<string, Scale> {
    const scales: Record<string, Scale> = { rh: { range: RH_RANGE_PCT }, wet: { range: WET_RANGE } };
    if (this.extraOf(model)?.display.style === 'bars') {
      scales.extra = { range: barRange };
    }
    return scales;
  }

  /**
   * Value axes of the scales in use: °C left, % right, the third axis right of it.
   *
   * @param narrow - True on narrow containers (phones): smaller axes leave the plot more room.
   */
  axes(model: ChartModel, narrow: boolean): Axis[] {
    const used = new Set(model.columns.map((column) => column.quantity.display.axis));
    const extraUnit = this.extraOf(model)?.display.unit;
    const numbers = (ticks: number[]) => {
      const decimals = tickDecimals(ticks);
      return ticks.map((v) => this.i18n.formatNumber(v, decimals));
    };
    const size = { size: narrow ? AXIS_SIZE_NARROW_PX : AXIS_SIZE_PX, labelSize: narrow ? AXIS_LABEL_SIZE_NARROW_PX : AXIS_LABEL_SIZE_PX };
    return [
      { ...size, scale: SCALE.temp, label: this.registry.get('temp_c').display.unit, show: used.has('temp'), values: (_, ticks) => numbers(ticks) },
      { ...size, scale: SCALE.rh, side: AXIS_SIDE_RIGHT, label: this.registry.get('rh_pct').display.unit, show: used.has('rh'), grid: { show: !used.has('temp') } },
      {
        ...size,
        scale: SCALE.extra,
        side: AXIS_SIDE_RIGHT,
        label: extraUnit ?? '',
        show: extraUnit !== undefined,
        grid: { show: false },
        values: (_, ticks) => numbers(ticks),
      },
    ];
  }

  /** The uPlot series of one column. */
  series(column: ChartColumn, resolution: Resolution): Series {
    const { quantity } = column;
    const { display } = quantity;
    const sensor = this.catalog.get(column.sensorId)?.label ?? column.sensorId;
    const color = this.colorFor(column.sensorId);
    const base: Series = {
      label: `${sensor} · ${this.labels.label(quantity, resolution)}`,
      scale: SCALE[display.axis],
      stroke: color,
      spanGaps: false,
      value: (_, v: number | null) => (v === null ? NO_VALUE : `${this.i18n.formatNumber(v, display.decimals)} ${display.unit}`),
    };
    switch (display.style) {
      case 'band':
        return {
          ...base,
          paths: () => null,
          points: { show: false },
          value: (_, v: number | null) => (v === null ? NO_VALUE : this.i18n.t(v === WET ? 'leafWet' : 'leafDry')),
        };
      case 'bars':
        return {
          ...base,
          width: BAR_OUTLINE_PX,
          fill: withAlpha(color, BAR_FILL_ALPHA),
          paths: uPlot.paths.bars?.({ size: [BAR_WIDTH_SHARE, BAR_MAX_WIDTH_PX] }),
          points: { show: false },
        };
      default:
        return { ...base, width: LINE_STYLES[display.style].width, dash: LINE_STYLES[display.style].dash };
    }
  }

  private extraOf(model: ChartModel) {
    return model.columns.find((column) => column.quantity.display.axis === 'extra')?.quantity;
  }
}
