import { describe, expect, it, vi } from 'vitest';
import {
  eventInWindow,
  isMarkedIntervalEvent,
  isOffSiteEvent,
  parseDailyFile,
  parseEventsFile,
  parseIndicesFile,
  parseManifest,
} from '../src/contract';

// Contract additions and tolerances of WP-3.2 (SiteBuilder). All values are synthetic.

const SENSOR = '77799986';

function collect(): { warnings: string[]; warn: (message: string) => void } {
  const warnings: string[] = [];
  return { warnings, warn: (message) => warnings.push(message) };
}

describe('event types', () => {
  it('skips an event of an unknown type with a warning and keeps the others', () => {
    const { warnings, warn } = collect();
    const file = parseEventsFile(
      {
        sensor_id: SENSOR,
        events: [
          { type: 'gap', t: 50, t_end: 90, source: 'detected' },
          { type: 'step', t: 100, source: 'detected', confidence: null, detail: 'temp_c level step +5.0 °C' },
        ],
      },
      'e.json',
      warn,
    );
    expect(file.events).toEqual([
      { type: 'step', t: 100, source: 'detected', confidence: null, detail: 'temp_c level step +5.0 °C' },
    ]);
    expect(warnings).toEqual(['e.json: $.events[0] skipped: unknown event type "gap"']);
  });

  it('warns about unknown types on the console by default', () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(parseEventsFile({ sensor_id: SENSOR, events: [{ type: 'new_kind', t: 1 }] }, 'e.json').events).toEqual([]);
    expect(spy).toHaveBeenCalledWith('e.json: $.events[0] skipped: unknown event type "new_kind"');
    spy.mockRestore();
  });

  it('reads low_battery and unlogged_off_site as marked intervals', () => {
    const file = parseEventsFile(
      {
        sensor_id: SENSOR,
        events: [
          { type: 'low_battery', t: 100, t_end: 100, source: 'detected', confidence: null, detail: 'low battery: 1 reading(s) below 3.3 V' },
          { type: 'unlogged_off_site', t: 200, t_end: 900, source: 'detected', confidence: 0.88, detail: null },
        ],
      },
      'e.json',
    );
    const [battery, unlogged] = file.events;
    expect(battery).toEqual({
      type: 'low_battery',
      t: 100,
      t_end: 100,
      source: 'detected',
      confidence: null,
      detail: 'low battery: 1 reading(s) below 3.3 V',
    });
    expect(unlogged?.type).toBe('unlogged_off_site');
    if (battery === undefined || unlogged === undefined) {
      throw new Error('events missing');
    }
    expect([isMarkedIntervalEvent(battery), isOffSiteEvent(battery)]).toEqual([true, false]);
    // A marked interval belongs to the windows that contain its marker time t.
    expect([eventInWindow(unlogged, 200, 201), eventInWindow(unlogged, 300, 1000)]).toEqual([true, false]);
  });

  it('requires a valid t_end on marked intervals', () => {
    const parse = (event: Record<string, unknown>) => () => parseEventsFile({ sensor_id: SENSOR, events: [event] }, 'e.json');
    expect(parse({ type: 'low_battery', t: 100, source: 'detected' })).toThrow('$.events[0].t_end must be a finite number');
    expect(parse({ type: 'low_battery', t: 100, t_end: 99, source: 'detected' })).toThrow(
      '$.events[0].t_end must not be before t (100), got 99',
    );
  });
});

describe('optional fields written by the SiteBuilder', () => {
  const manifest = (status: unknown) => ({
    schema_version: 1,
    generated_at: '2026-10-05T04:00:00Z',
    display_timezone: 'Europe/Prague',
    variables: [],
    sensors: { [SENSOR]: { first_t: 1, last_t: 2, raw_months: ['2026-01'], status } },
    seasons: [],
    indices: [],
  });

  it('reads the sensor status of the manifest', () => {
    expect(parseManifest(manifest('retired')).sensors[SENSOR]?.status).toBe('retired');
    expect('status' in (parseManifest(manifest(undefined)).sensors[SENSOR] ?? {})).toBe(false);
  });

  it('ignores a malformed status with a warning', () => {
    const { warnings, warn } = collect();
    const sensor = parseManifest(manifest(3), 'manifest.json', warn).sensors[SENSOR];
    expect(sensor?.status).toBeUndefined();
    expect(sensor?.raw_months).toEqual(['2026-01']);
    expect(warnings).toEqual(['manifest.json: $.sensors.77799986.status must be a string, got 3; optional field ignored']);
  });

  it('reads the estimated flag of an index result', () => {
    const indices = (estimated: unknown) => ({
      season: 2026,
      computed_at: '2026-10-05T04:00:00Z',
      sensors: { [SENSOR]: { botrytis_broome: { value: 0.07, unit: '1', coverage: 0.019, complete: false, class: null, estimated } } },
    });
    expect(parseIndicesFile(indices(true), 'i.json').sensors[SENSOR]?.botrytis_broome?.estimated).toBe(true);
    const { warnings, warn } = collect();
    expect(parseIndicesFile(indices('yes'), 'i.json', warn).sensors[SENSOR]?.botrytis_broome?.estimated).toBeUndefined();
    expect(warnings).toEqual([
      'i.json: $.sensors.77799986.botrytis_broome.estimated must be true or false, got "yes"; optional field ignored',
    ]);
    expect(parseIndicesFile(indices(undefined), 'i.json').sensors[SENSOR]?.botrytis_broome?.estimated).toBeUndefined();
  });

  it('reads precip_n_samples of the daily file', () => {
    const daily = parseDailyFile(
      {
        sensor_id: SENSOR,
        date: ['2026-01-01'],
        temp_min: [1],
        temp_mean: [2],
        temp_max: [3],
        rh_min: [70],
        rh_mean: [80],
        rh_max: [90],
        coverage: [1],
        precip_sum_mm: [0.4],
        precip_n_samples: [47],
      },
      'daily.json',
    );
    expect(daily.precip_n_samples).toEqual([47]);
  });
});
