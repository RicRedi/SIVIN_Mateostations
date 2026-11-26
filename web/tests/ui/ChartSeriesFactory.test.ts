// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import type uPlot from 'uplot';
import type { ChartData, SensorChartData } from '../../src/app/ChartDataLoader';
import { createQuantityRegistry } from '../../src/app/ChartQuantities';
import { SensorCatalog } from '../../src/app/SensorCatalog';
import { parseLatestFile, parseManifest, parseSensorsGeoJSON } from '../../src/contract';
import type { QuantityId } from '../../src/domain/quantities';
import { TimeSeries } from '../../src/domain/TimeSeries';
import { TimeWindow } from '../../src/domain/TimeWindow';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { ChartModel } from '../../src/ui/ChartModel';
import { barRange, ChartSeriesFactory, LINE_STYLES, tickDecimals } from '../../src/ui/ChartSeriesFactory';
import { QuantityLabels } from '../../src/ui/QuantityLabels';
import { fixtureJson } from '../helpers';

vi.hoisted(() => {
  // uPlot reads the device pixel ratio through matchMedia when it is imported; jsdom has none.
  window.matchMedia = () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) as unknown as MediaQueryList;
});

const manifest = parseManifest(fixtureJson('manifest.json'));
const catalog = SensorCatalog.build(parseSensorsGeoJSON(fixtureJson('sensors.geojson')), manifest, parseLatestFile(fixtureJson('latest.json')));
const registry = createQuantityRegistry(manifest.variables);
const i18n = new I18n({ cs, de, en }, 'cs');
const factory = new ChartSeriesFactory(i18n, catalog, registry, new QuantityLabels(i18n, manifest.variables), () => '#2a78d6');
// One synthetic sample (20 °C / 95 %), not a measurement.
const one = TimeSeries.of([100], [20]);
const sensor: SensorChartData = {
  sensorId: '77678271', temp_c: one, rh_pct: TimeSeries.of([100], [95]), precip_mm: TimeSeries.of([100], [0.4]), battery_v: one, events: [],
};
const data: ChartData = { window: new TimeWindow(0, 3600, 'raw'), sensors: [sensor], failures: [] };

function model(ids: readonly QuantityId[]): ChartModel {
  return ChartModel.build(data, registry.select(ids));
}

describe('ChartSeriesFactory', () => {
  it('styles each quantity in the sensor colour on its scale', () => {
    const m = model(['temp_c', 'rh_pct', 'dew_point_c', 'leaf_wetness', 'vpd_kpa']);
    const series = m.columns.map((column) => factory.series(column, 'raw'));
    expect(series.map((s) => [s.scale, s.dash])).toEqual([
      ['temp', LINE_STYLES.solid.dash], ['rh', LINE_STYLES.dashed.dash], ['temp', LINE_STYLES.dotted.dash], ['wet', undefined], ['extra', LINE_STYLES.dashDot.dash],
    ]);
    expect(series[2]?.label).toBe('77678271 (VUT) · Rosný bod');
    const value = (i: number, v: number | null) => (series[i]?.value as (u: uPlot, v: number | null) => string)({} as uPlot, v);
    expect(value(0, 20.04)).toBe('20,0 °C');
    expect(value(4, 1.234)).toBe('1,23 kPa');
    expect(value(3, 1)).toBe('mokro (odhad)');
    expect(value(3, 0)).toBe('sucho');
    expect([value(0, null), value(3, null)]).toEqual(['–', '–']);
    expect((series[3]?.paths as () => null)()).toBeNull();
  });

  it('draws precipitation as bars from 0', () => {
    const m = model(['temp_c', 'precip_mm']);
    const bars = factory.series(m.columns[1] ?? (undefined as never), 'hourly');
    expect(bars.label).toBe('77678271 (VUT) · Srážky za hodinu');
    expect(bars.fill).toBe('#2a78d68c');
    expect(bars.paths).toBeTypeOf('function');
    expect(factory.scales(m).extra?.range).toBe(barRange);
    const range = barRange as (u: uPlot, min: number, max: number) => [number, number];
    expect(range({} as uPlot, 0, 2)).toEqual([0, 2.2]);
    expect(range({} as uPlot, 0, 0)).toEqual([0, 1]);
    expect(factory.scales(model(['vpd_kpa'])).extra).toBeUndefined();
  });

  it('shows only the axes in use, the third one with its unit', () => {
    const shown = (ids: readonly QuantityId[]) => factory.axes(model(ids), false).map((a) => [a.scale, a.show, a.label]);
    expect(shown(['temp_c', 'rh_pct'])).toEqual([['temp', true, '°C'], ['rh', true, '%'], ['extra', false, '']]);
    expect(shown(['rh_pct', 'battery_v'])).toEqual([['temp', false, '°C'], ['rh', true, '%'], ['extra', true, 'V']]);
    const [temp, rh] = factory.axes(model(['rh_pct']), true);
    expect([temp?.size, rh?.grid?.show]).toEqual([38, true]);
    const ticks = (temp?.values as (u: uPlot, t: number[]) => string[])({} as uPlot, [2.5, 5, 7.5]);
    expect(ticks).toEqual(['2,5', '5,0', '7,5']);
  });

  it('gives tick labels as many decimals as their spacing needs', () => {
    expect(tickDecimals([0, 5, 10])).toBe(0);
    expect(tickDecimals([0, 0.05, 0.1])).toBe(2);
    expect(tickDecimals([0.1, 0.2])).toBe(1);
    expect(tickDecimals([0, 0.0001])).toBe(3);
    expect(tickDecimals([1])).toBe(0);
  });
});
