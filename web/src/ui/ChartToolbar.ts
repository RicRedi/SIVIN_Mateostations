import type { ViewRange } from '../domain/ViewRange';
import type { I18n } from '../i18n/I18n';
import type { CsvFile } from './ChartCsv';
import type { ChartModel } from './ChartModel';
import { el } from './dom';

/** What the chart currently shows: the model and the visible (possibly zoomed) range. */
export interface ChartSnapshot {
  readonly model: ChartModel;
  readonly view: ViewRange;
}

/** State of the toolbar buttons. */
export interface ChartToolbarState {
  /** True if the chart shows less than the loaded window. */
  readonly zoomed: boolean;
  /** True if there is something to export. */
  readonly exportable: boolean;
  /** True while the chart is maximised (the maximise button is hidden then). */
  readonly maximised: boolean;
}

/** Actions of the toolbar buttons. */
export interface ChartToolbarActions {
  onMaximise(): void;
  onResetZoom(): void;
  onDownload(): void;
}

/**
 * Buttons above the chart — "⤢" maximise (accessible name "Zvětšit graf"), "Celé okno" (reset the
 * zoom; disabled when not zoomed) and "Stáhnout CSV" — and a short hint how to zoom and pan.
 */
export class ChartToolbar {
  readonly element = el('div', { class: 'chart__toolbar' });
  private readonly maximise = el('button', { type: 'button', class: 'chart__button chart__button--icon' }, ['⤢']);
  private readonly reset = el('button', { type: 'button', class: 'chart__button', disabled: true });
  private readonly download = el('button', { type: 'button', class: 'chart__button', disabled: true });
  private readonly hint = el('p', { class: 'chart__hint' });
  private state: ChartToolbarState = { zoomed: false, exportable: false, maximised: false };

  /**
   * @param root - The chart section; the toolbar becomes its first child.
   * @param i18n - Translations.
   * @param actions - Button actions.
   */
  constructor(
    root: HTMLElement,
    private readonly i18n: I18n,
    actions: ChartToolbarActions,
  ) {
    this.maximise.addEventListener('click', () => {
      actions.onMaximise();
    });
    this.reset.addEventListener('click', () => {
      actions.onResetZoom();
    });
    this.download.addEventListener('click', () => {
      actions.onDownload();
    });
    this.element.append(el('div', { class: 'chart__buttons' }, [this.download, this.reset, this.maximise]), this.hint);
    root.prepend(this.element);
    this.render();
  }

  /** Change part of the state (e.g. only `maximised`); the rest stays. */
  update(change: Partial<ChartToolbarState>): void {
    this.state = { ...this.state, ...change };
    this.render();
  }

  /** Apply the state and the current language. */
  render(): void {
    const label = this.i18n.t('chartMaximise');
    this.maximise.setAttribute('aria-label', label);
    this.maximise.title = label;
    this.maximise.hidden = this.state.maximised;
    this.reset.textContent = this.i18n.t('chartResetZoom');
    this.reset.disabled = !this.state.zoomed;
    this.download.textContent = this.i18n.t('chartDownloadCsv');
    this.download.disabled = !this.state.exportable;
    this.hint.textContent = this.i18n.t('chartZoomHint');
  }
}

/** Builds and saves the CSV of what the chart shows. */
export class ChartExport {
  /**
   * @param snapshot - The chart's current model and view, `null` without data.
   * @param toFile - Builds the file (`ChartCsv.file`).
   * @param save - Saves a file (`FileDownload.save`).
   */
  constructor(
    private readonly snapshot: () => ChartSnapshot | null,
    private readonly toFile: (model: ChartModel, view: ViewRange) => CsvFile,
    private readonly save: (fileName: string, content: string) => void,
  ) {}

  /** @returns True if a file was saved. */
  run(): boolean {
    const current = this.snapshot();
    if (current === null) {
      return false;
    }
    const file = this.toFile(current.model, current.view);
    this.save(file.fileName, file.content);
    return true;
  }
}
