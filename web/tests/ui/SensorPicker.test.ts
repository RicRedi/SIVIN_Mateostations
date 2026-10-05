// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SensorCatalog } from '../../src/app/SensorCatalog';
import { parseLatestFile, parseManifest, parseSensorsGeoJSON } from '../../src/contract';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { ClusterIcon } from '../../src/ui/ClusterIcon';
import { SensorPicker } from '../../src/ui/picker/SensorPicker';
import { SensorColors } from '../../src/ui/SensorColors';
import { fixtureJson } from '../helpers';

// The sensor picker on the committed synthetic fixture: 20 sensors, fictional municipalities
// "Obec A/B/C" with tracks "Trať 1–6", one retired and one inactive sensor (WP-3.5).

const catalog = SensorCatalog.build(
  parseSensorsGeoJSON(fixtureJson('sensors.geojson')),
  parseManifest(fixtureJson('manifest.json')),
  parseLatestFile(fixtureJson('latest.json')),
);

interface Harness {
  root: HTMLElement;
  picker: SensorPicker;
  i18n: I18n;
  colors: SensorColors;
  onSensorToggle: ReturnType<typeof vi.fn<(id: string) => void>>;
  onGroupToggle: ReturnType<typeof vi.fn<(ids: readonly string[]) => void>>;
}

function setup(selected: readonly string[] = []): Harness {
  document.body.replaceChildren();
  const root = document.createElement('section');
  const outside = document.createElement('button');
  document.body.append(root, outside);
  const i18n = new I18n({ cs, de, en }, 'cs');
  const colors = new SensorColors();
  colors.update(selected);
  const onSensorToggle = vi.fn<(id: string) => void>();
  const onGroupToggle = vi.fn<(ids: readonly string[]) => void>();
  const picker = new SensorPicker(root, catalog, i18n, colors, { onSensorToggle, onGroupToggle });
  picker.render(selected, null);
  return { root, picker, i18n, colors, onSensorToggle, onGroupToggle };
}

function required<T>(value: T | null): T {
  if (value === null) {
    throw new Error('element missing');
  }
  return value;
}

const trigger = (root: HTMLElement): HTMLButtonElement => required(root.querySelector<HTMLButtonElement>('.picker__trigger'));
const search = (root: HTMLElement): HTMLInputElement => required(root.querySelector<HTMLInputElement>('.picker__search'));
const visibleText = (elements: Iterable<Element>): string[] =>
  [...elements].filter((e) => e.closest('[hidden]') === null).map((e) => e.textContent);

function groupHeads(root: HTMLElement, level: 'municipality' | 'track'): string[] {
  return visibleText(root.querySelectorAll(`.picker-group--${level} > .picker-group__head .picker-group__toggle`));
}

function groupCheckbox(root: HTMLElement, name: string): HTMLInputElement {
  const box = [...root.querySelectorAll<HTMLInputElement>('.picker-group__all')].find(
    (input) => input.getAttribute('aria-label') === `Vybrat vše: ${name}`,
  );
  if (box === undefined) {
    throw new Error(name);
  }
  return box;
}

function type(root: HTMLElement, text: string): void {
  search(root).value = text;
  search(root).dispatchEvent(new Event('input'));
}

function key(target: HTMLElement, name: string): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event;
}

