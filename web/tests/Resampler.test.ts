import { describe, expect, it } from 'vitest';
import { DEFAULT_EXCLUDE_MASK, QcFlag, QcMask } from '../src/domain/QcFlags';
import { RawSeries } from '../src/domain/RawSeries';
import { RAW_GAP_THRESHOLD_S, Resampler } from '../src/domain/Resampler';
import { utc } from './helpers';

const ID = '11111111';
const H0 = utc(2026, 7, 1, 0);
const H4 = utc(2026, 7, 1, 4);

function series(rows: readonly [number, number | null, number][]): RawSeries {
  return RawSeries.merge(ID, [
    {
      sensor_id: ID,
      t: rows.map((row) => row[0]),
      temp_c: rows.map((row) => row[1]),
      rh_pct: rows.map(() => 50),
      qc: rows.map((row) => row[2]),
    },
  ]);
}

describe('QcMask', () => {
  it('mirrors DEFAULT_EXCLUDE = MISSING|OUT_OF_RANGE|SPIKE|STUCK|PRE_DEPLOYMENT|MANUAL_EXCLUDE', () => {
    expect(DEFAULT_EXCLUDE_MASK).toBe(1 | 2 | 4 | 16 | 32 | 256);
    const mask = new QcMask();
    expect(mask.excludes(QcFlag.SPIKE)).toBe(true);
    expect(mask.excludes(QcFlag.STEP | QcFlag.NEIGHBOR_OUTLIER | QcFlag.TIMESTAMP_SUSPECT)).toBe(false);
    expect(mask.excludes(QcFlag.STEP | QcFlag.MANUAL_EXCLUDE)).toBe(true);
    expect(mask.excludes(0)).toBe(false);
  });
});

describe('Resampler.hourlyMeans', () => {
  const resampler = new Resampler(new QcMask());
  const raw = series([
    [H0, 10, 0],
    [H0 + 1800, 12, QcFlag.SPIKE],
    [H0 + 2700, null, QcFlag.MISSING],
    [H0 + 3600 + 600, 14, 0],
    [H0 + 3600 + 2400, 16, 0],
    [H0 + 3 * 3600 + 1200, 20, QcFlag.STEP],
    [H4 + 600, 30, 0],
  ]);

  it('averages valid values per UTC hour, skipping nulls and excluded flags', () => {
    const hourly = resampler.hourlyMeans(raw, 'temp_c', H0, H4);
    expect(hourly.t).toEqual([H0, H0 + 3600, H0 + 7200, H0 + 10_800]);
    // hour 0: 10 (12 is a SPIKE, the third value is null); hour 1: (14 + 16) / 2;
    // hour 2: no samples; hour 3: 20 (STEP is informative only); 04:10 is outside the window.
    expect(hourly.values).toEqual([10, 15, null, 20]);
  });

  it('aligns bins to full hours when the window starts mid-hour', () => {
    const hourly = resampler.hourlyMeans(raw, 'temp_c', H0 + 1800, H0 + 7200);
    // 00:00 lies before the window start, so hour 0 is empty.
    expect(hourly.t).toEqual([H0, H0 + 3600]);
    expect(hourly.values).toEqual([null, 15]);
  });

  it('honours a custom mask', () => {
    const keepSpikes = new Resampler(new QcMask(QcFlag.MISSING));
    expect(keepSpikes.hourlyMeans(raw, 'temp_c', H0, H0 + 3600).values).toEqual([11]);
  });
});

describe('Resampler.raw', () => {
  it('nulls excluded values and breaks gaps longer than the threshold', () => {
    const resampler = new Resampler(new QcMask());
    const raw = series([
      [H0, 10, 0],
      [H0 + 1825, 11, QcFlag.PRE_DEPLOYMENT],
      [H0 + 1825 + RAW_GAP_THRESHOLD_S + 1, 12, 0],
    ]);
    const result = resampler.raw(raw, 'temp_c');
    const gapT = Math.round((2 * H0 + 2 * 1825 + RAW_GAP_THRESHOLD_S + 1) / 2);
    expect(result.t).toEqual([H0, H0 + 1825, gapT, H0 + 1825 + RAW_GAP_THRESHOLD_S + 1]);
    expect(result.values).toEqual([10, null, null, 12]);
  });
});
