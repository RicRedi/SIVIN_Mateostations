// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import type { ChartController } from '../../src/app/ChartPresenter';
import { SensorCatalog, type SensorInfo } from '../../src/app/SensorCatalog';
import { parseLatestFile, parseManifest, parseSensorsGeoJSON } from '../../src/contract';
import { TimeWindow } from '../../src/domain/TimeWindow';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { LanguagePreference } from '../../src/i18n/LanguagePreference';
import { DEFAULT_APP_STATE, type AppState } from '../../src/state/AppState';
import { HashStateCodec } from '../../src/state/HashStateCodec';
import { Store } from '../../src/state/Store';
import { App, type AppViews } from '../../src/ui/App';
import { HashSync } from '../../src/ui/HashSync';
import { SensorColors } from '../../src/ui/SensorColors';
import { fixtureJson } from '../helpers';

const catalog = SensorCatalog.build(
  parseSensorsGeoJSON(fixtureJson('sensors.geojson')),
  parseManifest(fixtureJson('manifest.json')),
  parseLatestFile(fixtureJson('latest.json')),
);
const WINDOW = new TimeWindow(0, 3600, 'raw');

class FakePresenter implements ChartController {
  readonly refreshed: (readonly string[])[] = [];
  windowFor(): TimeWindow {
    return WINDOW;
  }
  refresh(_: AppState, sensorIds: readonly string[]): Promise<void> {
    this.refreshed.push(sensorIds);
    return Promise.resolve();
  }
}

function fakeViews() {
  const log = { map: [] as (readonly string[])[], panel: [] as [string[], boolean][], header: 0, chart: 0, fitted: 0 };
  const views: AppViews = {
    header: { render: () => { log.header += 1; } },
    map: { render: (ids) => { log.map.push(ids); }, invalidateSize: () => undefined, fitToSensors: () => { log.fitted += 1; } },
    panel: { render: (selected: readonly SensorInfo[], limit) => { log.panel.push([selected.map((s) => s.id), limit]); } },
    list: { render: () => undefined },
    windowControl: { render: () => undefined },
    chart: { render: () => { log.chart += 1; } },
  };
  return { views, log };
}

describe('App', () => {
  let store: Store<AppState>;
  let presenter: FakePresenter;
  let colors: SensorColors;
  let log: ReturnType<typeof fakeViews>['log'];
  let app: App;
  let storage: Map<string, string>;
  let hashChanges: EventTarget;

  /** Set the hash without jsdom's asynchronous hashchange, then dispatch one synchronously. */
  function navigate(hash: string): void {
    window.history.replaceState(null, '', hash);
    hashChanges.dispatchEvent(new Event('hashchange'));
  }

  beforeEach(() => {
    window.history.replaceState(null, '', '#');
    storage = new Map<string, string>();
    hashChanges = new EventTarget();
    store = new Store<AppState>(DEFAULT_APP_STATE);
    presenter = new FakePresenter();
    colors = new SensorColors();
    const fake = fakeViews();
    log = fake.log;
    const preference = new LanguagePreference(() => ({ getItem: (k: string) => storage.get(k) ?? null, setItem: (k: string, v: string) => storage.set(k, v) }) as unknown as Storage);
    app = new App(store, catalog, new I18n({ cs, de, en }, 'cs'), preference, colors, presenter, fake.views);
    new HashSync(store, new HashStateCodec(), window.location, window.history, hashChanges).write();
    app.start();
  });

  it('renders and loads once on start', () => {
    expect(log.fitted).toBe(1);
    expect(presenter.refreshed).toEqual([[]]);
  });

  it('selects on click, compares on ctrl-click and colours by selection order', () => {
    app.onSensorClick('77799986', false);
    app.onSensorClick('77678271', true);
    expect(store.state.selectedSensorIds).toEqual(['77799986', '77678271']);
    expect(colors.colorFor('77799986')).toBe('#2a78d6');
    expect(presenter.refreshed.at(-1)).toEqual(['77799986', '77678271']);
    app.onSensorToggle('77799986');
    expect(store.state.selectedSensorIds).toEqual(['77678271']);
    app.onSensorClick('77680921', false);
    expect(window.location.hash).toBe('#s=77680921&w=7d&lang=cs');
  });

  it('removes unknown sensor ids from state and URL after a hashchange', () => {
    navigate('#s=77678271,12345678&w=24h&lang=cs');
    expect(store.state.selectedSensorIds).toEqual(['77678271']);
    expect(window.location.hash).toBe('#s=77678271&w=24h&lang=cs');
  });

  it('applies a language change that arrives together with an unknown sensor id', () => {
    navigate('#s=77678271,12345678&w=7d&lang=de');
    expect(store.state.language).toBe('de');
    expect(store.state.selectedSensorIds).toEqual(['77678271']);
    expect(log.header).toBe(1);
    expect(storage.get('sivin.language')).toBe('de');
    expect(window.location.hash).toBe('#s=77678271&w=7d&lang=de');
  });

  it('switches language, saves it and re-renders header and chart', () => {
    app.onLanguage('de');
    expect(log.header).toBe(1);
    expect(log.chart).toBe(1);
    expect(storage.get('sivin.language')).toBe('de');
  });

  it('reloads when the window changes', () => {
    app.onSensorClick('77678271', false);
    const count = presenter.refreshed.length;
    app.onWindowChange({ window: { kind: '30d' } });
    expect(presenter.refreshed.length).toBe(count + 1);
  });
});
