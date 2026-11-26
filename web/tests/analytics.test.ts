import { describe, expect, it, vi } from 'vitest';
import { parseIndicesFile, parseManifest, type DailyFile, type IndexDaily } from '../src/contract';
import { addDays, dateRange, daysBetween, noonUtcSeconds, yearOf } from '../src/domain/isoDates';
import { levelTones, RiskStrip, toneForRank } from '../src/domain/RiskStrip';
import { FROST_THRESHOLD_C, RecordsCalculator } from '../src/domain/SensorRecords';
import { fixtureJson } from './helpers';

// Analytics domain functions and the daily-risk contract fields (WP-3.4). All data are synthetic.

function daily(rows: readonly (readonly [string, number | null, number | null, number | null, number, number | null])[]): DailyFile {
  return {
    sensor_id: '77678271',
    date: rows.map((row) => row[0]),
    temp_min: rows.map((row) => row[1]),
    temp_mean: rows.map((row) => row[2]),
    temp_max: rows.map((row) => row[3]),
    rh_min: rows.map(() => null),
    rh_mean: rows.map(() => null),
    rh_max: rows.map(() => null),
    coverage: rows.map((row) => row[4]),
    precip_sum_mm: rows.map((row) => row[5]),
  };
}

describe('isoDates', () => {
  it('counts calendar days across month, leap day and DST changes', () => {
    expect(addDays('2026-03-28', 2)).toBe('2026-03-30'); // across the CET -> CEST change
    expect(addDays('2028-02-28', 1)).toBe('2028-02-29');
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31');
    expect(daysBetween('2026-04-01', '2026-10-31')).toBe(213); // 214 days inclusive
    expect(dateRange('2026-06-29', '2026-07-01')).toEqual(['2026-06-29', '2026-06-30', '2026-07-01']);
    expect(dateRange('2026-07-02', '2026-07-01')).toEqual([]);
    expect(yearOf('2026-07-01')).toBe(2026);
    expect(noonUtcSeconds('1970-01-02')).toBe(86_400 + 43_200);
  });
});

describe('RiskStrip', () => {
  it('maps level ranks to traffic-light tones', () => {
    expect([0, 1, 2].map((rank) => toneForRank(rank, 3))).toEqual(['low', 'elevated', 'high']);
    expect([0, 1].map((rank) => toneForRank(rank, 2))).toEqual(['low', 'elevated']);
    expect([0, 1, 2, 3].map((rank) => toneForRank(rank, 4))).toEqual(['low', 'elevated', 'elevated', 'high']);
    expect(levelTones(['none', 'frost'])).toEqual([
      { level: 'none', tone: 'low' },
      { level: 'frost', tone: 'elevated' },
      { level: null, tone: null },
    ]);
  });

  it('spans the whole period and greys out unlisted and null days', () => {
    const block: IndexDaily = {
      levels: ['low', 'moderate', 'high'],
      start: '2026-06-01',
      end: '2026-06-05',
      date: ['2026-06-02', '2026-06-03', '2026-06-04'],
      value: [0, 70, 10],
      level: ['low', 'high', null],
    };
    const strip = RiskStrip.fromDaily(block);
    expect(strip.days.map((day) => day.tone)).toEqual([null, 'low', 'high', null, null]);
    expect(strip.days[3]).toEqual({ date: '2026-06-04', level: null, value: null, tone: null }); // no value without a level
    expect(strip.counts()).toEqual([
      { level: 'low', tone: 'low', days: 1 },
      { level: 'moderate', tone: 'elevated', days: 0 },
      { level: 'high', tone: 'high', days: 1 },
      { level: null, tone: null, days: 3 },
    ]);
    expect(strip.lastKnown()?.date).toBe('2026-06-03');
    expect(RiskStrip.fromDaily({ ...block, level: [null, null, null] }).lastKnown()).toBeNull();
  });
});

