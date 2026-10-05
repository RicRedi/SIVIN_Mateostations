import { describe, expect, it } from 'vitest';
import {
  MAX_EXPLICIT_HOURLY_WINDOW_S,
  MAX_EXPLICIT_RAW_WINDOW_S,
  MAX_HOURLY_WINDOW_S,
  MAX_RAW_WINDOW_S,
  ResolutionPolicy,
} from '../src/domain/ResolutionPolicy';
import { TimeWindow } from '../src/domain/TimeWindow';
import { TimeWindowFactory } from '../src/domain/TimeWindowFactory';
import { TimeZone } from '../src/domain/TimeZone';
import { utc } from './helpers';

const DAY = 86_400;
const HOUR = 3600;
const factory = new TimeWindowFactory(new TimeZone('Europe/Prague'), new ResolutionPolicy());
/** Last sample 21:34Z on 30 Sep 2026; windows end at the next full hour, 22:00Z (= local midnight). */
const ANCHOR = utc(2026, 9, 30, 21, 34);
const END = utc(2026, 9, 30, 22);

describe('TimeWindow', () => {
  it('is an immutable half-open interval', () => {
    const window = new TimeWindow(10, 20, 'raw');
    expect(window.durationS).toBe(10);
    expect(window.contains(10)).toBe(true);
    expect(window.contains(20)).toBe(false);
    expect(Object.isFrozen(window)).toBe(true);
    expect(window.withResolution('daily').resolution).toBe('daily');
    expect(() => new TimeWindow(20, 20, 'raw')).toThrow('must be after start');
  });
});

describe('TimeWindowFactory presets', () => {
  it('24 h is exactly 86 400 s ending at the next full hour after the data', () => {
    const window = factory.create({ kind: '24h' }, ANCHOR, 'auto');
    expect([window.startT, window.endT]).toEqual([END - DAY, END]);
    expect(window.resolution).toBe('raw');
  });

  it('7 d goes back seven local days', () => {
    const window = factory.create({ kind: '7d' }, ANCHOR, 'auto');
    expect(window.startT).toBe(utc(2026, 9, 23, 22));
    expect(window.durationS).toBe(7 * DAY);
    expect(window.resolution).toBe('raw');
  });

  it('a 7 d window over the end of DST (25 Oct 2026) is one hour longer', () => {
    // Ends Wed 28 Oct 12:00 CET (11:00Z); starts Wed 21 Oct 12:00 CEST (10:00Z).
    const window = factory.create({ kind: '7d' }, utc(2026, 10, 28, 11), 'auto');
    expect(window.startT).toBe(utc(2026, 10, 21, 10));
    expect(window.durationS).toBe(7 * DAY + HOUR);
    expect(window.resolution).toBe('raw');
  });

  it('30 d uses hourly means automatically', () => {
    const window = factory.create({ kind: '30d' }, ANCHOR, 'auto');
    expect(window.startT).toBe(utc(2026, 8, 31, 22));
    expect(window.resolution).toBe('hourly');
  });

  it('season is 1 Apr – 31 Oct local time, daily by default', () => {
    const window = factory.create({ kind: 'season', year: 2026 }, ANCHOR, 'auto');
    // 1 Apr 00:00 CEST = 31 Mar 22:00Z; 1 Nov 00:00 CET = 31 Oct 23:00Z.
    expect(window.startT).toBe(utc(2026, 3, 31, 22));
    expect(window.endT).toBe(utc(2026, 10, 31, 23));
    expect(window.durationS).toBe(214 * DAY + HOUR);
    expect(window.resolution).toBe('daily');
  });

  it('custom covers whole local days, inclusive, in either order', () => {
    const expected = [utc(2026, 6, 9, 22), utc(2026, 6, 12, 22)];
    const forward = factory.create({ kind: 'custom', from: '2026-06-10', to: '2026-06-12' }, ANCHOR, 'auto');
    const backward = factory.create({ kind: 'custom', from: '2026-06-12', to: '2026-06-10' }, ANCHOR, 'auto');
    expect([forward.startT, forward.endT]).toEqual(expected);
    expect([backward.startT, backward.endT]).toEqual(expected);
  });

  it('an explicit resolution overrides the automatic one', () => {
    expect(factory.create({ kind: '24h' }, ANCHOR, 'daily').resolution).toBe('daily');
    expect(factory.create({ kind: '30d' }, ANCHOR, 'raw').resolution).toBe('raw');
  });
});

describe('ResolutionPolicy', () => {
  it('switches at the documented limits', () => {
    const policy = new ResolutionPolicy();
    expect(policy.resolutionFor(MAX_RAW_WINDOW_S)).toBe('raw');
    expect(policy.resolutionFor(MAX_RAW_WINDOW_S + 1)).toBe('hourly');
    expect(policy.resolutionFor(MAX_HOURLY_WINDOW_S)).toBe('hourly');
    expect(policy.resolutionFor(MAX_HOURLY_WINDOW_S + 1)).toBe('daily');
  });

  it('honours an explicit choice up to the point caps, then gets coarser', () => {
    const policy = new ResolutionPolicy();
    expect(policy.resolve('auto', MAX_RAW_WINDOW_S)).toBe('raw');
    expect(policy.resolve('raw', MAX_EXPLICIT_RAW_WINDOW_S)).toBe('raw');
    expect(policy.resolve('raw', MAX_EXPLICIT_RAW_WINDOW_S + 1)).toBe('hourly');
    expect(policy.resolve('raw', MAX_EXPLICIT_HOURLY_WINDOW_S + 1)).toBe('daily');
    expect(policy.resolve('hourly', MAX_EXPLICIT_HOURLY_WINDOW_S)).toBe('hourly');
    expect(policy.resolve('hourly', MAX_EXPLICIT_HOURLY_WINDOW_S + 1)).toBe('daily');
    expect(policy.resolve('daily', 1)).toBe('daily');
  });

  it('caps an explicit hourly season to daily values', () => {
    expect(factory.create({ kind: 'season', year: 2026 }, ANCHOR, 'hourly').resolution).toBe('daily');
  });
});
