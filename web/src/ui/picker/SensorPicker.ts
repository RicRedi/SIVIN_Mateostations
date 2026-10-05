import type { SensorCatalog } from '../../app/SensorCatalog';
import { SensorGrouping } from '../../app/SensorGroups';
import { SensorQuery } from '../../app/SensorQuery';
import type { I18n } from '../../i18n/I18n';
import { MAX_COMPARED_SENSORS } from '../../state/AppState';
import type { LimitNotice } from '../../state/GroupSelection';
import { el } from '../dom';
import type { SensorColors } from '../SensorColors';
import { PickerTree, type PickerTreeHandlers } from './PickerTree';
import { SensorChips } from './SensorChips';

const PANEL_ID = 'sensor-picker-panel';
/** Controls the arrow keys move between inside the open panel. */
const FOCUSABLE = 'input, button';

/**
 * Sensor selection for larger networks (WP-3.5): a disclosure button "Čidla (n/N) ▾" that opens a
 * panel with a search field and the sensors grouped municipality → vineyard track, each group
 * with a tri-state "select all" checkbox; below it the selected sensors as chips in their line
 * colour.
 *
 * Keyboard: the button toggles the panel; opening focuses the search field; Tab and the
 * arrow keys move between the controls; Escape closes and returns focus to the button. A click
 * outside closes the panel. On phones the panel is a full-screen sheet with a close button (CSS).
 */
export class SensorPicker {
  private readonly trigger = el('button', {
    type: 'button',
    class: 'picker__trigger',
    'aria-expanded': 'false',
    'aria-controls': PANEL_ID,
  });
  private readonly triggerText = el('span');
  private readonly title = el('h2', { class: 'picker__title', id: `${PANEL_ID}-title` });
  private readonly closeButton = el('button', { type: 'button', class: 'picker__close' });
  private readonly search = el('input', { type: 'search', class: 'picker__search', autocomplete: 'off', spellcheck: false });
  private readonly notice = el('p', { class: 'picker__notice', role: 'status' });
  private readonly empty = el('p', { class: 'picker__empty' });
  private readonly panel: HTMLDivElement;
  private readonly tree: PickerTree;
  private readonly chips: SensorChips;
  private query = SensorQuery.EMPTY;
  private selectedIds: readonly string[] = [];

  /**
   * @param root - Container element (the panel's sensor slot).
   * @param catalog - The sensors.
   * @param i18n - Translations.
   * @param colors - Line colours of the compared sensors.
   * @param handlers - Called when a sensor or a whole group is toggled (chips remove a sensor).
   */
  constructor(
    private readonly root: HTMLElement,
    private readonly catalog: SensorCatalog,
    private readonly i18n: I18n,
    colors: SensorColors,
    handlers: PickerTreeHandlers,
  ) {
    this.tree = new PickerTree(new SensorGrouping().group(catalog.sensors), i18n, colors, handlers);
    this.chips = new SensorChips(catalog, i18n, colors, handlers.onSensorToggle, this.trigger);
    this.panel = el('div', { class: 'picker__panel', id: PANEL_ID, role: 'group', 'aria-labelledby': this.title.id, hidden: true }, [
      el('div', { class: 'picker__bar' }, [this.title, this.closeButton]),
      this.search,
      this.notice,
      this.empty,
      el('div', { class: 'picker__list' }, [this.tree.element]),
    ]);
    this.trigger.append(this.triggerText, el('span', { class: 'picker__caret', 'aria-hidden': 'true' }, ['▾']));
    root.classList.add('picker');
    root.append(this.trigger, this.panel, this.chips.element);
    this.listen();
  }

  get isOpen(): boolean {
    return !this.panel.hidden;
  }

  /** Show the selection (and a limit notice from the last change, if any). */
  render(selectedIds: readonly string[], notice: LimitNotice | null): void {
    this.selectedIds = selectedIds;
    const count = { selected: selectedIds.length, total: this.catalog.size };
    this.triggerText.textContent = this.i18n.t('pickerButton', count);
    this.title.textContent = `${this.i18n.t('pickerTitle')} (${String(count.selected)}/${String(count.total)})`;
    this.closeButton.textContent = this.i18n.t('pickerClose');
    this.search.setAttribute('aria-label', this.i18n.t('pickerSearchLabel'));
    this.search.placeholder = this.i18n.t('pickerSearchPlaceholder');
    this.notice.textContent = notice === null ? '' : this.noticeText(notice);
    this.notice.hidden = notice === null;
    this.chips.render(selectedIds);
    this.updateTree();
  }

  open(): void {
    this.setOpen(true);
    this.search.focus();
  }

  /** Close the panel; `returnFocus` moves focus back to the button (keyboard close). */
  close(returnFocus: boolean): void {
    this.setOpen(false);
    if (returnFocus) {
      this.trigger.focus();
    }
  }

  private listen(): void {
    this.trigger.addEventListener('click', () => {
      if (this.isOpen) {
        this.close(false);
      } else {
        this.open();
      }
    });
    this.closeButton.addEventListener('click', () => {
      this.close(true);
    });
    this.search.addEventListener('input', () => {
      const wasEmpty = this.query.isEmpty;
      this.query = SensorQuery.parse(this.search.value);
      if (wasEmpty && !this.query.isEmpty) {
        this.tree.expandAll();
      }
      this.updateTree();
    });
    this.root.addEventListener('keydown', (event) => {
      this.onKeyDown(event);
    });
    this.root.ownerDocument.addEventListener('pointerdown', (event) => {
      if (this.isOpen && event.target instanceof Node && !this.root.contains(event.target)) {
        this.close(false);
      }
    });
  }

  private onKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && this.isOpen) {
      event.preventDefault();
      this.close(true);
    } else if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && this.isOpen && event.target instanceof HTMLElement && this.panel.contains(event.target)) {
      event.preventDefault();
      this.moveFocus(event.target, event.key === 'ArrowDown' ? 1 : -1);
    }
  }

  /** Focus the next / previous visible control of the panel (stops at the ends). */
  private moveFocus(from: HTMLElement, step: 1 | -1): void {
    const controls = [...this.panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((control) => control.closest('[hidden]') === null);
    const target = controls[controls.indexOf(from) + step];
    target?.focus();
  }

  private setOpen(open: boolean): void {
    this.panel.hidden = !open;
    this.trigger.setAttribute('aria-expanded', String(open));
    this.root.classList.toggle('picker--open', open);
  }

  private updateTree(): void {
    const visible = this.tree.update({ query: this.query, selectedIds: this.selectedIds });
    this.empty.textContent = this.i18n.t('pickerNoMatch');
    this.empty.hidden = visible > 0;
  }

  private noticeText(notice: LimitNotice): string {
    return notice.kind === 'group'
      ? this.i18n.t('groupLimit', { max: MAX_COMPARED_SENSORS, added: notice.added })
      : this.i18n.t('comparisonLimit', { max: MAX_COMPARED_SENSORS });
  }
}
