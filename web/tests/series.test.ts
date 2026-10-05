import { describe, expect, it } from 'vitest';
import { alignSeries } from '../src/domain/alignSeries';
import { dailyColumnSeries } from '../src/domain/dailyColumnSeries';
import { QcMask } from '../src/domain/QcFlags';
import { RawSeries } from '../src/domain/RawSeries';
import { TimeSeries } from '../src/domain/TimeSeries';
import { TimeZone } from '../src/domain/TimeZone';
import { utc } from './helpers';

const ID = '11111111';

describe('TimeSeries', () => {
  it('validates lengths and ordering', () => {
    expect(() => TimeSeries.of([1, 2], [1])).toThrow('equal lengths');
    expect(() => TimeSeries.of([2, 2], [1, 1])).toThrow('strictly increase');
  });

  it('is immutable and counts valid values', () => {
    const series = TimeSeries.of([1, 2, 3], [1, null, 3]);
    expect(Object.isFrozen(series.t)).toBe(true);
    expect(series.validCount).toBe(2);
    expect(series.length).toBe(3);
  });

  it('inserts a null only where the step exceeds the limit', () => {
    const series = TimeSeries.of([0, 10, 40, 50], [1, 2, 3, 4]).withGapBreaks(20);
    expect(series.t).toEqual([0, 10, 25, 40, 50]);
    expect(series.values).toEqual([1, 2, null, 3, 4]);
  });
});

describe('RawSeries.merge', () => {
  it('sorts samples from files in any order and keeps one sample per time', () => {
    const later = { sensor_id: ID, t: [300, 400], temp_c: [3, 4], rh_pct: [30, 40], qc: [0, 0] };
    const earlier = { sensor_id: ID, t: [100, 300], temp_c: [1, 99], rh_pct: [10, 99], qc: [0, 8] };
    const merged = RawSeries.merge(ID, [later, earlier]);
    expect(merged.t).toEqual([100, 300, 400]);
    expect(merged.temp_c).toEqual([1, 99, 4]);
    expect(merged.qc).toEqual([0, 8, 0]);
  });

  it('cuts a half-open window and extracts a masked variable', () => {
    const file = { sensor_id: ID, t: [100, 200, 300], temp_c: [1, 2, 3], rh_pct: [10, 20, null], qc: [0, 4, 0] };
    const merged = RawSeries.merge(ID, [file]);
    expect(merged.between(100, 300).t).toEqual([100, 200]);
    expect(merged.variable('rh_pct', new QcMask()).values).toEqual([10, null, null]);
  });
});

describe('dailyColumnSeries', () => {
  it('draws each local day at local noon and keeps days starting inside the window', () => {
    const zone = new TimeZone('Europe/Prague');
    const daily = {
      sensor_id: ID,
      date: ['2026-06-01', '2026-06-02', '2026-06-03'],
      temp_min: [1, 2, 3],
      temp_mean: [10, null, 12],
      temp_max: [5, 6, 7],
      rh_min: [1, 1, 1],
      rh_mean: [70, 71, 72],
      rh_max: [9, 9, 9],
      coverage: [1, 1, 1],
    };
    const series = dailyColumnSeries(daily, 'temp_mean', zone, utc(2026, 5, 31, 22), utc(2026, 6, 2, 22));
    // 1 and 2 June 12:00 CEST = 10:00Z
    expect(series.t).toEqual([utc(2026, 6, 1, 10), utc(2026, 6, 2, 10)]);
    expect(series.values).toEqual([10, null]);
  });
});

describe('alignSeries', () => {
  it('builds a union time axis; absent samples are undefined, gaps stay null', () => {
    const a = TimeSeries.of([10, 20, 30], [1, null, 3]);
    const b = TimeSeries.of([15, 30], [5, 6]);
    const aligned = alignSeries([a, b]);
    expect(aligned.t).toEqual([10, 15, 20, 30]);
    expect(aligned.columns).toEqual([
      [1, undefined, null, 3],
      [undefined, 5, undefined, 6],
    ]);
  });
});
