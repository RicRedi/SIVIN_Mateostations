import { describe, expect, it, vi } from 'vitest';
import { parseIndicesFile, parseManifest, type DailyFile, type IndexDaily } from '../src/contract';
import { addDays, dateRange, daysBetween, noonUtcSeconds, yearOf } from '../src/domain/isoDates';
import { levelTones, RiskStrip, toneForRank } from '../src/domain/RiskStrip';
import { FROST_THRESHOLD_C, HALF_OBSERVED_SHARE, RecordsCalculator } from '../src/domain/SensorRecords';
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

/** Synthetic daily file with every day from `start` to `end` complete (coverage 1), T_min `tMinC`. */
function fullDays(start: string, end: string, tMinC = 5): DailyFile {
  const dates = dateRange(start, end);
  return daily(dates.map((date) => [date, tMinC, tMinC + 5, tMinC + 10, 1, null] as const));
}

function withFrost(file: DailyFile, frostDates: readonly string[]): DailyFile {
  return { ...file, temp_min: file.temp_min.map((value, i) => (frostDates.includes(file.date[i] ?? '') ? -1.5 : value)) };
}

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

  it('takes temperature extremes of complete days only, earliest date on ties', () => {
    const season = calculator.season(file, 2026);
    expect(season.span).toEqual({
      start: '2026-01-01', end: '2026-12-31', periodDays: 365, daysUsed: 7, firstUsed: '2026-01-10', lastUsed: '2026-11-02',
    }); // Mar 20 has coverage 0.5 < 0.9
    expect(season.tempMin).toEqual({ value: -4.0, date: '2026-11-02' });
    expect(season.tempMax).toEqual({ value: 34.6, date: '2026-07-01' });
    expect(season.highestMean).toEqual({ value: 24.5, date: '2026-07-01' });
    expect(season.lowestMean).toEqual({ value: -1.5, date: '2026-11-02' });
  });

  it('uses only days with a complete rain gauge for the precipitation record', () => {
    // 0.9 x 86 400 s / 1830 s = 42.5 -> at least 43 interval values; coverage of T/RH is irrelevant.
    expect(calculator.season(file, 2026).maxPrecip).toBeNull(); // no precip_n_samples column
    const counted = { ...file, precip_n_samples: [47, 47, 47, 47, null, 42, 43, 47, 47] };
    expect(calculator.season(counted, 2026).maxPrecip).toEqual({ value: 30.0, date: '2026-03-20' }); // T incomplete, gauge complete
    expect(calculator.isCompletePrecipitationDay(counted, 5)).toBe(false); // 42 values
    expect(calculator.isCompletePrecipitationDay(counted, 6)).toBe(true); // 43 values
  });

  it('covers all data from the first to the last day, without frost dates', () => {
    const all = calculator.allData(file);
    expect(all.span).toMatchObject({ start: '2025-12-31', end: '2026-11-02', periodDays: 307, daysUsed: 8 });
    expect(all.tempMin).toEqual({ value: -9.0, date: '2025-12-31' });
    expect([all.lastSpringFrost, all.firstAutumnFrost]).toEqual([null, null]);
    const empty = calculator.allData(daily([]));
    expect(empty.span).toMatchObject({ periodDays: 0, daysUsed: 0, firstUsed: null });
  });

  it('says "no frost" only for an observed half season', () => {
    expect(FROST_THRESHOLD_C).toBe(0);
    expect(HALF_OBSERVED_SHARE).toBe(0.9);
    // Full year without frost: both halves observed.
    const year = calculator.season(fullDays('2026-01-01', '2026-12-31'), 2026);
    expect(year.lastSpringFrost?.kind).toBe('none');
    expect(year.firstAutumnFrost?.kind).toBe('none');
    // Data only Jun-Oct: spring has 30 of 181 days, autumn 123 of 184 (< 90 %): never "none".
    const summer = calculator.season(fullDays('2026-06-01', '2026-10-31'), 2026);
    expect(summer.lastSpringFrost).toMatchObject({ kind: 'noneInData', span: { daysUsed: 30, periodDays: 181 } });
    expect(summer.firstAutumnFrost).toMatchObject({ kind: 'noneInData', span: { daysUsed: 123, periodDays: 184, lastUsed: '2026-10-31' } });
    // Data only Jan-May (a season in progress): spring 151 of 181 days (83 %), autumn no data.
    const spring = calculator.season(fullDays('2026-01-01', '2026-05-31'), 2026);
    expect(spring.lastSpringFrost?.kind).toBe('noneInData');
    expect(spring.firstAutumnFrost?.kind).toBe('noData');
    // 90 % of the autumn (166 of 184 days: Jul 1 - Dec 13) is enough.
    expect(calculator.season(fullDays('2026-07-01', '2026-12-13'), 2026).firstAutumnFrost?.kind).toBe('none');
    expect(calculator.season(fullDays('2026-07-01', '2026-12-12'), 2026).firstAutumnFrost?.kind).toBe('noneInData');
  });

  it('reports a found frost and whether the half was observed', () => {
    const frosty = withFrost(fullDays('2026-01-01', '2026-12-31'), ['2026-03-01', '2026-04-20', '2026-10-25', '2026-11-30']);
    const season = calculator.season(frosty, 2026);
    expect(season.lastSpringFrost).toMatchObject({ kind: 'found', date: '2026-04-20', observed: true });
    expect(season.firstAutumnFrost).toMatchObject({ kind: 'found', date: '2026-10-25', observed: true });
    // T_min exactly 0 °C counts (T <= 0); data only to May: a later spring frost may be missing.
    const partial = calculator.season(daily([['2026-04-02', 0.0, 6.0, 12.0, 1.0, null]]), 2026);
    expect(partial.lastSpringFrost).toMatchObject({ kind: 'found', date: '2026-04-02', observed: false });
    expect(partial.firstAutumnFrost?.kind).toBe('noData');
    // The frost of Mar 20 is on an incomplete day and does not count.
    expect(calculator.season(file, 2026).lastSpringFrost).toMatchObject({ kind: 'found', date: '2026-06-30', observed: false });
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
