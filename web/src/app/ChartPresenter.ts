import type { AppState } from '../state/AppState';
import type { I18n } from '../i18n/I18n';
import type { TimeWindow } from '../domain/TimeWindow';
import type { TimeWindowFactory } from '../domain/TimeWindowFactory';
import { DEFAULT_WINDOW } from '../domain/WindowSpec';
import type { ChartData, ChartDataLoader } from './ChartDataLoader';

/** What the presenter needs from the chart UI. */
export interface ChartView {
  /** Show a status text above the current chart (e.g. "loading"). */
  showMessage(text: string): void;
  /** Remove the chart and show an error text. */
  showError(text: string): void;
  showData(data: ChartData): void;
}

/** What the application needs from the presenter. */
export interface ChartController {
  windowFor(state: AppState): TimeWindow;
  refresh(state: AppState, sensorIds: readonly string[]): Promise<void>;
}

/**
 * Keeps the chart in sync with the application state: resolves the time window, loads data and
 * shows it, a "loading" message, or an error. Responses of superseded requests are dropped.
 */
export class ChartPresenter implements ChartController {
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

  /**
   * The concrete window for the state's window spec and resolution choice. A spec that cannot
   * be turned into a window (e.g. an invalid date) falls back to the default window, so the
   * application never fails on a bad URL.
   */
  windowFor(state: AppState): TimeWindow {
    try {
      return this.factory.create(state.window, this.anchorEndT, state.resolution);
    } catch (error) {
      if (!(error instanceof RangeError)) {
        throw error;
      }
      return this.factory.create(DEFAULT_WINDOW, this.anchorEndT, state.resolution);
    }
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
