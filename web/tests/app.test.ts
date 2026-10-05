import { describe, expect, it } from 'vitest';
import { ChartDataLoader } from '../src/app/ChartDataLoader';
import { ChartPresenter, type ChartView } from '../src/app/ChartPresenter';
import type { ChartData } from '../src/app/ChartDataLoader';
import { SensorCatalog } from '../src/app/SensorCatalog';
import { parseLatestFile, parseManifest, parseSensorsGeoJSON } from '../src/contract';
import { DataClient } from '../src/data/DataClient';
import { DISPLAY_EXCLUDE_MASK, QcMask } from '../src/domain/QcFlags';
import { Resampler } from '../src/domain/Resampler';
import { ResolutionPolicy } from '../src/domain/ResolutionPolicy';
import { TimeWindow } from '../src/domain/TimeWindow';
import { TimeWindowFactory } from '../src/domain/TimeWindowFactory';
import { TimeZone } from '../src/domain/TimeZone';
import { cs } from '../src/i18n/cs';
import { de } from '../src/i18n/de';
import { en } from '../src/i18n/en';
import { I18n } from '../src/i18n/I18n';
import { DEFAULT_APP_STATE } from '../src/state/AppState';
import { fakeFetcher, fixtureExists, fixtureJson, utc } from './helpers';

const BASE = 'data/';
const zone = new TimeZone('Europe/Prague');

function fixtureFetcher() {
  return fakeFetcher(BASE, new Proxy({}, {
    has: (_, path: string) => fixtureExists(path),
    get: (_, path: string) => fixtureJson(path),
  }));
}

class Warnings {
  readonly messages: string[] = [];
  warn(message: string): void {
    this.messages.push(message);
  }
}

function loader(warnings = new Warnings(), client = new DataClient(BASE, fixtureFetcher().fetcher)): ChartDataLoader {
  return new ChartDataLoader(client, new Resampler(new QcMask(DISPLAY_EXCLUDE_MASK)), zone, warnings);
}

describe('SensorCatalog', () => {
  const catalog = SensorCatalog.build(
    parseSensorsGeoJSON(fixtureJson('sensors.geojson')),
    parseManifest(fixtureJson('manifest.json')),
    parseLatestFile(fixtureJson('latest.json')),
  );

  it('joins registry, manifest and latest values in registry order', () => {
    expect(catalog.sensors.map((s) => s.id)).toEqual(['77678271', '77680921', '77800065', '77799986']);
    const sensor = catalog.get('77680921');
    expect(sensor?.elevation_m).toBe(201.6);
    expect(sensor?.lat).toBe(48.879593);
    expect(sensor?.hasData).toBe(true);
    expect(catalog.get('77800065')?.latest?.stale).toBe(true);
    expect(catalog.get('77799986')?.placedSince).toBe('2026-06-03T08:00:00Z');
  });

  it('drops unknown ids', () => {
    expect(catalog.knownIds(['00000000', '77678271'])).toEqual(['77678271']);
  });
});

describe('ChartDataLoader', () => {
  it('loads raw samples and in-window events for the office sensor', async () => {
    const window = new TimeWindow(utc(2026, 6, 2), utc(2026, 6, 5), 'raw');
    const data = await loader().load(['77799986'], window);
    const sensor = data.sensors[0];
    expect(sensor?.events.map((e) => e.type)).toEqual(['deployment']);
    // Office samples before the deployment carry PRE_DEPLOYMENT and are hidden (null).
    const firstValid = sensor?.temp_c.values.findIndex((value) => value !== null) ?? -1;
    expect(sensor?.temp_c.t[firstValid]).toBeGreaterThanOrEqual(sensor?.events[0]?.t ?? Infinity);
  });

  it('produces one hourly mean per hour of the window', async () => {
    const window = new TimeWindow(utc(2026, 7, 1), utc(2026, 7, 2), 'hourly');
    const data = await loader().load(['77678271', '77680921'], window);
    expect(data.sensors.map((s) => s.temp_c.length)).toEqual([24, 24]);
    expect(data.sensors[0]?.rh_pct.t[0]).toBe(utc(2026, 7, 1, 0, 30));
  });

  it('shows the 7-hour gap of 14 Jul 2026 as empty hours', async () => {
    const window = new TimeWindow(utc(2026, 7, 14, 9), utc(2026, 7, 14, 16), 'hourly');
    const data = await loader().load(['77680921'], window);
    expect(data.sensors[0]?.temp_c.validCount).toBe(0);
  });

  it('reads daily means from daily.json', async () => {
    const window = new TimeWindow(utc(2026, 7, 31, 22), utc(2026, 8, 3, 22), 'daily');
    const data = await loader().load(['77678271'], window);
    const daily = fixtureJson('series/77678271/daily.json') as { date: string[]; temp_mean: number[] };
    const index = daily.date.indexOf('2026-08-01');
    expect(data.sensors[0]?.temp_c.t).toEqual([utc(2026, 7, 31, 22), utc(2026, 8, 1, 22), utc(2026, 8, 2, 22)]);
    expect(data.sensors[0]?.temp_c.values[0]).toBe(daily.temp_mean[index]);
  });
});

