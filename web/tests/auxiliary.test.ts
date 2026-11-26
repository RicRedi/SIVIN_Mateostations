import { describe, expect, it } from 'vitest';
import { ChartDataLoader } from '../src/app/ChartDataLoader';
import { DataClient } from '../src/data/DataClient';
import { AUXILIARY_DISPLAY_EXCLUDE_MASK, DISPLAY_EXCLUDE_MASK, QcFlag, QcMask } from '../src/domain/QcFlags';
import { RawSeries } from '../src/domain/RawSeries';
import { Resampler } from '../src/domain/Resampler';
import { TimeWindow } from '../src/domain/TimeWindow';
import { TimeZone } from '../src/domain/TimeZone';
import { fakeFetcher, utc } from './helpers';

// Synthetic files in the contract shape (§2.6) with precipitation and battery voltage (WP-1.9);
// all numbers are invented for the test.
const ID = '22222222';
const H0 = utc(2026, 7, 1, 0);
const STEP = 1830;
const rawFile = {
  sensor_id: ID,
  t: [H0 + 60, H0 + 60 + STEP, H0 + 3600 + 60, H0 + 3600 + 60 + STEP],
  temp_c: [10, 11, 12, null],
  rh_pct: [80, null, 90, 70],
  precip_mm: [0.2, 0.4, null, 1.0],
  battery_v: [3.6, 3.5, 3.4, 3.3],
  qc: [0, QcFlag.MISSING, QcFlag.PRE_DEPLOYMENT, QcFlag.MISSING],
};
const resampler = new Resampler(new QcMask(DISPLAY_EXCLUDE_MASK));

describe('auxiliary raw columns', () => {
  it('are merged, and read as null when a file has none', () => {
    const merged = RawSeries.merge(ID, [
      rawFile,
      { sensor_id: ID, t: [H0 + 7200 + 60], temp_c: [9], rh_pct: [60], qc: [0] },
    ]);
    expect(merged.precip_mm).toEqual([0.2, 0.4, null, 1.0, null]);
    expect(merged.battery_v).toEqual([3.6, 3.5, 3.4, 3.3, null]);
    expect(merged.between(H0, H0 + 3600).precip_mm).toEqual([0.2, 0.4]);
  });

  it('are masked only by PRE_DEPLOYMENT and MANUAL_EXCLUDE, as in the pipeline (Q9)', () => {
    expect(AUXILIARY_DISPLAY_EXCLUDE_MASK).toBe(288);
    const raw = RawSeries.merge(ID, [rawFile]);
    // MISSING (humidity or temperature absent) keeps the rain; PRE_DEPLOYMENT hides it.
    expect(resampler.raw(raw, 'precip_mm').values).toEqual([0.2, 0.4, null, 1.0]);
    expect(resampler.raw(raw, 'battery_v').values).toEqual([3.6, 3.5, null, 3.3]);
    expect(resampler.raw(raw, 'temp_c').values).toEqual([10, null, null, null]);
  });

  it('sums precipitation per hour and averages battery voltage', () => {
    const raw = RawSeries.merge(ID, [rawFile]);
    // Hour 0: 0.2 + 0.4 = 0.6 mm; hour 1: only 1.0 (the PRE_DEPLOYMENT sample is excluded).
    const sums = resampler.hourlySums(raw, 'precip_mm', H0, H0 + 7200);
    expect(sums.t).toEqual([H0 + 1800, H0 + 5400]);
    expect(sums.values[0]).toBeCloseTo(0.6, 10);
    expect(sums.values[1]).toBe(1.0);
    expect(resampler.hourlyMeans(raw, 'battery_v', H0, H0 + 7200).values).toEqual([3.55, 3.3]);
    // An hour without a valid value is null, not 0.
    expect(resampler.hourlySums(raw, 'precip_mm', H0 + 7200, H0 + 10_800).values).toEqual([null]);
  });
});

describe('ChartDataLoader with auxiliary columns', () => {
  const zone = new TimeZone('Europe/Prague');
  const files = {
    [`series/${ID}/raw/2026-07.json`]: rawFile,
    [`series/${ID}/daily.json`]: {
      sensor_id: ID,
      date: ['2026-07-01', '2026-07-02'],
      temp_min: [8, 9], temp_mean: [12, 13], temp_max: [16, 17],
      rh_min: [50, 55], rh_mean: [80, 85], rh_max: [95, 96],
      coverage: [1, 1],
      precip_sum_mm: [1.6, 0],
      battery_min_v: [3.3, null],
    },
    'manifest.json': {
      schema_version: 1,
      generated_at: '2026-07-03T00:00:00Z',
      display_timezone: 'Europe/Prague',
      variables: [],
      sensors: { [ID]: { first_t: H0, last_t: H0 + 7200, raw_months: ['2026-07'] } },
      seasons: [2026],
      indices: [],
    },
  };
  const loader = new ChartDataLoader(new DataClient('data/', fakeFetcher('data/', files).fetcher), resampler, zone, { warn: () => undefined });

  it('loads precipitation and battery voltage per sample, per hour and per day', async () => {
    const raw = await loader.load([ID], new TimeWindow(H0, H0 + 7200, 'raw'));
    expect(raw.sensors[0]?.precip_mm.values).toEqual([0.2, 0.4, null, 1.0]);
    const hourly = await loader.load([ID], new TimeWindow(H0, H0 + 7200, 'hourly'));
    expect(hourly.sensors[0]?.battery_v.values).toEqual([3.55, 3.3]);
    expect(hourly.sensors[0]?.precip_mm.values[1]).toBe(1.0);
    const daily = await loader.load([ID], new TimeWindow(zone.startOfDate('2026-07-01'), zone.startOfDate('2026-07-03'), 'daily'));
    expect(daily.sensors[0]?.precip_mm.values).toEqual([1.6, 0]);
    expect(daily.sensors[0]?.battery_v.values).toEqual([3.3, null]);
  });
});