describe('SensorPicker', () => {
  let h: Harness;

  beforeEach(() => {
    h = setup(['77680921', '90000302']);
  });

  it('shows the count on a closed disclosure button', () => {
    expect(trigger(h.root).textContent).toBe('Čidla (2/20)▾');
    expect(trigger(h.root).getAttribute('aria-expanded')).toBe('false');
    expect(trigger(h.root).getAttribute('aria-controls')).toBe('sensor-picker-panel');
    expect(h.picker.isOpen).toBe(false);
  });

  it('groups municipality → track with the unassigned groups last', () => {
    trigger(h.root).click();
    expect(groupHeads(h.root, 'municipality')).toEqual(['Obec A1/7', 'Obec B1/6', 'Obec C0/5', 'Nezařazeno0/2']);
    expect(groupHeads(h.root, 'track')).toEqual([
      'Trať 11/4', 'Trať 20/3', 'Trať 30/3', 'Trať 41/3', 'Trať 50/2', 'Trať 60/2', 'Nezařazeno0/1', 'Nezařazeno0/2',
    ]);
  });

  it('lists retired sensors last and greyed, with variety and status', () => {
    const track4 = [...h.root.querySelectorAll('.picker-group--track')][3];
    const rows = [...(track4?.querySelectorAll('.picker-sensor') ?? [])];
    expect(rows.map((row) => row.querySelector('.picker-sensor__label')?.textContent)).toEqual([
      '90000301 (demo)', '90000303 (demo)', '90000302 (demo)',
    ]);
    expect(rows[2]?.classList.contains('is-retired')).toBe(true);
    expect(rows[2]?.querySelector('.picker-sensor__meta')?.textContent).toBe('Zweigeltrebe · vyřazeno');
    expect(rows[0]?.classList.contains('is-retired')).toBe(false);
  });

  it('reflects the selection in checkboxes, swatches and tri-state group boxes', () => {
    const checked = [...h.root.querySelectorAll<HTMLInputElement>('.picker-sensor input:checked')].map((box) => box.value);
    expect(checked).toEqual(['77680921', '90000302']);
    const track1 = groupCheckbox(h.root, 'Trať 1');
    expect([track1.checked, track1.indeterminate]).toEqual([false, true]);
    const track2 = groupCheckbox(h.root, 'Trať 2');
    expect([track2.checked, track2.indeterminate]).toEqual([false, false]);
    h.picker.render(['77678271', '77680921', '77800065', '90000101'], null);
    expect([track1.checked, track1.indeterminate]).toEqual([true, false]);
    const swatch = h.root.querySelector<HTMLElement>('#picker-sensor-77680921 + .swatch');
    expect(swatch?.style.background).toBe('rgb(42, 120, 214)');
  });

  it('toggles a sensor and a group with the visible sensors in display order', () => {
    h.root.querySelector<HTMLInputElement>('#picker-sensor-90000111')?.dispatchEvent(new Event('change'));
    expect(h.onSensorToggle).toHaveBeenCalledWith('90000111');
    groupCheckbox(h.root, 'Trať 4').dispatchEvent(new Event('change'));
    expect(h.onGroupToggle).toHaveBeenLastCalledWith(['90000301', '90000303', '90000302']);
    groupCheckbox(h.root, 'Obec C').dispatchEvent(new Event('change'));
    expect(h.onGroupToggle).toHaveBeenLastCalledWith(['90000401', '90000402', '90000411', '90000412', '90000421']);
  });

  it('filters by search, ignoring case and diacritics, and selects only matches of a group', () => {
    trigger(h.root).click();
    type(h.root, 'tRAT 4');
    // Every word must match some field: "4" also matches the ids 900004xx of Obec C.
    expect(groupHeads(h.root, 'municipality')).toEqual(['Obec B1/3', 'Obec C0/4']);
    type(h.root, 'zweigel');
    expect(groupHeads(h.root, 'track')).toEqual(['Trať 41/2']);
    groupCheckbox(h.root, 'Obec B').dispatchEvent(new Event('change'));
    expect(h.onGroupToggle).toHaveBeenLastCalledWith(['90000301', '90000302']);
    type(h.root, 'pálava');
    expect(visibleText(h.root.querySelectorAll('.picker-sensor__label'))).toEqual(['90000101 (demo)']);
    type(h.root, 'xyz');
    expect(h.root.querySelector<HTMLElement>('.picker__empty')?.hidden).toBe(false);
    expect(h.root.querySelector('.picker__empty')?.textContent).toBe('Hledání neodpovídá žádné čidlo.');
    type(h.root, '');
    expect(groupHeads(h.root, 'municipality')).toHaveLength(4);
    expect(h.root.querySelector<HTMLElement>('.picker__empty')?.hidden).toBe(true);
  });

  it('collapses groups and expands them all when a search starts', () => {
    const toggle = [...h.root.querySelectorAll<HTMLButtonElement>('.picker-group__toggle')][0];
    const body = h.root.querySelector<HTMLElement>(`#${toggle?.getAttribute('aria-controls') ?? ''}`);
    toggle?.click();
    expect(toggle?.getAttribute('aria-expanded')).toBe('false');
    expect(body?.hidden).toBe(true);
    type(h.root, 'obec');
    expect(toggle?.getAttribute('aria-expanded')).toBe('true');
    expect(body?.hidden).toBe(false);
  });

  it('opens with focus in the search, closes with Escape back on the button', () => {
    trigger(h.root).click();
    expect(h.picker.isOpen).toBe(true);
    expect(trigger(h.root).getAttribute('aria-expanded')).toBe('true');
    expect(h.root.classList.contains('picker--open')).toBe(true);
    expect(document.activeElement).toBe(search(h.root));
    const escape = key(search(h.root), 'Escape');
    expect(escape.defaultPrevented).toBe(true);
    expect(h.picker.isOpen).toBe(false);
    expect(document.activeElement).toBe(trigger(h.root));
    expect(key(trigger(h.root), 'Escape').defaultPrevented).toBe(false);
  });

  it('moves focus with the arrow keys over visible controls only', () => {
    trigger(h.root).click();
    type(h.root, '90000201');
    key(search(h.root), 'ArrowDown');
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Vybrat vše: Obec B');
    key(document.activeElement as HTMLElement, 'ArrowDown');
    expect(document.activeElement?.classList.contains('picker-group__toggle')).toBe(true);
    key(document.activeElement as HTMLElement, 'ArrowDown');
    key(document.activeElement as HTMLElement, 'ArrowDown');
    key(document.activeElement as HTMLElement, 'ArrowDown');
    expect((document.activeElement as HTMLInputElement).value).toBe('90000201');
    key(document.activeElement as HTMLElement, 'ArrowDown');
    expect((document.activeElement as HTMLInputElement).value).toBe('90000201');
    key(document.activeElement as HTMLElement, 'ArrowUp');
    expect(document.activeElement?.classList.contains('picker-group__toggle')).toBe(true);
  });

  it('closes on the close button, a second button click and a click outside', () => {
    trigger(h.root).click();
    h.root.querySelector<HTMLButtonElement>('.picker__close')?.click();
    expect(h.picker.isOpen).toBe(false);
    expect(document.activeElement).toBe(trigger(h.root));
    trigger(h.root).click();
    trigger(h.root).click();
    expect(h.picker.isOpen).toBe(false);
    trigger(h.root).click();
    search(h.root).dispatchEvent(new Event('pointerdown', { bubbles: true }));
    expect(h.picker.isOpen).toBe(true);
    document.body.lastElementChild?.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    expect(h.picker.isOpen).toBe(false);
  });

  it('shows a limit notice for a single sensor and for a group', () => {
    const notice = h.root.querySelector<HTMLElement>('.picker__notice');
    expect(notice?.hidden).toBe(true);
    h.picker.render(['77680921'], { kind: 'sensor' });
    expect(notice?.hidden).toBe(false);
    expect(notice?.textContent).toBe('Srovnat lze nejvýše 8 čidel.');
    h.picker.render(['77680921'], { kind: 'group', added: 3 });
    expect(notice?.textContent).toBe('Srovnat lze nejvýše 8 čidel – ze skupiny bylo přidáno jen 3.');
    h.picker.render(['77680921'], null);
    expect(notice?.hidden).toBe(true);
  });

  it('translates on render', () => {
    h.i18n.setLanguage('en');
    h.picker.render([], null);
    trigger(h.root).click();
    expect(trigger(h.root).textContent).toBe('Sensors (0/20)▾');
    expect(search(h.root).getAttribute('aria-label')).toBe('Search sensors');
    expect(groupHeads(h.root, 'municipality').at(-1)).toBe('Unassigned0/2');
  });
});

