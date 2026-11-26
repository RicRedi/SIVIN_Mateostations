// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import type { ChartData, SensorChartData } from '../../src/app/ChartDataLoader';
import { createQuantityRegistry } from '../../src/app/ChartQuantities';
import { csvFormat, CsvWriter, UTF8_BOM } from '../../src/app/CsvWriter';
import { SensorCatalog } from '../../src/app/SensorCatalog';
import { parseLatestFile, parseManifest, parseSensorsGeoJSON } from '../../src/contract';
import { TimeSeries } from '../../src/domain/TimeSeries';
import { TimeWindow } from '../../src/domain/TimeWindow';
import { TimeZone } from '../../src/domain/TimeZone';
import { ViewRange } from '../../src/domain/ViewRange';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { ChartCsv } from '../../src/ui/ChartCsv';
import { ChartModel } from '../../src/ui/ChartModel';
import { QuantityLabels } from '../../src/ui/QuantityLabels';
import { fixtureJson, utc } from '../helpers';

vi.hoisted(() => {
  // uPlot reads the device pixel ratio through matchMedia when it is imported; jsdom has none.
  window.matchMedia = () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) as unknown as MediaQueryList;
});

const manifest = parseManifest(fixtureJson('manifest.json'));
const catalog = SensorCatalog.build(parseSensorsGeoJSON(fixtureJson('sensors.geojson')), manifest, parseLatestFile(fixtureJson('latest.json')));
const registry = createQuantityRegistry(manifest.variables);
const zone = new TimeZone('Europe/Prague');
const T0 = utc(2026, 7, 1, 10);
const STEP = 1830;

/** Synthetic sensor data on the 1830 s grid (values invented, not measurements). */
function sensor(sensorId: string, offsetS: number, temp: (number | null)[], rh: (number | null)[], events: SensorChartData['events'] = []): SensorChartData {
  const t = temp.map((_, i) => T0 + offsetS + i * STEP);
  const empty = TimeSeries.of(t, t.map(() => null));
  return { sensorId, temp_c: TimeSeries.of(t, temp), rh_pct: TimeSeries.of(t, rh), precip_mm: empty, battery_v: empty, events };
}

const WINDOW = new TimeWindow(T0, T0 + 4 * STEP, 'raw');
const DATA: ChartData = {
  window: WINDOW,
  sensors: [
    sensor('77678271', 0, [20, 21.256, null, 18], [50, 92, 95, 60]),
    sensor('77799986', 60, [19, 19.5, 20, 20.5], [70, 71, 72, 73], [
      { type: 'off_site', t: T0 + 60 + STEP, t_end: T0 + 60 + 2 * STEP, source: 'log', confidence: null, detail: 'service' },
    ]),
  ],
  failures: [],
};

describe('ChartModel', () => {
  const model = ChartModel.build(DATA, registry.select(['temp_c', 'leaf_wetness']));

  it('aligns one column per sensor and quantity on the union of times', () => {
    expect(model.t).toEqual([T0, T0 + 60, T0 + STEP, T0 + STEP + 60, T0 + 2 * STEP, T0 + 2 * STEP + 60, T0 + 3 * STEP, T0 + 3 * STEP + 60]);
    expect(model.columns.map((c) => `${c.sensorId}:${c.quantity.id}`)).toEqual([
      '77678271:temp_c', '77678271:leaf_wetness', '77799986:temp_c', '77799986:leaf_wetness',
    ]);
    expect(model.columns[0]?.values).toEqual([20, undefined, 21.256, undefined, null, undefined, 18, undefined]);
    expect(model.bounds.equals(new ViewRange(WINDOW.startT, WINDOW.endT))).toBe(true);
    expect(model.hasValues).toBe(true);
  });

  it('blanks a sensor inside its off-site period', () => {
    expect(model.offSiteBands).toHaveLength(1);
    // 77799986 at T0 + 60 + STEP lies inside [t, t_end): no temperature there.
    expect(model.columns[2]?.values[3]).toBeNull();
    expect(model.columns[2]?.values[5]).toBe(20);
  });

  it('turns RH >= 90 % into wetness bands reaching half a nominal step to each side', () => {
    // 77678271 wet at T0 + STEP (92 %) and T0 + 2·STEP (95 %, temperature missing): one band.
    expect(model.wetLanes).toEqual([
      { sensorId: '77678271', intervals: [{ startT: T0 + STEP - STEP / 2, endT: T0 + 2 * STEP + STEP / 2 }] },
      { sensorId: '77799986', intervals: [] },
    ]);
  });

  it('lists rows inside a view that have a value', () => {
    // Row 3 (77799986 off site, 77678271 without a sample) has no value and is skipped.
    expect(model.rowsWithin(new ViewRange(T0 + STEP, T0 + 2 * STEP + 61))).toEqual([2, 4, 5]);
    const empty = ChartModel.build(DATA, []);
    expect(empty.hasValues).toBe(false);
    expect(empty.rowsWithin(empty.bounds)).toEqual([]);
  });
});

