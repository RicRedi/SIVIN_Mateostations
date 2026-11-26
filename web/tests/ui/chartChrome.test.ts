// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type uPlot from 'uplot';
import { createQuantityRegistry } from '../../src/app/ChartQuantities';
import { parseManifest } from '../../src/contract';
import { TimeWindow } from '../../src/domain/TimeWindow';
import { ViewRange } from '../../src/domain/ViewRange';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { ChartDialog } from '../../src/ui/ChartDialog';
import { ChartModel } from '../../src/ui/ChartModel';
import { ChartExport, ChartToolbar } from '../../src/ui/ChartToolbar';
import { CSV_MIME_TYPE, FileDownload, REVOKE_DELAY_MS } from '../../src/ui/FileDownload';
import { QuantityControl } from '../../src/ui/QuantityControl';
import { QuantityLabels } from '../../src/ui/QuantityLabels';
import { WET_LANE_HEIGHT_PX, WetnessBands, withAlpha } from '../../src/ui/WetnessBands';
import type { QuantityId } from '../../src/domain/quantities';
import { fixtureJson } from '../helpers';

vi.hoisted(() => {
  // uPlot reads the device pixel ratio through matchMedia when it is imported; jsdom has none.
  window.matchMedia = () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) as unknown as MediaQueryList;
});

const variables = parseManifest(fixtureJson('manifest.json')).variables;

describe('ChartDialog', () => {
  let panel: HTMLElement;
  let picker: HTMLElement;
  let controls: HTMLElement;
  let chart: HTMLElement;
  let opener: HTMLButtonElement;
  let dialog: ChartDialog;
  let phone: boolean;
  const changes: boolean[] = [];
  const i18n = new I18n({ cs, de, en }, 'cs');

  beforeEach(() => {
    document.body.replaceChildren();
    changes.length = 0;
    phone = false;
    const header = document.createElement('header');
    panel = document.createElement('aside');
    picker = document.createElement('section');
    controls = document.createElement('section');
    chart = document.createElement('section');
    opener = document.createElement('button');
    chart.append(opener);
    panel.append(picker, controls, chart);
    document.body.append(header, panel);
    dialog = new ChartDialog(document, i18n, { controls: [picker, controls], chart }, () => phone, (open) => changes.push(open));
  });

  function window_(): HTMLElement {
    const found = document.querySelector<HTMLElement>('.chart-dialog__window');
    if (found === null) {
      throw new Error('no dialog');
    }
    return found;
  }

  it('moves chart and controls into a modal dialog and puts them back on close', () => {
    opener.focus();
    dialog.open();
    expect(dialog.isOpen).toBe(true);
    expect(window_().getAttribute('role')).toBe('dialog');
    expect(window_().getAttribute('aria-modal')).toBe('true');
    expect(document.getElementById('chart-dialog-title')?.textContent).toBe('Graf');
    expect(window_().contains(chart) && window_().contains(picker) && window_().contains(controls)).toBe(true);
    expect(document.querySelector('header')?.hasAttribute('inert')).toBe(true);
    expect(document.activeElement?.className).toBe('chart-dialog__close');
    expect(document.querySelector('details')?.open).toBe(true);
    dialog.open();
    expect(changes).toEqual([true]);

    document.querySelector<HTMLButtonElement>('.chart-dialog__close')?.click();
    expect(dialog.isOpen).toBe(false);
    expect([...panel.children]).toEqual([picker, controls, chart]);
    expect(document.querySelector('header')?.hasAttribute('inert')).toBe(false);
    expect(document.activeElement).toBe(opener);
    expect(changes).toEqual([true, false]);
    dialog.close();
    expect(changes).toEqual([true, false]);
  });

  it('closes on Escape unless a control inside handled it, and starts with collapsed controls on phones', () => {
    phone = true;
    dialog.open();
    expect(document.querySelector('details')?.open).toBe(false);
    const handled = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    handled.preventDefault();
    picker.dispatchEvent(handled);
    expect(dialog.isOpen).toBe(true);
    picker.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    expect(dialog.isOpen).toBe(false);
  });

  it('traps Tab inside the dialog and translates its texts', () => {
    dialog.open();
    opener.focus();
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    opener.dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(true);
    expect(document.activeElement?.className).toBe('chart-dialog__close');
    i18n.setLanguage('en');
    dialog.render();
    expect(document.querySelector('.chart-dialog__close')?.getAttribute('aria-label')).toBe('Close');
    expect(document.querySelector('summary')?.textContent).toBe('Chart settings');
    expect(document.querySelector('.chart-dialog__empty')?.textContent).toBe('No sensor selected. Choose sensors in the chart settings (Sensors).');
    i18n.setLanguage('cs');
  });
});

