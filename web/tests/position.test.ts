import { describe, expect, it } from 'vitest';
import { formatPosition, POSITION_DECIMALS } from '../src/domain/position';

describe('formatPosition', () => {
  it('writes latitude first, six decimals and a decimal point', () => {
    expect(POSITION_DECIMALS).toBe(6);
    expect(formatPosition(48.880215, 16.673002)).toBe('48.880215, 16.673002');
    expect(formatPosition(48.8826, 16.6761)).toBe('48.882600, 16.676100');
    expect(formatPosition(49, 17)).toBe('49.000000, 17.000000');
  });

  it('rounds to the nearest micro-degree', () => {
    expect(formatPosition(48.8802154, 16.6730026)).toBe('48.880215, 16.673003');
  });

  it('keeps the sign of negative coordinates and drops it from a rounded zero', () => {
    expect(formatPosition(-33.8688, -70.5)).toBe('-33.868800, -70.500000');
    expect(formatPosition(-0.0000001, 0)).toBe('0.000000, 0.000000');
  });

  it('does not depend on the locale (no decimal comma)', () => {
    expect(formatPosition(48.5, 16.25)).not.toContain(',5');
  });
});
