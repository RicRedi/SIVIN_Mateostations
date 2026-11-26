import uPlot from 'uplot';
import type { WetLane } from './ChartModel';

/** Height of one sensor's wetness band, CSS px. */
export const WET_LANE_HEIGHT_PX = 10;
/** Opacity of a wetness band (in the sensor's colour), so lines drawn over it stay visible. */
export const WET_LANE_ALPHA = 0.45;
const BYTE_MAX = 255;
const HEX_RADIX = 16;
const HEX_BYTE_DIGITS = 2;
/** Length of `#rrggbb`. */
const RGB_HEX_LENGTH = '#rrggbb'.length;

/** `#rrggbb` with an alpha channel (`#rrggbbaa`); other colour strings are returned unchanged. */
export function withAlpha(color: string, alpha: number): string {
  if (!color.startsWith('#') || color.length !== RGB_HEX_LENGTH) {
    return color;
  }
  return `${color}${Math.round(alpha * BYTE_MAX).toString(HEX_RADIX).padStart(HEX_BYTE_DIGITS, '0')}`;
}

/**
 * Draws the leaf-wetness estimate as bands: one lane per sensor along the bottom of the plotting
 * area (stacked upwards in selection order), filled in the sensor's colour where `RH >= 90 %`.
 * Drawn in uPlot's `drawClear` hook, under grid and lines, clipped to the plotting area.
 */
export class WetnessBands {
  private lanes: readonly WetLane[] = [];

  /** @param colorFor - Line colour of a sensor. */
  constructor(private readonly colorFor: (sensorId: string) => string) {}

  setLanes(lanes: readonly WetLane[]): void {
    this.lanes = lanes;
  }

  draw(plot: uPlot): void {
    if (this.lanes.length === 0) {
      return;
    }
    const { ctx } = plot;
    const { left, top, width, height } = plot.bbox;
    const laneHeight = WET_LANE_HEIGHT_PX * uPlot.pxRatio;
    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, width, height);
    ctx.clip();
    this.lanes.forEach((lane, index) => {
      ctx.fillStyle = withAlpha(this.colorFor(lane.sensorId), WET_LANE_ALPHA);
      const y = top + height - (index + 1) * laneHeight;
      for (const interval of lane.intervals) {
        const x0 = plot.valToPos(interval.startT, 'x', true);
        const x1 = plot.valToPos(interval.endT, 'x', true);
        ctx.fillRect(x0, y, x1 - x0, laneHeight);
      }
    });
    ctx.restore();
  }
}