describe('ChartToolbar', () => {
  it('renders the buttons, their state and texts and calls the actions', () => {
    const root = document.createElement('section');
    root.append(document.createElement('p'));
    const actions = { onMaximise: vi.fn(), onResetZoom: vi.fn(), onDownload: vi.fn() };
    const toolbar = new ChartToolbar(root, new I18n({ cs, de, en }, 'cs'), actions);
    expect(root.firstElementChild).toBe(toolbar.element);
    const [download, reset, maximise] = [...root.querySelectorAll('button')];
    expect(maximise?.getAttribute('aria-label')).toBe('Zvětšit graf');
    expect(maximise?.textContent).toBe('⤢');
    expect(reset?.textContent).toBe('Celé okno');
    expect(download?.textContent).toBe('Stáhnout CSV');
    expect([reset?.disabled, download?.disabled]).toEqual([true, true]);
    toolbar.update({ zoomed: true, exportable: true });
    toolbar.update({ maximised: true });
    expect([reset?.disabled, download?.disabled, maximise?.hidden]).toEqual([false, false, true]);
    maximise?.click();
    reset?.click();
    download?.click();
    expect([actions.onMaximise, actions.onResetZoom, actions.onDownload].map((f) => f.mock.calls.length)).toEqual([1, 1, 1]);
    expect(root.querySelector('.chart__hint')?.textContent).toContain('Kolečko myši');
  });
});

describe('ChartExport and FileDownload', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('saves the CSV of the current snapshot and nothing without a chart', () => {
    const model = ChartModel.build({ window: new TimeWindow(0, 3600, 'raw'), sensors: [], failures: [] }, []);
    const view = new ViewRange(0, 1800);
    let snapshot: { model: ChartModel; view: ViewRange } | null = null;
    const saved: [string, string][] = [];
    const toFile = vi.fn(() => ({ fileName: 'a.csv', content: 'x' }));
    const exporter = new ChartExport(() => snapshot, toFile, (name, content) => saved.push([name, content]));
    expect(exporter.run()).toBe(false);
    snapshot = { model, view };
    expect(exporter.run()).toBe(true);
    expect(toFile).toHaveBeenCalledWith(model, view);
    expect(saved).toEqual([['a.csv', 'x']]);
  });

  it('downloads through a temporary link and revokes the object URL later', async () => {
    vi.useFakeTimers();
    const urls = { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() };
    const clicked: [string, string][] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push([this.download, this.getAttribute('href') ?? '']);
    });
    new FileDownload(document, urls).save('sivin.csv', '﻿a;b');
    expect(clicked).toEqual([['sivin.csv', 'blob:test']]);
    expect(document.querySelector('a[download]')).toBeNull();
    const blob = (urls.createObjectURL.mock.calls[0] as unknown as [Blob])[0];
    expect(blob.type).toBe(CSV_MIME_TYPE);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    expect(urls.revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(REVOKE_DELAY_MS);
    expect(urls.revokeObjectURL).toHaveBeenCalledWith('blob:test');
    click.mockRestore();
  });
});

