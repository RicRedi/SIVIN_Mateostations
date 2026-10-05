import { describe, expect, it } from 'vitest';
import { SENSOR_COLORS, STALE_COLOR, TEMPERATURE_COLORS, TemperatureScale, sensorColor } from '../../src/ui/palette';

describe('TemperatureScale', () => {
  const scale = new TemperatureScale();

  it('maps temperatures to diverging classes; edges belong to the warmer class', () => {
    expect(scale.colorFor(-20)).toBe(TEMPERATURE_COLORS[0]);
    expect(scale.colorFor(-5)).toBe(TEMPERATURE_COLORS[1]);
    expect(scale.colorFor(9.9)).toBe(TEMPERATURE_COLORS[3]);
    expect(scale.colorFor(10)).toBe(TEMPERATURE_COLORS[4]);
    expect(scale.colorFor(14.9)).toBe(TEMPERATURE_COLORS[4]);
    expect(scale.colorFor(30)).toBe(TEMPERATURE_COLORS[8]);
    expect(STALE_COLOR).not.toBe(TEMPERATURE_COLORS[4]);
  });

  it('describes open-ended legend classes', () => {
    expect(scale.classes[0]).toEqual({ lowerC: null, upperC: -5, color: TEMPERATURE_COLORS[0] });
    expect(scale.classes.at(-1)).toEqual({ lowerC: 30, upperC: null, color: TEMPERATURE_COLORS[8] });
  });

  it('requires one more colour than edges', () => {
    expect(() => new TemperatureScale([0, 10], ['#000', '#fff'])).toThrow('Need 3 colours');
  });
});

describe('sensorColor', () => {
  it('assigns colours by registry position and wraps', () => {
    expect(sensorColor(0)).toBe(SENSOR_COLORS[0]);
    expect(sensorColor(SENSOR_COLORS.length + 1)).toBe(SENSOR_COLORS[1]);
  });
});
