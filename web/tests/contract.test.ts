import { describe, expect, it } from 'vitest';
import {
  ContractError,
  parseDailyFile,
  parseEventsFile,
  parseIndicesFile,
  parseLatestFile,
  parseManifest,
  parseRawMonthFile,
  parseSensorsGeoJSON,
} from '../src/contract';
import { fixtureJson } from './helpers';

const SENSOR = '77678271';

function rawFile(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { sensor_id: SENSOR, t: [100, 200], temp_c: [1.2, null], rh_pct: [90, 91], qc: [0, 1], ...overrides };
}

describe('the committed synthetic fixture', () => {
  it('passes validation of every contract file', () => {
    const manifest = parseManifest(fixtureJson('manifest.json'));
    expect(manifest.schema_version).toBe(1);
    expect(manifest.display_timezone).toBe('Europe/Prague');
    expect(Object.keys(manifest.sensors)).toHaveLength(4);
    expect(parseSensorsGeoJSON(fixtureJson('sensors.geojson')).features).toHaveLength(4);
    expect(parseLatestFile(fixtureJson('latest.json')).sensors['77800065']?.stale).toBe(true);
    expect(parseIndicesFile(fixtureJson('indices/2026.json'), 'indices/2026.json').season).toBe(2026);
    for (const [id, sensor] of Object.entries(manifest.sensors)) {
      expect(parseDailyFile(fixtureJson(`series/${id}/daily.json`), 'daily.json').sensor_id).toBe(id);
      expect(parseEventsFile(fixtureJson(`events/${id}.json`), 'events.json').sensor_id).toBe(id);
      for (const month of sensor.raw_months) {
        const file = parseRawMonthFile(fixtureJson(`series/${id}/raw/${month}.json`), month);
        expect(file.t.length).toBeGreaterThan(0);
      }
    }
  });

  it('contains the deployment event of the office sensor', () => {
    const events = parseEventsFile(fixtureJson('events/77799986.json'), 'events.json');
    expect(events.events.map((event) => event.type)).toEqual(['deployment']);
  });
});

describe('contract validation errors', () => {
  it('rejects an unsupported schema version and names file and path', () => {
    const manifest = { ...(fixtureJson('manifest.json') as object), schema_version: 2 };
    expect(() => parseManifest(manifest)).toThrow(
      'manifest.json: $.schema_version must be one of [1], got 2',
    );
  });

  it('reports a wrongly typed nested value with its JSON path', () => {
    const latest = { generated_at: 'x', sensors: { [SENSOR]: { t: 1, temp_c: '12', rh_pct: null, qc: 0, stale: false } } };
    expect(() => parseLatestFile(latest)).toThrow(`latest.json: $.sensors.${SENSOR}.temp_c must be a finite number, got "12"`);
  });

  it('rejects a column whose length differs from t', () => {
    expect(() => parseRawMonthFile(rawFile({ rh_pct: [90] }), 'raw.json')).toThrow(
      'raw.json: $.rh_pct must have 2 items like "t", got 1',
    );
  });

  it('rejects times that do not strictly increase', () => {
    expect(() => parseRawMonthFile(rawFile({ t: [200, 200] }), 'raw.json')).toThrow(
      'raw.json: $.t[1] must be greater than the previous time 200',
    );
  });

  it('rejects a missing field and a non-object root', () => {
    expect(() => parseRawMonthFile(rawFile({ qc: undefined }), 'raw.json')).toThrow('$.qc must be an array, got nothing (field is missing)');
    expect(() => parseRawMonthFile([], 'raw.json')).toThrow('raw.json: $ must be an object');
  });

  it('throws ContractError instances carrying file and path', () => {
    try {
      parseEventsFile({ sensor_id: SENSOR, events: [{ type: 'moved', t: 1, source: 'detected' }] }, 'events.json');
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(ContractError);
      expect((error as ContractError).path).toBe('$.events[0].type');
      expect((error as ContractError).file).toBe('events.json');
    }
  });

  it('rejects a bad daily date, a bad month key and a non-integer time', () => {
    const daily = fixtureJson('series/77678271/daily.json') as Record<string, unknown[]>;
    const badDaily = { ...daily, date: ['1.6.2026', ...(daily.date ?? []).slice(1)] };
    expect(() => parseDailyFile(badDaily, 'daily.json')).toThrow('$.date[0] must be a date YYYY-MM-DD, got "1.6.2026"');
    const manifest = fixtureJson('manifest.json') as { sensors: Record<string, object> };
    const badMonths = { ...manifest, sensors: { [SENSOR]: { first_t: 1, last_t: 2, raw_months: ['2026-13'] } } };
    expect(() => parseManifest(badMonths)).toThrow(`$.sensors.${SENSOR}.raw_months[0] must be a month YYYY-MM, got "2026-13"`);
    expect(() => parseRawMonthFile(rawFile({ t: [100.5, 200] }), 'raw.json')).toThrow('$.t[0] must be an integer, got 100.5');
  });

  it('rejects a registry that is not a FeatureCollection of points', () => {
    expect(() => parseSensorsGeoJSON({ type: 'Feature', features: [] })).toThrow('$.type must be one of ["FeatureCollection"]');
    const bad = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [16.6] }, properties: {} }] };
    expect(() => parseSensorsGeoJSON(bad)).toThrow('$.features[0].geometry.coordinates must be [lon, lat]');
  });

  it('accepts null and missing optional values', () => {
    const events = parseEventsFile({ sensor_id: SENSOR, events: [{ type: 'retrieval', t: 5, source: 'registry' }] }, 'e.json');
    expect(events.events[0]).toEqual({ type: 'retrieval', t: 5, source: 'registry', confidence: null, detail: null });
    const indices = parseIndicesFile(
      { season: 2026, computed_at: 'x', sensors: { [SENSOR]: { gst: { value: null, unit: '°C', coverage: 0.5, complete: false } } } },
      'i.json',
    );
    expect(indices.sensors[SENSOR]?.gst?.class).toBeNull();
    expect(() => parseLatestFile({ generated_at: 'x', sensors: { a: { t: 1, temp_c: 1, rh_pct: 1, qc: 0, stale: 'no' } } })).toThrow(
      '$.sensors.a.stale must be true or false',
    );
  });
});
