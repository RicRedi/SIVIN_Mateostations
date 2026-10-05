import { describe, expect, it } from 'vitest';
import { parseDailyFile, parseRawMonthFile } from '../src/contract';
import { QcMask } from '../src/domain/QcFlags';
import { RawSeries } from '../src/domain/RawSeries';

// Optional precipitation and battery fields of the series files (WP-1.9). All values are synthetic.

const SENSOR = '77799986';

function rawFile(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { sensor_id: SENSOR, t: [100, 200], temp_c: [1.2, null], rh_pct: [90, 91], qc: [0, 1], ...overrides };
}

function dailyFile(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    sensor_id: SENSOR,
    date: ['2026-01-01', '2026-01-02'],
    temp_min: [-2.1, -1.0],
    temp_mean: [0.4, 1.0],
    temp_max: [3.0, 4.0],
    rh_min: [70, 71],
    rh_mean: [88.1, 89],
    rh_max: [99, 98],
    coverage: [0.98, 1],
    ...overrides,
  };
}

describe('raw month files with optional precipitation and battery', () => {
  it('reads both fields when present, with nulls', () => {
    const file = parseRawMonthFile(rawFile({ precip_mm: [0, 0.3], battery_v: [3.6, null] }), 'raw.json');
    expect(file.precip_mm).toEqual([0, 0.3]);
    expect(file.battery_v).toEqual([3.6, null]);
  });

  it('leaves absent fields out, so older files stay valid', () => {
    const file = parseRawMonthFile(rawFile(), 'raw.json');
    expect('precip_mm' in file).toBe(false);
    expect('battery_v' in file).toBe(false);
    expect(parseRawMonthFile(rawFile({ battery_v: [3.5, 3.4] }), 'raw.json').precip_mm).toBeUndefined();
  });

  it('rejects a present field of the wrong length or type', () => {
    expect(() => parseRawMonthFile(rawFile({ precip_mm: [0] }), 'raw.json')).toThrow(
      'raw.json: $.precip_mm must have 2 items like "t", got 1',
    );
    expect(() => parseRawMonthFile(rawFile({ battery_v: [3.6, '3.5'] }), 'raw.json')).toThrow(
      '$.battery_v[1] must be a finite number, got "3.5"',
    );
    expect(() => parseRawMonthFile(rawFile({ precip_mm: null }), 'raw.json')).toThrow(
      '$.precip_mm must be an array, got null',
    );
  });

  it('does not disturb the merged temperature and humidity series', () => {
    const withExtras = parseRawMonthFile(rawFile({ precip_mm: [0, 0.3], battery_v: [3.6, 3.5] }), 'a.json');
    const without = parseRawMonthFile(rawFile({ t: [300, 400] }), 'b.json');
    const merged = RawSeries.merge(SENSOR, [withExtras, without]);
    expect(merged.t).toEqual([100, 200, 300, 400]);
    expect(merged.variable('rh_pct', new QcMask(0)).values).toEqual([90, 91, 90, 91]);
  });
});

describe('daily files with optional precipitation sum and battery minimum', () => {
  it('reads both fields when present, with nulls', () => {
    const file = parseDailyFile(dailyFile({ precip_sum_mm: [1.5, null], battery_min_v: [3.4, 3.2] }), 'daily.json');
    expect(file.precip_sum_mm).toEqual([1.5, null]);
    expect(file.battery_min_v).toEqual([3.4, 3.2]);
  });

  it('leaves absent fields out', () => {
    const file = parseDailyFile(dailyFile(), 'daily.json');
    expect(file.precip_sum_mm).toBeUndefined();
    expect(file.battery_min_v).toBeUndefined();
    expect(file.coverage).toEqual([0.98, 1]);
  });

  it('rejects a present field of the wrong length', () => {
    expect(() => parseDailyFile(dailyFile({ battery_min_v: [3.4] }), 'daily.json')).toThrow(
      'daily.json: $.battery_min_v must have 2 items like "t", got 1',
    );
  });
});
