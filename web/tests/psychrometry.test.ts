import { describe, expect, it } from 'vitest';
import {
  absoluteHumidityGM3,
  actualVapourPressureKpa,
  dewPointC,
  isLeafWet,
  saturationVapourPressureKpa,
  vapourPressureDeficitKpa,
} from '../src/domain/psychrometry';

// Expected values are computed by hand from the formulas in docs/indices/dew_point.md and
// docs/indices/vpd.md; the inputs are made-up round numbers, not measurements.
describe('dewPointC (Magnus, Alduchov & Eskridge 1996)', () => {
  it('gives 9.261 °C at 20 °C / 50 % (the value docs/indices/dew_point.md quotes)', () => {
    // γ = ln(0.5) + 17.625·20/263.04 = −0.693147 + 1.340101 = 0.646954; Td = 243.04·γ/(17.625 − γ) = 9.2611
    expect(dewPointC(20, 50)).toBeCloseTo(9.2611, 4);
  });

  it('equals the air temperature at saturation', () => {
    // RH = 100 %: γ = a·T/(b + T), so Td = b·a·T/(a·(b + T) − a·T) = T.
    expect(dewPointC(12.5, 100)).toBeCloseTo(12.5, 10);
    expect(dewPointC(-3, 100)).toBeCloseTo(-3, 10);
  });

  it('is undefined (null) for RH <= 0 and non-finite input, like the Python NaN', () => {
    expect(dewPointC(20, 0)).toBeNull();
    expect(dewPointC(20, -1)).toBeNull();
    expect(dewPointC(Number.NaN, 50)).toBeNull();
  });
});

describe('vapour pressure (FAO-56 eq. 11)', () => {
  it('has e_s(0 °C) = 0.6108 kPa and e_s(20 °C) = 2.3383 kPa', () => {
    expect(saturationVapourPressureKpa(0)).toBe(0.6108);
    // 0.6108·exp(17.27·20/257.3) = 0.6108·exp(1.342402) = 0.6108·3.828227 = 2.33828
    expect(saturationVapourPressureKpa(20)).toBeCloseTo(2.33828, 5);
  });

  it('computes e_a and the VPD from RH', () => {
    expect(actualVapourPressureKpa(0, 50)).toBeCloseTo(0.3054, 10);
    expect(vapourPressureDeficitKpa(0, 50)).toBeCloseTo(0.3054, 10);
    expect(vapourPressureDeficitKpa(20, 50)).toBeCloseTo(1.16914, 5);
    expect(vapourPressureDeficitKpa(20, 100)).toBeCloseTo(0, 10);
  });

  it('passes RH above 100 % through as a negative VPD and rejects RH <= 0', () => {
    expect(vapourPressureDeficitKpa(0, 110)).toBeCloseTo(-0.06108, 10);
    expect(vapourPressureDeficitKpa(0, 0)).toBeNull();
    expect(actualVapourPressureKpa(0, -5)).toBeNull();
  });
});

describe('absoluteHumidityGM3 (ideal-gas law for water vapour)', () => {
  it('gives 4.845 g/m³ at 0 °C / 100 % and 8.642 g/m³ at 20 °C / 50 %', () => {
    // 0.6108 kPa = 610.8 Pa; 610.8 / (461.5 · 273.15) = 0.0048454 kg/m³
    expect(absoluteHumidityGM3(0, 100)).toBeCloseTo(4.8454, 4);
    // 1169.14 Pa / (461.5 · 293.15) = 0.0086418 kg/m³
    expect(absoluteHumidityGM3(20, 50)).toBeCloseTo(8.6418, 4);
  });

  it('is null for RH <= 0', () => {
    expect(absoluteHumidityGM3(20, 0)).toBeNull();
  });
});

describe('isLeafWet', () => {
  it('uses RH >= 90 % by default', () => {
    expect(isLeafWet(90)).toBe(true);
    expect(isLeafWet(89.9)).toBe(false);
    expect(isLeafWet(85, 80)).toBe(true);
  });
});
