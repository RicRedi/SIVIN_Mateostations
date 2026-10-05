// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { SensorCatalog, type SensorInfo } from '../../src/app/SensorCatalog';
import { parseLatestFile, parseManifest, parseSensorsGeoJSON } from '../../src/contract';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { DEFAULT_APP_STATE, type AppState } from '../../src/state/AppState';
import { HashStateCodec } from '../../src/state/HashStateCodec';
import { Store } from '../../src/state/Store';
import { el } from '../../src/ui/dom';
import { HashSync } from '../../src/ui/HashSync';
import { HeaderView } from '../../src/ui/HeaderView';
import { SensorList } from '../../src/ui/SensorList';
import { SensorColors } from '../../src/ui/SensorColors';
import { SensorPanel } from '../../src/ui/SensorPanel';
import { fixtureJson } from '../helpers';

const catalog = SensorCatalog.build(
  parseSensorsGeoJSON(fixtureJson('sensors.geojson')),
  parseManifest(fixtureJson('manifest.json')),
  parseLatestFile(fixtureJson('latest.json')),
);
const i18n = (): I18n => new I18n({ cs, de, en }, 'cs');

function sensor(id: string): SensorInfo {
  const found = catalog.get(id);
  if (found === undefined) {
    throw new Error(id);
  }
  return found;
}

describe('el', () => {
  it('sets attributes and children, skipping false and empty values', () => {
    const node = el('button', { type: 'button', disabled: true, hidden: false, title: undefined, 'data-n': 3 }, ['a', null, false, el('b')]);
    expect(node.outerHTML).toBe('<button type="button" disabled="" data-n="3">a<b></b></button>');
  });
});

describe('HeaderView', () => {
  it('shows title, demo badge and switches language', () => {
    const root = document.createElement('header');
    const onLanguage = vi.fn();
    const translations = i18n();
    const header = new HeaderView(root, translations, true, onLanguage);
    expect(root.querySelector('h1')?.textContent).toBe('SIVIN – meteostanice ve vinicích');
    expect(root.querySelector('.demo-badge')?.textContent).toBe('Ukázková data');
    expect(document.title).toBe('SIVIN – meteostanice ve vinicích');
    const select = root.querySelector('select');
    if (select) {
      select.value = 'en';
      select.dispatchEvent(new Event('change'));
    }
    expect(onLanguage).toHaveBeenCalledWith('en');
    translations.setLanguage('en');
    header.render();
    expect(document.documentElement.lang).toBe('en');
    expect(root.querySelector('h1')?.textContent).toBe('SIVIN – weather stations in vineyards');
  });

  it('has no badge for real data', () => {
    const root = document.createElement('header');
    new HeaderView(root, i18n(), false, vi.fn());
    expect(root.querySelector('.demo-badge')).toBeNull();
  });
});

describe('SensorList', () => {
  it('lists all sensors with checkboxes reflecting the selection', () => {
    const root = document.createElement('div');
    const onToggle = vi.fn();
    const colors = new SensorColors();
    colors.update(['77680921']);
    const list = new SensorList(root, catalog, i18n(), colors, onToggle);
    list.render(['77680921']);
    const swatches = [...root.querySelectorAll<HTMLElement>('.swatch')];
    expect(swatches[1]?.style.background).toBe('rgb(42, 120, 214)');
    expect(swatches[0]?.classList.contains('swatch--empty')).toBe(true);
    const boxes = [...root.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(boxes.map((box) => box.value)).toEqual(['77678271', '77680921', '77800065', '77799986']);
    expect(boxes.map((box) => box.checked)).toEqual([false, true, false, false]);
    boxes[0]?.dispatchEvent(new Event('change'));
    expect(onToggle).toHaveBeenCalledWith('77678271');
    expect(root.querySelector('label')?.textContent).toBe('77678271 (VUT)');
  });
});

describe('SensorPanel', () => {
  it('shows the hint without a selection and hides controls', () => {
    const root = document.createElement('aside');
    const panel = new SensorPanel(root, i18n(), 'Europe/Prague', new SensorColors(), vi.fn());
    panel.render([], false);
    expect(root.querySelector('.panel__hint')?.textContent).toContain('Vyberte čidlo');
    expect(panel.chartSlot.hidden).toBe(true);
    expect(panel.windowSlot.hidden).toBe(true);
  });

  it('shows metadata and latest values of selected sensors, marking stale ones', () => {
    const root = document.createElement('aside');
    const panel = new SensorPanel(root, i18n(), 'Europe/Prague', new SensorColors(), vi.fn());
    panel.render([sensor('77799986'), sensor('77800065')], false);
    const cards = root.querySelectorAll('.sensor-card');
    expect(cards).toHaveLength(2);
    const text = cards[0]?.textContent ?? '';
    expect(text).toContain('77799986 (VUT)');
    expect(text).toContain('219 m');
    expect(text).toContain('3. 6. 2026');
    expect(text).toContain('11,2 °C');
    expect(text).not.toContain('Vinice');
    expect(cards[1]?.querySelector('.is-stale')).not.toBeNull();
    expect(cards[1]?.textContent).toContain('neaktuální');
    expect(panel.chartSlot.hidden).toBe(false);
    expect(root.querySelector<HTMLElement>('.panel__hint')?.hidden).toBe(true);
  });

  it('shows the comparison limit and toggles the bottom sheet', () => {
    const root = document.createElement('aside');
    const onToggle = vi.fn();
    const panel = new SensorPanel(root, i18n(), 'Europe/Prague', new SensorColors(), onToggle);
    panel.render([sensor('77678271')], true);
    expect(root.querySelector('.panel__hint')?.textContent).toBe('Srovnat lze nejvýše 1 čidel.');
    const toggle = root.querySelector<HTMLButtonElement>('.panel__toggle');
    toggle?.click();
    expect(root.classList.contains('panel--collapsed')).toBe(true);
    expect(toggle?.getAttribute('aria-expanded')).toBe('false');
    expect(toggle?.textContent).toBe('Zobrazit panel');
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it('renders a sensor without latest values or placement', () => {
    const root = document.createElement('aside');
    const panel = new SensorPanel(root, i18n(), 'Europe/Prague', new SensorColors(), vi.fn());
    const bare: SensorInfo = { ...sensor('77678271'), latest: null, elevation_m: null, placedSince: 'unknown', site: 'Test', variety: null };
    panel.render([bare], false);
    const text = root.querySelector('.sensor-card')?.textContent ?? '';
    expect(text).toContain('bez hodnoty');
    expect(text).toContain('unknown');
    expect(text).toContain('Vinice');
  });
});

describe('HashSync', () => {
  it('writes state changes to the hash and reads user edits back', () => {
    const store = new Store<AppState>(DEFAULT_APP_STATE);
    const sync = new HashSync(store, new HashStateCodec(), window.location, window.history, window);
    sync.write();
    expect(window.location.hash).toBe('#w=7d&lang=cs');
    store.update({ selectedSensorIds: ['77678271'] });
    expect(window.location.hash).toBe('#s=77678271&w=7d&lang=cs');
    window.location.hash = '#s=77680921&w=24h&lang=de';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(store.state.selectedSensorIds).toEqual(['77680921']);
    expect(store.state.window).toEqual({ kind: '24h' });
    expect(store.state.language).toBe('de');
    window.location.hash = '#w=30d';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(store.state.selectedSensorIds).toEqual([]);
    expect(store.state.language).toBe('de');
  });
});
