import type { AppState } from '../state/AppState';
import type { I18n } from '../i18n/I18n';
import type { TimeWindow } from '../domain/TimeWindow';
import type { TimeWindowFactory } from '../domain/TimeWindowFactory';
import type { ChartData, ChartDataLoader } from './ChartDataLoader';

/** What the presenter needs from the chart UI. */
export interface ChartView {
  /** Show a status text above the current chart (e.g. "loading"). */
  showMessage(text: string): void;
  /** Remove the chart and show an error text. */
  showError(text: string): void;
  showData(data: ChartData): void;
}

/**
 * Keeps the chart in sync with the application state: resolves the time window, loads data and
 * shows it, a "loading" message, or an error. Responses of superseded requests are dropped.
 */
export class ChartPresenter {
  private latestRequest = 0;

  /**
   * @param anchorEndT - End of the available data (Unix seconds); relative presets end here.
   */
  constructor(
    private readonly loader: ChartDataLoader,
    private readonly factory: TimeWindowFactory,
    private readonly i18n: I18n,
    private readonly view: ChartView,
    private readonly anchorEndT: number,
  ) {}

  /** The concrete window for the state's window spec and resolution choice. */
  windowFor(state: AppState): TimeWindow {
    return this.factory.create(state.window, this.anchorEndT, state.resolution);
  }

  /** Load and show data for `sensorIds` in the state's window. Resolves when done. */
  async refresh(state: AppState, sensorIds: readonly string[]): Promise<void> {
    const request = ++this.latestRequest;
    if (sensorIds.length === 0) {
      return;
    }
    this.view.showMessage(this.i18n.t('loading'));
    try {
      const data = await this.loader.load(sensorIds, this.windowFor(state));
      if (request === this.latestRequest) {
        this.view.showData(data);
      }
    } catch (error) {
      if (request === this.latestRequest) {
        const message = error instanceof Error ? error.message : String(error);
        this.view.showError(this.i18n.t('loadError', { message }));
      }
    }
  }
}
