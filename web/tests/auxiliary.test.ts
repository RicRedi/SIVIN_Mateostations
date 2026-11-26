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

  it('averages battery voltage per hour', () => {
    const raw = RawSeries.merge(ID, [rawFile]);
    expect(resampler.hourlyMeans(raw, 'battery_v', H0, H0 + 7200).values).toEqual([3.55, 3.3]);
  });
});

describe('Resampler.hourlyPrecipitation', () => {
  // Synthetic grid of 1830 s from 00:15 with 0.1 … 0.7 mm (invented values).
  const times = [900, 2730, 4560, 6390, 8220, 10_050, 11_880].map((s) => H0 + s);
  const precip = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7];
  const ALL = [0, 1, 2, 3, 4, 5, 6];
  function file(keep: readonly number[], qc: Readonly<Record<number, number>> = {}, at = times, mm = precip) {
    return RawSeries.merge(ID, [{
      sensor_id: ID,
      t: keep.map((i) => at[i] ?? 0),
      temp_c: keep.map(() => 10),
      rh_pct: keep.map(() => 80),
      precip_mm: keep.map((i) => mm[i] ?? null),
      qc: keep.map((i) => qc[i] ?? 0),
    }]);
  }

  it('counts each amount in the hour of the midpoint of its interval (t_prev, t]', () => {
    // Midpoints: 00:15 − 915 s = 23:59:45 (before the window), 00:30:15 → hour 0,
    // 01:00:45 and 01:31:15 → hour 1, 02:01:45 and 02:32:15 → hour 2, 03:02:45 (after the
    // window). Binning by the sample's own time would have put 0.1 mm into hour 0 as well.
    const hourly = resampler.hourlyPrecipitation(file(ALL), H0, H0 + 3 * 3600);
    expect(hourly.t).toEqual([H0 + 1800, H0 + 5400, H0 + 9000]);
    expect(hourly.values[0]).toBe(0.2);
    expect(hourly.values[1]).toBeCloseTo(0.3 + 0.4, 10);
    expect(hourly.values[2]).toBeCloseTo(0.5 + 0.6, 10);
  });

  it('shows an hour with a missed or masked sample as null, not as a partial sum', () => {
    // Without sample 3 the sample at 02:17 covers 3660 s > 2745 s: hour 1 (its midpoint
    // 01:46:30) is incomplete although it holds the valid 0.3 mm.
    expect(resampler.hourlyPrecipitation(file([0, 1, 2, 4, 5, 6]), H0, H0 + 3 * 3600).values).toEqual([0.2, null, 0.6]);
    // A MANUAL_EXCLUDE sample makes its hour incomplete; MISSING (temperature/humidity) does not.
    const masked = file(ALL, { 1: QcFlag.MANUAL_EXCLUDE, 4: QcFlag.MISSING });
    const [h0, h1, h2] = resampler.hourlyPrecipitation(masked, H0, H0 + 3 * 3600).values;
    expect(h0).toBeNull();
    expect(h1).toBeCloseTo(0.7, 10);
    expect(h2).toBeCloseTo(1.1, 10);
  });

  it('leaves an hour at the edge of a gap empty when its end is not covered (review round 2)', () => {
    // Samples 10:05Z (0.5 mm), 10:35Z (1.0 mm), then nothing until 14:00Z (0.3 mm).
    // Hour 10 counts only (10:05, 10:35]: 10:35–11:00 is uncovered (25 min > 1372.5 s), so the
    // 1.0 mm must not be shown as the hour's sum. The 14:00 sample covers 3 h 25 min → hour 12
    // (its midpoint 12:17:30) is incomplete; hours 11, 13 and 14 have no sample.
    const H10 = utc(2026, 7, 1, 10);
    const gap = file([0, 1, 2], {}, [H10 + 300, H10 + 2100, H10 + 4 * 3600], [0.5, 1.0, 0.3]);
    expect(resampler.hourlyPrecipitation(gap, H10, H10 + 5 * 3600).values).toEqual([null, null, null, null, null]);
  });

  it('leaves the running last hour of the data empty', () => {
    // With a fourth hour in the window, hour 3 only holds (02:47:30, 03:18]: its end is not covered.
    expect(resampler.hourlyPrecipitation(file(ALL), H0, H0 + 4 * 3600).values[3]).toBeNull();
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
    // Hour 0 holds the masked (PRE_DEPLOYMENT) third sample → incomplete; hour 1 ends at the
    // last sample 01:31:30, so 01:31–02:00 is uncovered → null too.
    expect(hourly.sensors[0]?.precip_mm.values).toEqual([null, null]);
    const daily = await loader.load([ID], new TimeWindow(zone.startOfDate('2026-07-01'), zone.startOfDate('2026-07-03'), 'daily'));
    expect(daily.sensors[0]?.precip_mm.values).toEqual([1.6, 0]);
    expect(daily.sensors[0]?.battery_v.values).toEqual([3.3, null]);
  });
});
