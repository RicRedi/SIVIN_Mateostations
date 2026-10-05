import './styles.css';
import { ChartDataLoader } from './app/ChartDataLoader';
import { ChartPresenter } from './app/ChartPresenter';
import { SensorCatalog } from './app/SensorCatalog';
import type { Manifest } from './contract';
import { DataClient } from './data/DataClient';
import { DISPLAY_EXCLUDE_MASK, QcMask } from './domain/QcFlags';
import { Resampler } from './domain/Resampler';
import { ResolutionPolicy } from './domain/ResolutionPolicy';
import { TimeWindowFactory } from './domain/TimeWindowFactory';
import { TimeZone } from './domain/TimeZone';
import { MS_PER_SECOND } from './domain/units';
import { cs } from './i18n/cs';
import { de } from './i18n/de';
import { en } from './i18n/en';
import { I18n } from './i18n/I18n';
import { LanguagePreference } from './i18n/LanguagePreference';
import { DEFAULT_APP_STATE, type AppState } from './state/AppState';
import { HashStateCodec } from './state/HashStateCodec';
import { Store } from './state/Store';
import { App } from './ui/App';
import { HashSync } from './ui/HashSync';
import { HeaderView } from './ui/HeaderView';
import { MapView } from './ui/MapView';
import { TemperatureScale } from './ui/palette';
import { SensorColors } from './ui/SensorColors';
import { SensorList } from './ui/SensorList';
import { SensorPanel } from './ui/SensorPanel';
import { SeriesChart } from './ui/SeriesChart';
import { TimeWindowControl } from './ui/TimeWindowControl';

/** Data directory, relative to the deployed base path (see `vite.config.ts`). */
const DATA_BASE_URL = `${import.meta.env.BASE_URL}data/`;
/** Build-time flag: the bundled data are the synthetic fixture unless set to `"false"`. */
const IS_DEMO_DATA = import.meta.env.VITE_DEMO_DATA !== 'false';
/** Below this viewport width the map legend starts collapsed so it does not cover the map. */
const COMPACT_LEGEND_QUERY = '(max-width: 600px)';

function requireElement(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`index.html is missing #${id}`);
  }
  return element;
}

/** End of the available data: the latest `last_t` of any sensor, else `generated_at`. */
function dataEndT(manifest: Manifest): number {
  const lastTimes = Object.values(manifest.sensors).map((sensor) => sensor.last_t);
  return lastTimes.length > 0 ? Math.max(...lastTimes) : Date.parse(manifest.generated_at) / MS_PER_SECOND;
}

async function start(): Promise<void> {
  const client = new DataClient(DATA_BASE_URL, (url) => fetch(url));
  const preference = new LanguagePreference(() => window.localStorage);
  const codec = new HashStateCodec();
  const initial: AppState = {
    ...DEFAULT_APP_STATE,
    language: preference.load() ?? DEFAULT_APP_STATE.language,
    ...codec.decode(window.location.hash),
  };
  const i18n = new I18n({ cs, de, en }, initial.language);
  const store = new Store<AppState>(initial);
  let app: App | null = null;
  const header = new HeaderView(requireElement('header'), i18n, IS_DEMO_DATA, (language) => app?.onLanguage(language));
  const status = requireElement('status');
  status.textContent = i18n.t('loading');

  const [manifest, registry, latest] = await Promise.all([client.getManifest(), client.getSensors(), client.getLatest()]);
  status.hidden = true;
  const zone = new TimeZone(manifest.display_timezone);
  const catalog = SensorCatalog.build(registry, manifest, latest);
  store.update({ selectedSensorIds: catalog.knownIds(store.state.selectedSensorIds) });

  const factory = new TimeWindowFactory(zone, new ResolutionPolicy());
  const colors = new SensorColors();
  const panel = new SensorPanel(requireElement('panel'), i18n, zone.name, colors, () => {
    map.invalidateSize();
  });
  const chart = new SeriesChart(panel.chartSlot, i18n, catalog, colors, manifest.variables, zone);
  const loader = new ChartDataLoader(client, new Resampler(new QcMask(DISPLAY_EXCLUDE_MASK)), zone, console);
  const presenter = new ChartPresenter(loader, factory, i18n, chart, dataEndT(manifest));
  const legendCollapsed = window.matchMedia(COMPACT_LEGEND_QUERY).matches;
  const map = new MapView(requireElement('map'), catalog, i18n, new TemperatureScale(), zone.name, legendCollapsed, (id, compare) =>
    app?.onSensorClick(id, compare),
  );
  const list = new SensorList(panel.listSlot, catalog, i18n, colors, (id) => app?.onSensorToggle(id));
  const windowControl = new TimeWindowControl(panel.windowSlot, i18n, zone, manifest.seasons, (change) =>
    app?.onWindowChange(change),
  );
  app = new App(store, catalog, i18n, preference, colors, presenter, { header, map, panel, list, windowControl, chart });
  new HashSync(store, codec, window.location, window.history, window).write();
  app.start();
}

start().catch((error: unknown) => {
  const status = document.getElementById('status');
  if (status !== null) {
    status.hidden = false;
    status.textContent = error instanceof Error ? error.message : String(error);
  }
});
