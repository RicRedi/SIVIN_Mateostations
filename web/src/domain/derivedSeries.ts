import { isLeafWet, LEAF_WET_RH_THRESHOLD_PCT } from './psychrometry';
import { TimeSeries } from './TimeSeries';

/** A half-open time interval `[startT, endT)` in Unix seconds UTC. */
export interface TimeInterval {
  readonly startT: number;
  readonly endT: number;
}

/** Value of the leaf wetness indicator for a wet sample (a dry sample is 0). */
export const WET = 1;
export const DRY = 0;

/**
 * A quantity derived pointwise from temperature and humidity at the same times, e.g. the dew
 * point. The result has the times of `temp`; a value is `null` where the temperature or the
 * humidity at that time is `null` or missing, or where `formula` returns `null`. QC-masked
 * samples are `null` in the inputs and so stay masked; gap breaks (`null`) are kept.
 *
 * @param temp - Temperature series, °C.
 * @param rh - Relative humidity series, %.
 * @param formula - `(tempC, rhPct) => value`, `null` when undefined.
 */
export function combineSeries(
  temp: TimeSeries,
  rh: TimeSeries,
  formula: (tempC: number, rhPct: number) => number | null,
): TimeSeries {
  const rhByTime = new Map<number, number | null>();
  rh.t.forEach((t, i) => rhByTime.set(t, rh.values[i] ?? null));
  const values = temp.t.map((t, i) => {
    const tempC = temp.values[i] ?? null;
    const rhPct = rhByTime.get(t) ?? null;
    return tempC === null || rhPct === null ? null : formula(tempC, rhPct);
  });
  return TimeSeries.of(temp.t, values);
}

/**
 * Leaf wetness proxy as an indicator series on the times of `rh`: {@link WET} where
 * `RH >= thresholdPct`, {@link DRY} below, `null` where the humidity is `null`.
 *
 * @param rh - Relative humidity series, %.
 * @param thresholdPct - Wetness threshold, %.
 */
export function leafWetnessIndicator(rh: TimeSeries, thresholdPct: number = LEAF_WET_RH_THRESHOLD_PCT): TimeSeries {
  return TimeSeries.of(
    rh.t,
    rh.values.map((value) => (value === null ? null : isLeafWet(value, thresholdPct) ? WET : DRY)),
  );
}

/**
 * Time intervals in which an indicator series is {@link WET}, for drawing bands. Each wet point
 * covers half the way to its neighbours, but at most `maxHalfWidthS` to each side (so a point
 * next to a gap covers only its own sampling step); touching or overlapping intervals are merged.
 *
 * @param indicator - Series of {@link WET} / {@link DRY} / `null`.
 * @param maxHalfWidthS - Largest extent of one point to each side, seconds (half the sampling step).
 * @returns Disjoint intervals in ascending order.
 */
export function wetIntervals(indicator: TimeSeries, maxHalfWidthS: number): TimeInterval[] {
  const intervals: TimeInterval[] = [];
  const { t, values } = indicator;
  t.forEach((time, i) => {
    if (values[i] !== WET) {
      return;
    }
    const previous = t[i - 1];
    const next = t[i + 1];
    const startT = previous === undefined ? time - maxHalfWidthS : Math.max(time - maxHalfWidthS, (previous + time) / 2);
    const endT = next === undefined ? time + maxHalfWidthS : Math.min(time + maxHalfWidthS, (time + next) / 2);
    const last = intervals.at(-1);
    if (last !== undefined && startT <= last.endT) {
      intervals[intervals.length - 1] = { startT: last.startT, endT: Math.max(last.endT, endT) };
    } else {
      intervals.push({ startT, endT });
    }
  });
  return intervals;
}
