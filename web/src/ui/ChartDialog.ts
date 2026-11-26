import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import { ModalSheet } from './picker/ModalSheet';

/** The parts of the panel that the dialog shows while it is open. */
export interface ChartDialogParts {
  /** Controls shown beside the chart (sensor picker, time window, quantities), in this order. */
  readonly controls: readonly HTMLElement[];
  /** The chart section (toolbar, messages, plot). */
  readonly chart: HTMLElement;
}

const TITLE_ID = 'chart-dialog-title';

/**
 * The maximised chart: a centred modal dialog (full screen on phones) that **moves** the existing
 * chart and its controls into itself while open and puts them back on close, so there is one
 * chart, one set of controls and one application state — a change in the dialog is a change of
 * the small chart, and the zoom is kept.
 *
 * `role="dialog"`, `aria-modal="true"`, the rest of the page `inert` and Tab trapped inside
 * (`ModalSheet`); ✕ and Escape close it and focus returns to where it was. The controls are in a
 * `<details>` that starts open, except on phones, where the chart gets the room. Without a
 * selected sensor (the panel hides the chart section) the chart area says how to select one.
 */
export class ChartDialog {
  readonly element = el('div', { class: 'chart-dialog', hidden: true });
  private readonly window = el('div', { class: 'chart-dialog__window', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': TITLE_ID });
  private readonly title = el('h2', { class: 'chart-dialog__title', id: TITLE_ID });
  private readonly closeButton = el('button', { type: 'button', class: 'chart-dialog__close' }, ['✕']);
  private readonly settings = el('details', { class: 'chart-dialog__controls' });
  private readonly settingsSummary = el('summary');
  private readonly chartArea = el('div', { class: 'chart-dialog__chart' });
  /** Shown by CSS only while the chart section is hidden (no sensor selected). */
  private readonly emptyNote = el('p', { class: 'chart-dialog__empty' });
  private readonly modal: ModalSheet;
  private readonly markers = new Map<HTMLElement, Comment>();
  private returnFocus: HTMLElement | null = null;

  /**
   * @param document - Document the dialog is appended to (as the last child of `<body>`).
   * @param i18n - Translations.
   * @param parts - Elements moved into the dialog while it is open.
   * @param isPhone - True if the phone layout is active (checked on each opening).
   * @param onOpenChange - Called after opening (`true`), and on closing (`false`) before the
   *   focus returns (so a control hidden while open can be shown again and take the focus).
   */
  constructor(
    private readonly document: Document,
    private readonly i18n: I18n,
    private readonly parts: ChartDialogParts,
    private readonly isPhone: () => boolean,
    private readonly onOpenChange: (open: boolean) => void,
  ) {
    this.settings.append(this.settingsSummary);
    this.chartArea.append(this.emptyNote);
    this.window.append(
      el('div', { class: 'chart-dialog__bar' }, [this.title, this.closeButton]),
      el('div', { class: 'chart-dialog__body' }, [this.settings, this.chartArea]),
    );
    this.element.append(el('div', { class: 'chart-dialog__backdrop' }), this.window);
    this.modal = new ModalSheet(this.window, 'dialog');
    this.closeButton.addEventListener('click', () => {
      this.close();
    });
    this.element.addEventListener('keydown', (event) => {
      this.onKeyDown(event);
    });
    document.body.append(this.element);
    this.render();
  }

  get isOpen(): boolean {
    return !this.element.hidden;
  }

  /** Update the texts (language change). */
  render(): void {
    this.title.textContent = this.i18n.t('chartDialogTitle');
    this.closeButton.setAttribute('aria-label', this.i18n.t('chartDialogClose'));
    this.closeButton.title = this.i18n.t('chartDialogClose');
    this.settingsSummary.textContent = this.i18n.t('chartSettings');
    this.emptyNote.textContent = this.i18n.t('chartDialogEmpty');
  }

  open(): void {
    if (this.isOpen) {
      return;
    }
    const active = this.document.activeElement;
    this.returnFocus = active instanceof HTMLElement ? active : null;
    for (const control of this.parts.controls) {
      this.moveInto(control, this.settings);
    }
    this.moveInto(this.parts.chart, this.chartArea);
    this.settings.open = !this.isPhone();
    this.element.hidden = false;
    this.modal.activate();
    this.closeButton.focus();
    this.onOpenChange(true);
  }

  close(): void {
    if (!this.isOpen) {
      return;
    }
    this.modal.deactivate();
    this.element.hidden = true;
    for (const [part, marker] of this.markers) {
      marker.replaceWith(part);
    }
    this.markers.clear();
    this.onOpenChange(false);
    if (this.returnFocus?.isConnected === true) {
      this.returnFocus.focus();
    }
    this.returnFocus = null;
  }

  private moveInto(part: HTMLElement, target: HTMLElement): void {
    const marker = this.document.createComment('chart-dialog placeholder');
    part.before(marker);
    this.markers.set(part, marker);
    target.append(part);
  }

  private onKeyDown(event: KeyboardEvent): void {
    if (event.defaultPrevented) {
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      this.close();
      return;
    }
    this.modal.trapTab(event);
  }
}
