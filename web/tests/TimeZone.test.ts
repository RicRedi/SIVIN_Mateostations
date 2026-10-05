import { describe, expect, it } from 'vitest';
import { TimeZone } from '../src/domain/TimeZone';
import { utc } from './helpers';

const prague = new TimeZone('Europe/Prague');

describe('TimeZone (Europe/Prague)', () => {
  it('knows winter (CET) and summer (CEST) offsets', () => {
    expect(prague.offsetS(utc(2026, 1, 15, 12))).toBe(3600);
    expect(prague.offsetS(utc(2026, 7, 15, 12))).toBe(7200);
  });

  it('converts a wall-clock time to UTC', () => {
    expect(prague.toUtc({ year: 2026, month: 7, day: 1, hour: 0, minute: 0, second: 0 })).toBe(utc(2026, 6, 30, 22));
    expect(prague.toLocal(utc(2026, 6, 30, 22))).toEqual({ year: 2026, month: 7, day: 1, hour: 0, minute: 0, second: 0 });
  });

  it('resolves a repeated time on 25 Oct 2026 to the earlier instant', () => {
    // 02:30 local happens at 00:30Z (CEST) and again at 01:30Z (CET).
    expect(prague.toUtc({ year: 2026, month: 10, day: 25, hour: 2, minute: 30, second: 0 })).toBe(utc(2026, 10, 25, 0, 30));
  });

  it('moves a time skipped on 29 Mar 2026 one hour later', () => {
    // 02:30 local does not exist; 01:30Z is 03:30 CEST.
    expect(prague.toUtc({ year: 2026, month: 3, day: 29, hour: 2, minute: 30, second: 0 })).toBe(utc(2026, 3, 29, 1, 30));
  });

  it('shifts by local calendar days across DST', () => {
    expect(prague.addDays(utc(2026, 10, 28, 11), -7)).toBe(utc(2026, 10, 21, 10));
    expect(prague.isoDate(utc(2026, 6, 30, 22))).toBe('2026-07-01');
    expect(prague.startOfDate('2026-12-24')).toBe(utc(2026, 12, 23, 23));
  });

  it('rejects malformed dates and unknown zones', () => {
    expect(() => prague.startOfDate('24.12.2026')).toThrow('Expected a date YYYY-MM-DD');
    expect(() => new TimeZone('Mars/Olympus')).toThrow(RangeError);
  });

  it('computes the next calendar date', () => {
    expect(TimeZone.nextIsoDate('2026-02-28')).toBe('2026-03-01');
    expect(TimeZone.nextIsoDate('2026-12-31')).toBe('2027-01-01');
  });
});
