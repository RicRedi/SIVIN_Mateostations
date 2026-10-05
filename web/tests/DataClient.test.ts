import { describe, expect, it } from 'vitest';
import { DataClient } from '../src/data/DataClient';
import { DataLoadError } from '../src/data/DataLoadError';
import { utcMonthKeys } from '../src/data/monthKeys';
import { fakeFetcher, utc } from './helpers';

const BASE = '/SIVIN_Mateostations/data/';
const ID = '11111111';

const manifest = {
  schema_version: 1,
  generated_at: '2026-10-01T00:00:00Z',
  display_timezone: 'Europe/Prague',
  variables: [],
  sensors: { [ID]: { first_t: utc(2026, 6, 30, 23), last_t: utc(2026, 9, 1), raw_months: ['2026-06', '2026-07', '2026-09'] } },
  seasons: [2026],
  indices: [],
};

const june = {
  sensor_id: ID,
  t: [utc(2026, 6, 30, 23, 0), utc(2026, 6, 30, 23, 30)],
  temp_c: [10, 11],
  rh_pct: [80, null],
  qc: [0, 1],
};
const july = {
  sensor_id: ID,
  t: [utc(2026, 7, 1, 0, 0), utc(2026, 7, 1, 0, 30)],
  temp_c: [12, 13],
  rh_pct: [82, 83],
  qc: [0, 0],
};

function client(extra: Record<string, unknown> = {}) {
  const { fetcher, requested } = fakeFetcher(BASE, {
    'manifest.json': manifest,
    [`series/${ID}/raw/2026-06.json`]: june,
    [`series/${ID}/raw/2026-07.json`]: july,
    ...extra,
  });
  return { client: new DataClient(BASE, fetcher), requested };
}

describe('utcMonthKeys', () => {
  it('lists the UTC months overlapping a half-open window', () => {
    expect(utcMonthKeys(utc(2026, 6, 30, 23), utc(2026, 7, 1, 1))).toEqual(['2026-06', '2026-07']);
    expect(utcMonthKeys(utc(2026, 6, 1), utc(2026, 7, 1))).toEqual(['2026-06']);
    expect(utcMonthKeys(utc(2025, 11, 15), utc(2026, 2, 2))).toEqual(['2025-11', '2025-12', '2026-01', '2026-02']);
    expect(utcMonthKeys(utc(2026, 6, 1), utc(2026, 6, 1))).toEqual([]);
  });
});

describe('DataClient.getRawRange', () => {
  it('fetches both months of a window crossing a month boundary and merges them', async () => {
    const { client: data, requested } = client();
    const series = await data.getRawRange(ID, utc(2026, 6, 30, 23, 15), utc(2026, 7, 1, 0, 15));
    expect(requested).toEqual([
      `${BASE}manifest.json`,
      `${BASE}series/${ID}/raw/2026-06.json`,
      `${BASE}series/${ID}/raw/2026-07.json`,
    ]);
    expect(series.t).toEqual([utc(2026, 6, 30, 23, 30), utc(2026, 7, 1, 0, 0)]);
    expect(series.temp_c).toEqual([11, 12]);
    expect(series.rh_pct).toEqual([null, 82]);
    expect(series.qc).toEqual([1, 0]);
  });

  it('fetches a single month for a window inside it', async () => {
    const { client: data } = client();
    expect(await data.rawMonthsFor(ID, utc(2026, 7, 1), utc(2026, 7, 8))).toEqual(['2026-07']);
  });

  it('skips months that the manifest does not list and returns an empty series outside the data', async () => {
    const { client: data, requested } = client();
    const august = await data.getRawRange(ID, utc(2026, 8, 1), utc(2026, 8, 31));
    const earlier = await data.getRawRange(ID, utc(2025, 1, 1), utc(2025, 2, 1));
    expect(august.length).toBe(0);
    expect(earlier.length).toBe(0);
    expect(requested).toEqual([`${BASE}manifest.json`]);
  });

  it('fails when a month listed in the manifest is missing', async () => {
    const { client: data } = client();
    const pending = data.getRawRange(ID, utc(2026, 9, 1), utc(2026, 9, 2));
    await expect(pending).rejects.toBeInstanceOf(DataLoadError);
    await expect(pending).rejects.toThrow(`Cannot load ${BASE}series/${ID}/raw/2026-09.json: HTTP 404`);
  });

  it('fails for a sensor that the manifest does not know', async () => {
    const { client: data } = client();
    await expect(data.getRawRange('99999999', 0, 1)).rejects.toThrow('Sensor 99999999 is not listed in manifest.json');
  });

  it('rejects a month file that belongs to another sensor', async () => {
    const { client: data } = client({ [`series/${ID}/raw/2026-07.json`]: { ...july, sensor_id: '22222222' } });
    await expect(data.getRawRange(ID, utc(2026, 7, 1), utc(2026, 7, 2))).rejects.toThrow('contains sensor 22222222, expected 11111111');
  });

  it('caches every file and does not refetch on a second call', async () => {
    const { client: data, requested } = client();
    await data.getRawRange(ID, utc(2026, 6, 30), utc(2026, 7, 2));
    await data.getRawRange(ID, utc(2026, 6, 30), utc(2026, 7, 2));
    expect(requested).toHaveLength(3);
  });
});

describe('DataClient file loading', () => {
  it('builds URLs for every contract file', async () => {
    const files = {
      'latest.json': { generated_at: 'x', sensors: {} },
      'sensors.geojson': { type: 'FeatureCollection', features: [] },
      [`series/${ID}/daily.json`]: { sensor_id: ID, date: [], temp_min: [], temp_mean: [], temp_max: [], rh_min: [], rh_mean: [], rh_max: [], coverage: [] },
      [`events/${ID}.json`]: { sensor_id: ID, events: [] },
      'indices/2026.json': { season: 2026, computed_at: 'x', sensors: {} },
    };
    const { client: data } = client(files);
    expect((await data.getLatest()).sensors).toEqual({});
    expect((await data.getSensors()).features).toEqual([]);
    expect((await data.getDaily(ID)).date).toEqual([]);
    expect((await data.getEvents(ID)).events).toEqual([]);
    expect((await data.getIndices(2026)).season).toBe(2026);
  });

  it('reports network errors and invalid JSON as DataLoadError, and retries after a failure', async () => {
    let attempt = 0;
    const data = new DataClient(BASE, () => {
      attempt += 1;
      if (attempt === 1) {
        return Promise.reject(new Error('offline'));
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new SyntaxError('bad')) });
    });
    await expect(data.getManifest()).rejects.toThrow(`Cannot load ${BASE}manifest.json: offline`);
    await expect(data.getManifest()).rejects.toThrow('response is not valid JSON');
    expect(attempt).toBe(2);
  });
});
