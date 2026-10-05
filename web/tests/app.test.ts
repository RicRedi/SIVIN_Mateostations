import { describe, expect, it } from 'vitest';
import { ChartDataLoader } from '../src/app/ChartDataLoader';
import { ChartPresenter, type ChartView } from '../src/app/ChartPresenter';
import type { ChartData } from '../src/app/ChartDataLoader';
import { SensorCatalog } from '../src/app/SensorCatalog';
import { parseLatestFile, parseManifest, parseSensorsGeoJSON } from '../src/contract';
import { DataClient } from '../src/data/DataClient';
import { QcMask } from '../src/domain/QcFlags';
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

function loader(): ChartDataLoader {
  return new ChartDataLoader(new DataClient(BASE, fixtureFetcher().fetcher), new Resampler(new QcMask()), zone);
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
    expect(sensor?.colorIndex).toBe(1);
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
    expect(data.sensors[0]?.rh_pct.t[0]).toBe(utc(2026, 7, 1));
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

  it('shows an error message when loading fails', async () => {
    const view = new RecordingView();
    const presenter = new ChartPresenter(loader(), factory, i18n, view, anchor);
    await presenter.refresh(DEFAULT_APP_STATE, ['00000000']);
    // Raw data and events load in parallel; whichever fails first is reported.
    expect(view.errors.at(-1)).toMatch(/^Could not load data: .*00000000/);
    expect(view.shown).toHaveLength(0);
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