describe('ChartDataLoader failure handling', () => {
  it('reports a failing sensor and still returns the others', async () => {
    const window = new TimeWindow(utc(2026, 7, 1), utc(2026, 7, 2), 'raw');
    const data = await loader().load(['77678271', '00000000'], window);
    expect(data.sensors.map((s) => s.sensorId)).toEqual(['77678271']);
    expect(data.failures).toEqual([{ sensorId: '00000000', message: 'Sensor 00000000 is not listed in manifest.json' }]);
  });

  it('treats a missing or invalid events file as no events and warns', async () => {
    const { fetcher } = fakeFetcher(BASE, new Proxy({}, {
      has: (_, path: string) => path !== 'events/77678271.json' && fixtureExists(path),
      get: (_, path: string) =>
        path === 'events/77680921.json' ? { sensor_id: '77680921', events: [{ type: 'moved', t: 1, source: 'x' }] } : fixtureJson(path),
    }));
    const warnings = new Warnings();
    const window = new TimeWindow(utc(2026, 8, 22), utc(2026, 8, 23), 'raw');
    const data = await loader(warnings, new DataClient(BASE, fetcher)).load(['77678271', '77680921'], window);
    expect(data.failures).toEqual([]);
    expect(data.sensors.map((s) => s.events.length)).toEqual([0, 0]);
    expect(data.sensors.every((s) => s.temp_c.validCount > 0)).toBe(true);
    expect(warnings.messages).toEqual([
      'Events of sensor 77678271 ignored: Cannot load data/events/77678271.json: HTTP 404',
      'Events of sensor 77680921 ignored: events/77680921.json: $.events[0].type must be one of ["deployment","retrieval","step"], got "moved"',
    ]);
  });
});

describe('ChartPresenter', () => {
  class RecordingView implements ChartView {
    readonly messages: string[] = [];
    readonly shown: ChartData[] = [];
    readonly errors: string[] = [];
    showMessage(text: string): void {
      this.messages.push(text);
    }
    showError(text: string): void {
      this.errors.push(text);
    }
    showData(data: ChartData): void {
      this.shown.push(data);
    }
  }

  const i18n = new I18n({ cs, de, en }, 'en');
  const factory = new TimeWindowFactory(zone, new ResolutionPolicy());
  const anchor = utc(2026, 9, 30, 21, 34);

  it('shows loading, then data for the requested window', async () => {
    const view = new RecordingView();
    const presenter = new ChartPresenter(loader(), factory, i18n, view, anchor);
    await presenter.refresh({ ...DEFAULT_APP_STATE, window: { kind: '24h' } }, ['77678271']);
    expect(view.messages).toEqual(['Loading data…']);
    expect(view.shown[0]?.window.endT).toBe(utc(2026, 9, 30, 22));
  });

  it('passes per-sensor failures to the view', async () => {
    const view = new RecordingView();
    const presenter = new ChartPresenter(loader(), factory, i18n, view, anchor);
    await presenter.refresh(DEFAULT_APP_STATE, ['00000000']);
    expect(view.shown[0]?.failures.map((f) => f.sensorId)).toEqual(['00000000']);
  });

  it('shows an error when the whole load fails', async () => {
    const view = new RecordingView();
    const broken = new DataClient(BASE, () => Promise.reject(new Error('offline')));
    const presenter = new ChartPresenter(loader(new Warnings(), broken), factory, i18n, view, anchor);
    await presenter.refresh(DEFAULT_APP_STATE, ['77678271']);
    expect(view.shown[0]?.failures[0]?.message).toBe('Cannot load data/manifest.json: offline');
  });

  it('falls back to the default window when the spec cannot be resolved', () => {
    const presenter = new ChartPresenter(loader(), factory, i18n, new RecordingView(), anchor);
    const window = presenter.windowFor({ ...DEFAULT_APP_STATE, window: { kind: 'custom', from: '2026-13-45', to: '2026-06-01' } });
    expect([window.startT, window.endT]).toEqual([utc(2026, 9, 23, 22), utc(2026, 9, 30, 22)]);
  });

  it('rethrows unexpected errors from the window factory', () => {
    const failing = { create: () => { throw new TypeError('bug'); } } as unknown as TimeWindowFactory;
    const presenter = new ChartPresenter(loader(), failing, i18n, new RecordingView(), anchor);
    expect(() => presenter.windowFor(DEFAULT_APP_STATE)).toThrow('bug');
  });

  it('shows an error message when the loader itself rejects', async () => {
    const view = new RecordingView();
    const rejecting = { load: () => Promise.reject(new Error('boom')) } as unknown as ChartDataLoader;
    await new ChartPresenter(rejecting, factory, i18n, view, anchor).refresh(DEFAULT_APP_STATE, ['77678271']);
    expect(view.errors).toEqual(['Could not load data: boom']);
  });

  it('drops a response superseded by a newer request and ignores an empty selection', async () => {
    const view = new RecordingView();
    const presenter = new ChartPresenter(loader(), factory, i18n, view, anchor);
    const first = presenter.refresh(DEFAULT_APP_STATE, ['77678271']);
    const second = presenter.refresh({ ...DEFAULT_APP_STATE, window: { kind: '24h' } }, ['77680921']);
    await Promise.all([first, second]);
    expect(view.shown.map((data) => data.sensors[0]?.sensorId)).toEqual(['77680921']);
    await presenter.refresh(DEFAULT_APP_STATE, []);
    expect(view.shown).toHaveLength(1);
  });
});