describe('QuantityControl', () => {
  const i18n = new I18n({ cs, de, en }, 'cs');
  const registry = createQuantityRegistry(variables);
  let root: HTMLElement;
  let changes: (readonly QuantityId[])[];
  let control: QuantityControl;

  beforeEach(() => {
    root = document.createElement('div');
    document.body.append(root);
    changes = [];
    control = new QuantityControl(root, registry, new QuantityLabels(i18n, variables), i18n, (q) => changes.push(q));
    control.render({ quantities: ['temp_c', 'rh_pct', 'vpd_kpa'], resolution: 'daily' });
  });

  function input(value: string): HTMLInputElement {
    const found = root.querySelector<HTMLInputElement>(`input[value="${value}"]`);
    if (found === null) {
      throw new Error(`no input ${value}`);
    }
    return found;
  }

  it('shows check boxes for the base quantities and radio buttons for the third axis', () => {
    expect(root.querySelector('legend')?.textContent).toBe('Zobrazené veličiny');
    expect([...root.querySelectorAll('input[type=checkbox]')].map((i) => (i as HTMLInputElement).value)).toEqual([
      'temp_c', 'rh_pct', 'dew_point_c', 'leaf_wetness',
    ]);
    expect([input('temp_c').checked, input('dew_point_c').checked, input('vpd_kpa').checked, input('none').checked]).toEqual([true, false, true, false]);
    const labels = [...root.querySelectorAll('label')].map((l) => l.textContent);
    expect(labels).toContain('Teplota (°C)');
    // Rendered at daily resolution: leaf wetness carries the "not daily" note.
    expect(labels).toContain('Ovlhčení listů – odhad (RH ≥ 90 %)– jen pro surová data a hodinové průměry');
    expect(labels).toContain('Denní srážky (mm)');
    expect(labels).toContain('Denní minimum napětí baterie (V)');
    expect(labels).toContain('Žádná');
  });

  it('disables leaf wetness at daily resolution with a note and enables it again at hourly', () => {
    control.render({ quantities: ['temp_c', 'leaf_wetness'], resolution: 'daily' });
    const note = input('leaf_wetness').closest('label')?.querySelector<HTMLElement>('.quantity-control__note');
    expect([input('leaf_wetness').disabled, input('leaf_wetness').checked, note?.hidden, note?.textContent]).toEqual([
      true, true, false, '– jen pro surová data a hodinové průměry',
    ]);
    expect(input('dew_point_c').disabled).toBe(false);
    control.render({ quantities: ['temp_c', 'leaf_wetness'], resolution: 'hourly' });
    expect([input('leaf_wetness').disabled, note?.hidden]).toEqual([false, true]);
  });

  it('reports toggled quantities and a changed third axis', () => {
    input('dew_point_c').click();
    input('precip_mm').click();
    input('none').click();
    expect(changes).toEqual([
      ['temp_c', 'rh_pct', 'dew_point_c', 'vpd_kpa'],
      ['temp_c', 'rh_pct', 'precip_mm'],
      ['temp_c', 'rh_pct'],
    ]);
  });
});

describe('WetnessBands', () => {
  it('fills one lane per sensor along the bottom, in the sensor colour with alpha', () => {
    const fills: [string, number, number, number, number][] = [];
    const ctx = {
      save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), clip: vi.fn(), fillStyle: '',
      fillRect(x: number, y: number, w: number, h: number) {
        fills.push([this.fillStyle, x, y, w, h]);
      },
    };
    const plot = { ctx, bbox: { left: 10, top: 0, width: 500, height: 200 }, valToPos: (v: number) => v } as unknown as uPlot;
    const bands = new WetnessBands((id) => (id === 'a' ? '#2a78d6' : 'red'));
    bands.draw(plot);
    expect(ctx.save).not.toHaveBeenCalled();
    bands.setLanes([
      { sensorId: 'a', intervals: [{ startT: 20, endT: 50 }] },
      { sensorId: 'b', intervals: [{ startT: 60, endT: 70 }] },
    ]);
    bands.draw(plot);
    expect(ctx.clip).toHaveBeenCalled();
    expect(fills).toEqual([
      ['#2a78d673', 20, 200 - WET_LANE_HEIGHT_PX, 30, WET_LANE_HEIGHT_PX],
      ['red', 60, 200 - 2 * WET_LANE_HEIGHT_PX, 10, WET_LANE_HEIGHT_PX],
    ]);
    expect(withAlpha('#000000', 1)).toBe('#000000ff');
  });
});
