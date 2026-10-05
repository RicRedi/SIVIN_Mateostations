// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import { TimeWindow } from '../../src/domain/TimeWindow';
import { TimeZone } from '../../src/domain/TimeZone';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { TimeWindowControl, type WindowChange } from '../../src/ui/TimeWindowControl';
import { utc } from '../helpers';

const WINDOW_7D = new TimeWindow(utc(2026, 9, 23, 22), utc(2026, 9, 30, 22), 'raw');

describe('TimeWindowControl', () => {
  let root: HTMLElement;
  let changes: WindowChange[];
  let control: TimeWindowControl;
  const i18n = new I18n({ cs, de, en }, 'cs');

  function button(kind: string): HTMLButtonElement {
    const found = root.querySelector<HTMLButtonElement>(`button[data-kind="${kind}"]`);
    if (found === null) {
      throw new Error(`no button ${kind}`);
    }
    return found;
  }

  beforeEach(() => {
    root = document.createElement('div');
    changes = [];
    control = new TimeWindowControl(root, i18n, new TimeZone('Europe/Prague'), [2025, 2026], (change) => changes.push(change));
    control.render({ spec: { kind: '7d' }, resolution: 'auto', window: WINDOW_7D });
  });

  it('marks the active preset and names the automatic resolution', () => {
    expect(button('7d').getAttribute('aria-pressed')).toBe('true');
    expect(button('24h').getAttribute('aria-pressed')).toBe('false');
    expect(button('7d').textContent).toBe('7 dní');
    const select = root.querySelector<HTMLSelectElement>('#resolution-select');
    expect(select?.value).toBe('auto');
    expect(select?.options[0]?.textContent).toBe('Automaticky (Surová data)');
  });

  it('shows the concrete window and resolution in local time', () => {
    const shown = root.querySelector('.window-control__shown')?.textContent ?? '';
    expect(shown).toMatch(/^Zobrazeno 24\. 9\. 2026 0:00 – 1\. 10\. 2026 0:00 · Surová data$/);
  });

  it('emits relative presets', () => {
    button('30d').click();
    expect(changes).toEqual([{ window: { kind: '30d' } }]);
  });

  it('emits the latest manifest season and lets the year be changed', () => {
    button('season').click();
    expect(changes[0]).toEqual({ window: { kind: 'season', year: 2026 } });
    control.render({ spec: { kind: 'season', year: 2026 }, resolution: 'auto', window: WINDOW_7D });
    const year = root.querySelector<HTMLSelectElement>('#season-year');
    expect(year?.closest('div')?.hidden).toBe(false);
    if (year) {
      year.value = '2025';
      year.dispatchEvent(new Event('change'));
    }
    expect(changes[1]).toEqual({ window: { kind: 'season', year: 2025 } });
  });

  it('prefills a custom range from the current window and applies edited dates', () => {
    button('custom').click();
    // 23 Sep 22:00Z – 30 Sep 22:00Z is 24 Sep – 30 Sep in Prague (end exclusive).
    expect(changes[0]).toEqual({ window: { kind: 'custom', from: '2026-09-24', to: '2026-09-30' } });
    control.render({ spec: { kind: 'custom', from: '2026-09-24', to: '2026-09-30' }, resolution: 'auto', window: WINDOW_7D });
    const from = root.querySelector<HTMLInputElement>('#custom-from');
    const form = root.querySelector('form');
    expect(form?.hidden).toBe(false);
    expect(from?.value).toBe('2026-09-24');
    if (from) {
      from.value = '2026-09-01';
    }
    form?.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(changes[1]).toEqual({ window: { kind: 'custom', from: '2026-09-01', to: '2026-09-30' } });
  });

  it('does not apply an incomplete custom range', () => {
    control.render({ spec: { kind: 'custom', from: '2026-09-24', to: '2026-09-30' }, resolution: 'auto', window: WINDOW_7D });
    const to = root.querySelector<HTMLInputElement>('#custom-to');
    if (to) {
      to.value = '';
    }
    root.querySelector('form')?.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(changes).toEqual([]);
  });

  it('emits an explicit resolution', () => {
    const select = root.querySelector<HTMLSelectElement>('#resolution-select');
    if (select) {
      select.value = 'daily';
      select.dispatchEvent(new Event('change'));
    }
    expect(changes).toEqual([{ resolution: 'daily' }]);
  });

  it('re-renders labels in another language', () => {
    i18n.setLanguage('de');
    control.render({ spec: { kind: '7d' }, resolution: 'hourly', window: WINDOW_7D.withResolution('hourly') });
    expect(button('7d').textContent).toBe('7 Tage');
    expect(root.querySelector('legend')?.textContent).toBe('Zeitfenster');
    expect(root.querySelector<HTMLSelectElement>('#resolution-select')?.value).toBe('hourly');
    i18n.setLanguage('cs');
  });
});
