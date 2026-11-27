import type { I18n } from '../i18n/I18n';
import type { AnalyticsData, AnalyticsLoader } from './AnalyticsLoader';

/** What the presenter needs from the analytics UI. */
export interface AnalyticsView {
  showMessage(text: string): void;
  showData(data: AnalyticsData): void;
}

/**
 * Keeps the "Ukazatele" section in sync with the selected sensors and season: shows "loading",
 * then the data; responses of superseded requests are dropped.
 */
export class AnalyticsPresenter {
  private latestRequest = 0;

  constructor(
    private readonly loader: AnalyticsLoader,
    private readonly i18n: I18n,
    private readonly view: AnalyticsView,
  ) {}

  /** Load and show the analytics of `sensorIds` for `season`. Resolves when done. */
  async refresh(season: number | null, sensorIds: readonly string[]): Promise<void> {
    const request = ++this.latestRequest;
    if (season === null || sensorIds.length === 0) {
      return;
    }
    this.view.showMessage(this.i18n.t('loading'));
    const data = await this.loader.load(season, sensorIds);
    if (request === this.latestRequest) {
      this.view.showData(data);
    }
  }
}