describe('CsvWriter', () => {
  it('writes a BOM, quotes fields with separator, quote or line break and uses CRLF', () => {
    const writer = new CsvWriter(csvFormat(','));
    expect(writer.write(['a;b', 'say "x"', 'plain'], [['1,5', 'two\nlines', '']])).toBe(
      `${UTF8_BOM}"a;b";"say ""x""";plain\r\n1,5;"two\nlines";\r\n`,
    );
  });

  it('formats numbers with fixed decimals, the decimal mark and no negative zero', () => {
    const comma = new CsvWriter(csvFormat(','));
    expect(comma.number(12.345, 2)).toBe('12,35');
    expect(comma.number(-0.0004, 2)).toBe('0,00');
    expect(comma.number(1234567.5, 1)).toBe('1234567,5');
    expect(comma.number(null, 2)).toBe('');
    expect(comma.number(undefined, 2)).toBe('');
    expect(comma.number(Number.NaN, 2)).toBe('');
    expect(new CsvWriter(csvFormat('.')).number(1, 0)).toBe('1');
  });
});

describe('ChartCsv', () => {
  const i18n = new I18n({ cs, de, en }, 'cs');
  const csv = new ChartCsv(i18n, catalog, zone, new QuantityLabels(i18n, manifest.variables));
  const model = ChartModel.build(DATA, registry.select(['temp_c', 'dew_point_c']));

  it('exports the visible rows with local and UTC time, labels, units and decimal comma', () => {
    const view = new ViewRange(T0, T0 + STEP + 61);
    const lines = csv.content(model, view).split('\r\n');
    expect(lines[0]).toBe(
      `${UTF8_BOM}Místní čas (Europe/Prague);Čas UTC (ISO 8601);77678271 (VUT) – Teplota (°C);77678271 (VUT) – Rosný bod (°C);77799986 (VUT) – Teplota (°C);77799986 (VUT) – Rosný bod (°C)`,
    );
    // 10:00 UTC is 12:00 in Prague (CEST). Dew point of 20 °C / 50 % = 9.26 °C.
    expect(lines[1]).toBe('2026-07-01 12:00:00;2026-07-01T10:00:00Z;20,00;9,26;;');
    // 19 °C / 70 %: γ = ln 0.7 + 17.625·19/262.04 = −0.356675 + 1.277954 = 0.921279; Td = 13.40 °C.
    expect(lines[2]).toBe('2026-07-01 12:01:00;2026-07-01T10:01:00Z;;;19,00;13,40');
    // 21.256 °C / 92 %: γ = ln 0.92 + 17.625·21.256/264.296 = −0.083382 + 1.417490 = 1.334108;
    // Td = 243.04·1.334108/(17.625 − 1.334108) = 19.90 °C. The temperature is rounded to 0.01.
    expect(lines[3]).toBe('2026-07-01 12:30:30;2026-07-01T10:30:30Z;21,26;19,90;;');
    // 77799986 is off site at 10:31:30: the row has no value and is left out.
    expect(lines).toHaveLength(5);
    expect(lines[4]).toBe('');
  });

  it('names the file after the sensors and the visible range in local time', () => {
    expect(csv.fileName(model, new ViewRange(T0, T0 + 3600))).toBe('sivin_77678271-77799986_20260701T1200_20260701T1300.csv');
    expect(csv.file(model, model.bounds).fileName).toBe('sivin_77678271-77799986_20260701T1200_20260701T1402.csv');
  });

  it('uses a decimal point in English and resolution-specific labels', () => {
    const english = new I18n({ cs, de, en }, 'en');
    const enCsv = new ChartCsv(english, catalog, zone, new QuantityLabels(english, manifest.variables));
    const daily: ChartData = { ...DATA, window: new TimeWindow(T0, T0 + 4 * STEP, 'daily') };
    const content = enCsv.content(ChartModel.build(daily, registry.select(['temp_c', 'precip_mm'])), new ViewRange(T0, T0 + 1));
    expect(content.split('\r\n')[0]).toContain('77678271 (VUT) – Temperature (°C);77678271 (VUT) – Daily precipitation (mm)');
    expect(content.split('\r\n')[1]).toBe('2026-07-01 12:00:00;2026-07-01T10:00:00Z;20.00;;;');
  });
});
