import { describe, expect, it } from 'vitest';
import type { SensorChartData } from '../src/app/ChartDataLoader';
import { createQuantityRegistry, MeasuredQuantity, QuantityRegistry } from '../src/app/ChartQuantities';
import { parseManifest } from '../src/contract';
import { WET } from '../src/domain/derivedSeries';
import { TimeSeries } from '../src/domain/TimeSeries';
import { extraAxisOf, normalizeQuantities, sameQuantities, toggleQuantity, withExtraAxis } from '../src/state/QuantitySelection';
import { fixtureJson } from './helpers';

describe('QuantitySelection', () => {
  it('normalises to known ids, canonical order and one extra axis', () => {
    expect(normalizeQuantities(['vpd_kpa', 'temp_c', 'x', 'temp_c', 'precip_mm'])).toEqual(['temp_c', 'vpd_kpa']);
    expect(normalizeQuantities([])).toEqual([]);
  });

  it('toggles base quantities freely and replaces the extra-axis quantity', () => {
    expect(toggleQuantity(['temp_c', 'rh_pct'], 'dew_point_c')).toEqual(['temp_c', 'rh_pct', 'dew_point_c']);
    expect(toggleQuantity(['temp_c', 'rh_pct'], 'rh_pct')).toEqual(['temp_c']);
    expect(toggleQuantity(['temp_c', 'vpd_kpa'], 'battery_v')).toEqual(['temp_c', 'battery_v']);
    expect(toggleQuantity(['temp_c', 'vpd_kpa'], 'vpd_kpa')).toEqual(['temp_c']);
  });

  it('sets or clears the extra axis', () => {
    expect(withExtraAxis(['temp_c', 'vpd_kpa'], 'precip_mm')).toEqual(['temp_c', 'precip_mm']);
    expect(withExtraAxis(['temp_c', 'vpd_kpa'], null)).toEqual(['temp_c']);
    expect(extraAxisOf(['temp_c', 'abs_humidity_g_m3'])).toBe('abs_humidity_g_m3');
    expect(extraAxisOf(['temp_c'])).toBeNull();
    expect(sameQuantities(['temp_c', 'rh_pct'], ['rh_pct', 'temp_c'])).toBe(true);
    expect(sameQuantities(['temp_c'], ['rh_pct'])).toBe(false);
  });
});

describe('ChartQuantities', () => {
  const registry = createQuantityRegistry(parseManifest(fixtureJson('manifest.json')).variables);
  // Synthetic sensor data: 20 °C / 50 % and 10 °C / 95 %.
  const t = [1000, 2000];
  const sensor: SensorChartData = {
    sensorId: 'synthetic',
    temp_c: TimeSeries.of(t, [20, 10]),
    rh_pct: TimeSeries.of(t, [50, 95]),
    precip_mm: TimeSeries.of(t, [0.2, null]),
    battery_v: TimeSeries.of(t, [3.6, 3.5]),
    events: [],
  };

  it('registers every quantity once, in display order', () => {
    expect(registry.all().map((q) => q.id)).toEqual([
      'temp_c', 'rh_pct', 'dew_point_c', 'leaf_wetness', 'vpd_kpa', 'abs_humidity_g_m3', 'precip_mm', 'battery_v',
    ]);
    expect(registry.select(['vpd_kpa', 'temp_c']).map((q) => q.id)).toEqual(['temp_c', 'vpd_kpa']);
    expect(() => new QuantityRegistry().register(registry.get('temp_c')).register(registry.get('temp_c'))).toThrow('registered twice');
    expect(() => new QuantityRegistry().get('temp_c')).toThrow('Unknown chart quantity');
  });

  it('computes derived quantities from the shown temperature and humidity', () => {
    expect(registry.get('dew_point_c').series(sensor).values[0]).toBeCloseTo(9.2611, 4);
    expect(registry.get('vpd_kpa').series(sensor).values[0]).toBeCloseTo(1.16914, 5);
    expect(registry.get('abs_humidity_g_m3').series(sensor).values[0]).toBeCloseTo(8.6418, 4);
    expect(registry.get('leaf_wetness').series(sensor).values).toEqual([0, WET]);
    expect(registry.get('precip_mm').series(sensor)).toBe(sensor.precip_mm);
    expect(registry.get('battery_v').series(sensor)).toBe(sensor.battery_v);
  });

  it('describes axes, units and resolution-dependent labels', () => {
    expect(registry.get('temp_c').display).toMatchObject({ unit: '°C', axis: 'temp', style: 'solid' });
    expect(registry.get('dew_point_c').display).toMatchObject({ unit: '°C', axis: 'temp', style: 'dotted' });
    expect(registry.get('rh_pct').display).toMatchObject({ unit: '%', axis: 'rh' });
    expect(registry.get('leaf_wetness').display.axis).toBe('band');
    expect(registry.get('leaf_wetness').labelParams()).toEqual({ threshold: 90 });
    expect(registry.get('temp_c').labelParams()).toEqual({});
    expect(registry.get('precip_mm').display).toMatchObject({ unit: 'mm', axis: 'extra', style: 'bars' });
    expect(registry.get('precip_mm').labelKey('raw')).toBe('quantityPrecip');
    expect(registry.get('precip_mm').labelKey('hourly')).toBe('quantityPrecipHourly');
    expect(registry.get('precip_mm').labelKey('daily')).toBe('quantityPrecipDaily');
    expect(registry.get('battery_v').labelKey('hourly')).toBe('quantityBattery');
    expect(registry.get('battery_v').labelKey('daily')).toBe('quantityBatteryDaily');
    const temp = registry.get('temp_c');
    expect(temp instanceof MeasuredQuantity && temp.manifestLabelled).toBe(true);
  });

  it('falls back to the contract units without manifest variables', () => {
    const bare = createQuantityRegistry([]);
    expect(bare.get('temp_c').display.unit).toBe('°C');
    expect(bare.get('rh_pct').display.unit).toBe('%');
  });
});
