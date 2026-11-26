import { NOMINAL_STEP_S } from './Resampler';
import type { Resolution } from './TimeWindow';
import { SECONDS_PER_DAY, SECONDS_PER_HOUR } from './units';

/** Spacing of the points of each resolution, seconds (raw: the nominal sampling step). */
export const RESOLUTION_STEP_S: Readonly<Record<Resolution, number>> = {
  raw: NOMINAL_STEP_S,
  hourly: SECONDS_PER_HOUR,
  daily: SECONDS_PER_DAY,
};

/** Zooming in stops when the view would show fewer than this many point spacings. */
export const MIN_VISIBLE_STEPS = 4;

/**
 * Wheel zoom sensitivity: the view span is multiplied by `exp(deltaPx × this)`, so one typical
 * wheel notch (100 px) zooms by a factor of about 1.16 and opposite notches cancel exactly.
 */
export const WHEEL_ZOOM_PER_PX = 0.0015;

/** Smallest view span for a resolution, seconds. */
export function minViewSpanS(resolution: Resolution): number {
  return MIN_VISIBLE_STEPS * RESOLUTION_STEP_S[resolution];
}

/**
 * Span factor of a wheel movement: > 1 (zoom out) for a positive `deltaPx` (wheel towards the
 * user), < 1 (zoom in) for a negative one.
 *
 * @param deltaPx - Vertical wheel movement in CSS pixels.
 */
export function wheelZoomFactor(deltaPx: number): number {
  return Math.exp(deltaPx * WHEEL_ZOOM_PER_PX);
}

/**
 * The visible part `[startT, endT)` of the time axis, in Unix seconds UTC; an immutable value.
 * Zooming and panning never leave the given bounds (the loaded window), so no data are fetched.
 */
export class ViewRange {
  /** @throws RangeError if `endT <= startT` or a bound is not finite. */
  constructor(
    readonly startT: number,
    readonly endT: number,
  ) {
    if (!Number.isFinite(startT) || !Number.isFinite(endT) || !(endT > startT)) {
      throw new RangeError(`ViewRange end ${endT} must be after start ${startT}`);
    }
    Object.freeze(this);
  }

  get spanS(): number {
    return this.endT - this.startT;
  }

  equals(other: ViewRange): boolean {
    return this.startT === other.startT && this.endT === other.endT;
  }

  /** True if this range covers all of `bounds`. */
  covers(bounds: ViewRange): boolean {
    return this.startT <= bounds.startT && this.endT >= bounds.endT;
  }

  /**
   * Zoom by `factor` around `anchorT`: the anchor keeps its position on screen. The span is
   * limited to `[minSpanS, bounds.spanS]` and the result is shifted to lie inside `bounds`.
   *
   * @param anchorT - Time under the cursor, Unix seconds.
   * @param factor - Span multiplier: < 1 zooms in, > 1 zooms out.
   * @param bounds - The loaded window.
   * @param minSpanS - Smallest span, seconds.
   */
  zoom(anchorT: number, factor: number, bounds: ViewRange, minSpanS: number): ViewRange {
    const span = Math.min(bounds.spanS, Math.max(Math.min(minSpanS, bounds.spanS), this.spanS * factor));
    const anchor = Math.min(this.endT, Math.max(this.startT, anchorT));
    const fraction = (anchor - this.startT) / this.spanS;
    const startT = anchor - fraction * span;
    return ViewRange.shiftedInto(startT, span, bounds);
  }

  /**
   * Move by `deltaS` seconds (positive = later), keeping the span, stopping at the bounds.
   *
   * @param deltaS - Shift, seconds.
   * @param bounds - The loaded window.
   */
  pan(deltaS: number, bounds: ViewRange): ViewRange {
    return ViewRange.shiftedInto(this.startT + deltaS, Math.min(this.spanS, bounds.spanS), bounds);
  }

  /**
   * This range limited to `bounds`, at least `minSpanS` long (e.g. a selection made with the
   * mouse); if it does not overlap the bounds at all, the bounds themselves.
   */
  clampTo(bounds: ViewRange, minSpanS: number): ViewRange {
    const startT = Math.max(this.startT, bounds.startT);
    const endT = Math.min(this.endT, bounds.endT);
    if (!(endT > startT)) {
      return bounds;
    }
    const span = Math.min(bounds.spanS, Math.max(minSpanS, endT - startT));
    return ViewRange.shiftedInto((startT + endT - span) / 2, span, bounds);
  }

  private static shiftedInto(startT: number, spanS: number, bounds: ViewRange): ViewRange {
    const start = Math.min(bounds.endT - spanS, Math.max(bounds.startT, startT));
    return new ViewRange(start, start + spanS);
  }
}
