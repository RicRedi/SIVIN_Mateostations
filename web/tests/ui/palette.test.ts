import { describe, expect, it } from 'vitest';
import { SENSOR_COLORS, STALE_COLOR, TEMPERATURE_COLORS, TemperatureScale } from '../../src/ui/palette';
import { SensorColors } from '../../src/ui/SensorColors';

/** WCAG 2 contrast ratio of two #rrggbb colours. */
function contrast(a: string, b: string): number {
  const luminance = (hex: string): number => {
    const [r, g, bl] = [1, 3, 5].map((i) => {
      const v = parseInt(hex.slice(i, i + 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (bl ?? 0);
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
}

describe('palette', () => {
  it('every sensor line colour and the stale fill reach 3:1 against white', () => {
    for (const color of [...SENSOR_COLORS, STALE_COLOR]) {
      expect(contrast(color, '#ffffff')).toBeGreaterThanOrEqual(3);
    }
  });

  it('has no near-white temperature class', () => {
    for (const color of TEMPERATURE_COLORS) {
      expect(contrast(color, '#ffffff')).toBeGreaterThan(1.4);
    }
  });
});

describe('TemperatureScale', () => {
  const scale = new TemperatureScale();

  it('maps temperatures to classes; edges belong to the warmer class; 10 °C starts the warm arm', () => {
    expect(scale.colorFor(-20)).toBe(TEMPERATURE_COLORS[0]);
    expect(scale.colorFor(-5)).toBe(TEMPERATURE_COLORS[1]);
    expect(scale.colorFor(9.9)).toBe(TEMPERATURE_COLORS[3]);
    expect(scale.colorFor(10)).toBe(TEMPERATURE_COLORS[4]);
    expect(scale.colorFor(14.9)).toBe(TEMPERATURE_COLORS[4]);
    expect(scale.colorFor(30)).toBe(TEMPERATURE_COLORS[8]);
  });

  it('describes open-ended legend classes', () => {
    expect(scale.classes[0]).toEqual({ lowerC: null, upperC: -5, color: TEMPERATURE_COLORS[0] });
    expect(scale.classes.at(-1)).toEqual({ lowerC: 30, upperC: null, color: TEMPERATURE_COLORS[8] });
  });

  it('requires one more colour than edges', () => {
    expect(() => new TemperatureScale([0, 10], ['#000', '#fff'])).toThrow('Need 3 colours');
  });
});

describe('SensorColors', () => {
  it('assigns colours in selection order', () => {
    const colors = new SensorColors();
    colors.update(['c', 'a']);
    expect(colors.colorFor('c')).toBe(SENSOR_COLORS[0]);
    expect(colors.colorFor('a')).toBe(SENSOR_COLORS[1]);
    expect(colors.colorFor('b')).toBeNull();
  });

  it('keeps colours of sensors that stay selected and reuses freed slots', () => {
    const colors = new SensorColors();
    colors.update(['a', 'b', 'c']);
    colors.update(['b', 'c']);
    expect(colors.colorFor('b')).toBe(SENSOR_COLORS[1]);
    expect(colors.colorFor('c')).toBe(SENSOR_COLORS[2]);
    colors.update(['b', 'c', 'd']);
    expect(colors.colorFor('d')).toBe(SENSOR_COLORS[0]);
  });

  it('never gives two of eight compared sensors the same colour, whatever their registry position', () => {
    const colors = new SensorColors();
    const ids = ['s0', 's8', 's16', 's3', 's11', 's5', 's13', 's7'];
    colors.update(ids);
    expect(new Set(ids.map((id) => colors.colorFor(id))).size).toBe(8);
  });

  it('wraps only beyond the palette size', () => {
    const colors = new SensorColors(['#111111', '#222222']);
    colors.update(['a', 'b', 'c']);
    expect(colors.colorFor('c')).toBe('#111111');
  });
});