describe('RecordsCalculator', () => {
  // 2026: Jan 10 frost (-3.0), Mar 20 frost on an incomplete day (ignored), Apr 2 Tmin exactly 0 (frost),
  // Jun 30 frost, Jul 1 warmest, Oct 15 first autumn frost (-0.5), Nov 2 frost (-4.0 lowest).
  const file = daily([
    ['2025-12-31', -9.0, -5.0, -1.0, 1.0, 0.0],
    ['2026-01-10', -3.0, -1.0, 2.0, 1.0, 1.2],
    ['2026-03-20', -8.0, -2.0, 5.0, 0.5, 30.0],
    ['2026-04-02', 0.0, 6.0, 12.0, 0.95, 4.4],
    ['2026-06-30', -0.1, 14.0, 22.0, 0.9, null],
    ['2026-07-01', 15.0, 24.5, 34.6, 1.0, 12.5],
    ['2026-07-02', 16.0, 24.5, 34.6, 1.0, 12.5],
    ['2026-10-15', -0.5, 7.0, 15.0, 0.99, 0.0],
    ['2026-11-02', -4.0, -1.5, 1.0, 1.0, 0.2],
  ]);
  const calculator = new RecordsCalculator(0.9);

  it('takes extremes of complete days only, earliest date on ties', () => {
    const season = calculator.season(file, 2026);
    expect(season.daysTotal).toBe(8);
    expect(season.daysUsed).toBe(7); // Mar 20 has coverage 0.5 < 0.9
    expect(season.tempMin).toEqual({ value: -4.0, date: '2026-11-02' });
    expect(season.tempMax).toEqual({ value: 34.6, date: '2026-07-01' });
    expect(season.highestMean).toEqual({ value: 24.5, date: '2026-07-01' });
    expect(season.lowestMean).toEqual({ value: -1.5, date: '2026-11-02' });
    expect(season.maxPrecip).toEqual({ value: 12.5, date: '2026-07-01' });
  });

  it('finds the last spring and first autumn frost of the season', () => {
    expect(FROST_THRESHOLD_C).toBe(0);
    const season = calculator.season(file, 2026);
    expect(season.lastSpringFrost).toBe('2026-06-30');
    expect(season.firstAutumnFrost).toBe('2026-10-15');
    const spring = calculator.season(daily([['2026-04-02', 0.0, 6.0, 12.0, 1.0, null]]), 2026);
    expect(spring.lastSpringFrost).toBe('2026-04-02'); // T_min = 0 °C counts (T <= 0)
    expect(spring.firstAutumnFrost).toBeNull();
  });

  it('covers all data without frost dates', () => {
    const all = calculator.allData(file);
    expect(all.daysTotal).toBe(9);
    expect(all.daysUsed).toBe(8);
    expect(all.tempMin).toEqual({ value: -9.0, date: '2025-12-31' });
    expect([all.lastSpringFrost, all.firstAutumnFrost]).toEqual([null, null]);
  });

  it('has no records without complete days or without precipitation', () => {
    const withoutPrecip: DailyFile = { ...file, precip_sum_mm: undefined };
    expect(calculator.season(withoutPrecip, 2026).maxPrecip).toBeNull();
    const empty = calculator.season(file, 2024);
    expect(empty).toMatchObject({ tempMin: null, tempMax: null, daysTotal: 0, daysUsed: 0, lastSpringFrost: null });
  });
});

describe('daily risk contract (optional fields)', () => {
  const entry = { value: 70, unit: 'points', coverage: 0.4, complete: false, class: null };
  const block = { levels: ['low', 'high'], start: '2026-04-01', end: '2026-10-31', date: ['2026-06-01', '2026-06-02'], value: [0, 70], level: ['low', 'high'] };
  const file = (daily: unknown) => ({ season: 2026, computed_at: 'x', sensors: { a: { pm: { ...entry, daily } } } });

  it('reads a daily block and tolerates its absence', () => {
    const parsed = parseIndicesFile(file(block), 'indices/2026.json', () => undefined);
    expect(parsed.sensors.a?.pm?.daily).toEqual(block);
    const without = parseIndicesFile(file(undefined), 'indices/2026.json', () => undefined);
    expect(without.sensors.a?.pm?.daily).toBeUndefined();
  });

  it.each([
    ['unknown level', { ...block, level: ['low', 'extreme'] }, 'must be one of'],
    ['column length', { ...block, value: [0] }, 'must have 2 items'],
    ['date order', { ...block, date: ['2026-06-02', '2026-06-01'] }, 'must be after'],
    ['date format', { ...block, start: '1. 4. 2026' }, 'must be a date'],
  ])('ignores a malformed block with a warning (%s)', (_, daily, problem) => {
    const warn = vi.fn();
    const parsed = parseIndicesFile(file(daily), 'indices/2026.json', warn);
    expect(parsed.sensors.a?.pm?.daily).toBeUndefined();
    expect(parsed.sensors.a?.pm?.value).toBe(70);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining(problem));
  });

  it('reads min_daily_coverage of the manifest and ignores a share outside 0-1', () => {
    const manifest = fixtureJson('manifest.json') as Record<string, unknown>;
    expect(parseManifest(manifest).min_daily_coverage).toBe(0.9);
    const warn = vi.fn();
    expect(parseManifest({ ...manifest, min_daily_coverage: 1.5 }, 'manifest.json', warn).min_daily_coverage).toBeUndefined();
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('within 0-1'));
  });
});
