import { describe, expect, it } from 'vitest';
import { combineSeries, DRY, leafWetnessIndicator, WET, wetIntervals } from '../src/domain/derivedSeries';
import { TimeSeries } from '../src/domain/TimeSeries';

// Synthetic series with round numbers, not measurements.
describe('combineSeries', () => {
  it('applies the formula where both values exist and keeps gaps and masked samples null', () => {
    const temp = TimeSeries.of([100, 200, 300, 400], [10, null, 30, 40]);
    const rh = TimeSeries.of([100, 200, 300, 400], [50, 60, null, 80]);
    const sum = combineSeries(temp, rh, (t, r) => t + r);
    expect(sum.t).toEqual([100, 200, 300, 400]);
    expect(sum.values).toEqual([60, null, null, 120]);
  });

  it('matches by time, not by index, and passes a null of the formula through', () => {
    const temp = TimeSeries.of([100, 200, 300], [1, 2, 3]);
    const rh = TimeSeries.of([200, 300], [20, 0]);
    expect(combineSeries(temp, rh, (t, r) => (r > 0 ? t * r : null)).values).toEqual([null, 40, null]);
  });
});

describe('leafWetnessIndicator', () => {
  it('is 1 at RH >= 90 %, 0 below and null without humidity', () => {
    const rh = TimeSeries.of([1, 2, 3, 4], [95, 90, 89.9, null]);
    expect(leafWetnessIndicator(rh).values).toEqual([WET, WET, DRY, null]);
    expect(leafWetnessIndicator(rh, 95).values).toEqual([WET, DRY, DRY, null]);
  });
});

describe('wetIntervals', () => {
  it('extends each wet point half way to its neighbours and merges adjacent ones', () => {
    // Points every 100 s; wet at 200 and 300 → [150, 350); wet at 600 → [550, 650).
    const indicator = TimeSeries.of([100, 200, 300, 400, 500, 600, 700], [DRY, WET, WET, DRY, DRY, WET, DRY]);
    expect(wetIntervals(indicator, 1000)).toEqual([
      { startT: 150, endT: 350 },
      { startT: 550, endT: 650 },
    ]);
  });

  it('limits the extent at gaps and at the ends to the half step', () => {
    // A null gap break at 500 between 400 and 2000: the wet point 2000 covers [1950, 2050).
    const indicator = TimeSeries.of([400, 500, 2000], [WET, null, WET]);
    expect(wetIntervals(indicator, 50)).toEqual([
      { startT: 350, endT: 450 },
      { startT: 1950, endT: 2050 },
    ]);
  });

  it('is empty without wet points', () => {
    expect(wetIntervals(TimeSeries.of([1, 2], [DRY, null]), 10)).toEqual([]);
  });
});