describe('SensorChips', () => {
  it('shows the selection as chips in line colour, in selection order', () => {
    const h = setup(['90000302', '77680921']);
    const chips = [...h.root.querySelectorAll<HTMLElement>('.picker-chip')];
    expect(chips.map((chip) => chip.querySelector('.picker-chip__label')?.textContent)).toEqual(['90000302 (demo)', '77680921 (VUT)']);
    expect(chips[0]?.style.borderColor).toBe('rgb(42, 120, 214)');
    expect(h.root.querySelector('.picker-chips')?.getAttribute('aria-label')).toBe('Vybraná čidla');
    expect(chips[1]?.querySelector('button')?.getAttribute('aria-label')).toBe('Odebrat 77680921 (VUT) ze srovnání');
  });

  it('removes a chip and moves focus to the next chip, then to the button', () => {
    const h = setup(['90000302', '77680921']);
    h.onSensorToggle.mockImplementation((id) => {
      const next = id === '90000302' ? ['77680921'] : [];
      h.colors.update(next);
      h.picker.render(next, null);
    });
    h.root.querySelector<HTMLButtonElement>('.picker-chip__remove')?.click();
    expect(h.onSensorToggle).toHaveBeenCalledWith('90000302');
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Odebrat 77680921 (VUT) ze srovnání');
    (document.activeElement as HTMLButtonElement).click();
    expect(h.root.querySelector<HTMLElement>('.picker-chips')?.hidden).toBe(true);
    expect(document.activeElement).toBe(trigger(h.root));
  });

  it('falls back to the id for an unknown sensor', () => {
    const h = setup();
    h.picker.render(['12345678'], null);
    expect(h.root.querySelector('.picker-chip__label')?.textContent).toBe('12345678');
  });
});

describe('ClusterIcon', () => {
  it('shows the count, an accessible name and the selection highlight', () => {
    const icon = new ClusterIcon(new I18n({ cs, de, en }, 'cs'));
    const content = icon.content(5);
    expect(content.querySelector('[aria-hidden]')?.textContent).toBe('5');
    expect(content.querySelector('.visually-hidden')?.textContent).toBe('Skupina čidel: 5 – přiblížit');
    expect(icon.className(0)).toBe('sensor-cluster');
    expect(icon.className(2)).toBe('sensor-cluster sensor-cluster--selected');
  });
});
