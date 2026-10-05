import { describe, expect, it, vi } from 'vitest';
import {
  ContractError,
  eventInWindow,
  isOffSiteEvent,
  parseDailyFile,
  parseEventsFile,
  parseIndicesFile,
  parseLatestFile,
  parseManifest,
  parseRawMonthFile,
  parseSensorsGeoJSON,
} from '../src/contract';
import { OFF_SITE_DETAIL, OFF_SITE_END, OFF_SITE_START, fixtureJson } from './helpers';

const SENSOR = '77678271';

function rawFile(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { sensor_id: SENSOR, t: [100, 200], temp_c: [1.2, null], rh_pct: [90, 91], qc: [0, 1], ...overrides };
}

describe('the committed synthetic fixture', () => {
  it('passes validation of every contract file', () => {
    const manifest = parseManifest(fixtureJson('manifest.json'));
    expect(manifest.schema_version).toBe(1);
    expect(manifest.display_timezone).toBe('Europe/Prague');
    expect(Object.keys(manifest.sensors)).toHaveLength(20);
    const registry = parseSensorsGeoJSON(fixtureJson('sensors.geojson'));
    expect(registry.features).toHaveLength(20);
    // Public projection (owner decision 2026-10-05): no internal notes.
    expect(registry.features.every((f) => f.properties.notes === null && f.properties.placements.every((p) => p.note === null))).toBe(true);
    expect(new Set(registry.features.map((f) => f.properties.municipality))).toEqual(new Set(['Obec A', 'Obec B', 'Obec C', null]));
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

  it('contains the off-site period of the service sensor', () => {
    const events = parseEventsFile(fixtureJson('events/77799986.json'), 'events.json');
    expect(events.events).toEqual([
      { type: 'off_site', t: OFF_SITE_START, t_end: OFF_SITE_END, source: 'log', confidence: null, detail: OFF_SITE_DETAIL },
    ]);
  });
});

describe('off_site events (MIGRATION_PLAN §2.8)', () => {
  const parse = (event: Record<string, unknown>) => parseEventsFile({ sensor_id: SENSOR, events: [event] }, 'e.json').events[0];

  it('accepts a closed and an open period', () => {
    const closed = parse({ type: 'off_site', t: 100, t_end: 200, source: 'log', detail: 'office: winter' });
    expect(closed).toEqual({ type: 'off_site', t: 100, t_end: 200, source: 'log', confidence: null, detail: 'office: winter' });
    const open = parse({ type: 'off_site', t: 100, t_end: null, source: 'log' });
    expect(open).toEqual({ type: 'off_site', t: 100, t_end: null, source: 'log', confidence: null, detail: null });
    expect(open !== undefined && isOffSiteEvent(open)).toBe(true);
  });

  it('requires t_end for off_site and checks it', () => {
    expect(() => parse({ type: 'off_site', t: 100, source: 'log' })).toThrow(
      'e.json: $.events[0].t_end is required for "off_site" (a number, or null while still off site)',
    );
    expect(() => parse({ type: 'off_site', t: 100, t_end: 100, source: 'log' })).toThrow(
      '$.events[0].t_end must be greater than t (100), got 100',
    );
    expect(() => parse({ type: 'off_site', t: 100, t_end: 150.5, source: 'log' })).toThrow(
      '$.events[0].t_end must be an integer, got 150.5',
    );
    expect(() => parse({ type: 'off_site', t: 100, t_end: '200', source: 'log' })).toThrow('$.events[0].t_end must be a finite number');
  });

  it('ignores t_end on point events with a warning (tolerant reading)', () => {
    const warnings: string[] = [];
    const file = parseEventsFile(
      { sensor_id: SENSOR, events: [{ type: 'deployment', t: 100, t_end: 200, source: 'detected' }, { type: 'step', t: 300, t_end: null, source: 'detected' }] },
      'e.json',
      (message) => warnings.push(message),
    );
    expect(file.events).toEqual([
      { type: 'deployment', t: 100, source: 'detected', confidence: null, detail: null },
      { type: 'step', t: 300, source: 'detected', confidence: null, detail: null },
    ]);
    expect(warnings).toEqual([
      'e.json: $.events[0].t_end ignored: only interval events have an end, not "deployment"',
      'e.json: $.events[1].t_end ignored: only interval events have an end, not "step"',
    ]);
  });

  it('warns on the console by default', () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    parse({ type: 'step', t: 100, t_end: 200, source: 'detected' });
    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });

  it('tells whether an event belongs to a window', () => {
    const point = parse({ type: 'step', t: 100, source: 'detected' });
    const closed = parse({ type: 'off_site', t: 100, t_end: 200, source: 'log' });
    const open = parse({ type: 'off_site', t: 100, t_end: null, source: 'log' });
    if (point === undefined || closed === undefined || open === undefined) {
      throw new Error('events missing');
    }
    expect([eventInWindow(point, 100, 101), eventInWindow(point, 50, 100), eventInWindow(point, 101, 200)]).toEqual([true, false, false]);
    expect([eventInWindow(closed, 0, 101), eventInWindow(closed, 199, 300), eventInWindow(closed, 200, 300), eventInWindow(closed, 0, 100)]).toEqual([
      true,
      true,
      false,
      false,
    ]);
    expect(eventInWindow(open, 10_000, 20_000)).toBe(true);
    expect(isOffSiteEvent(point)).toBe(false);
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
      parseEventsFile({ sensor_id: SENSOR, events: [{ type: 7, t: 1, source: 'detected' }] }, 'events.json');
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

  it('reads municipality and track, missing ones as null, and ignores an old site key with a warning', () => {
    const properties = {
      id: SENSOR, portal_name: `8615620 ${SENSOR}`, label: 'x', variety: null, status: 'active', notes: null,
      placements: [{ from: '2026-06-01T00:00:00Z', to: null, lon: 16.6, lat: 48.8, elevation_m: null, note: null }],
    };
    const file = (props: object): unknown => ({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [16.6, 48.8] }, properties: props }],
    });
    const warnings: string[] = [];
    const warn = (message: string): void => {
      warnings.push(message);
    };
    const grouped = parseSensorsGeoJSON(file({ ...properties, municipality: 'Obec A', track: 'Trať 1' }), 'sensors.geojson', warn);
    expect(grouped.features[0]?.properties).toMatchObject({ municipality: 'Obec A', track: 'Trať 1' });
    const old = parseSensorsGeoJSON(file({ ...properties, site: 'Old vineyard' }), 'sensors.geojson', warn);
    expect(old.features[0]?.properties).toMatchObject({ municipality: null, track: null });
    expect('site' in (old.features[0]?.properties ?? {})).toBe(false);
    expect(warnings).toEqual([
      'sensors.geojson: $.features[0].properties.site is deprecated (replaced by municipality and track); ignored',
    ]);
    expect(() => parseSensorsGeoJSON(file({ ...properties, track: 7 }), 'sensors.geojson', warn)).toThrow(
      '$.features[0].properties.track must be a string, got 7',
    );
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
