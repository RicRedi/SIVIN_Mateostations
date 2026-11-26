import type { AnalyticsCatalog } from '../app/AnalyticsCatalog';
import type { AnalyticsData } from '../app/AnalyticsLoader';
import type { AnalyticsView } from '../app/AnalyticsPresenter';
import type { SensorCatalog } from '../app/SensorCatalog';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import type { IndexCardsView, SensorColumn } from './IndexCardsView';
import type { RecordsView } from './RecordsView';
import type { RiskStripView } from './RiskStripView';
import type { SensorColors } from './SensorColors';

/** The three parts of the section. */
export interface AnalyticsParts {
  readonly cards: IndexCardsView;
  readonly risks: RiskStripView;
  readonly records: RecordsView;
}

/**
 * The "Ukazatele" section of the panel: a season selector (the seasons of the manifest, the
 * latest by default), then the season index cards, the daily risk strips and the records of
 * the selected sensors. It asks for data only when the sensors or the season change; a
 * language change redraws the loaded data.
 */
export class AnalyticsSection implements AnalyticsView {
  private readonly heading = el('h3', {});
  private readonly seasonLabel = el('span', {});
  private readonly seasonSelect = el('select', { class: 'analytics__season' });
  private readonly status = el('p', { class: 'analytics__status', 'aria-live': 'polite' });
  private readonly body = el('div', { class: 'analytics__body' });
  private season: number | null;
  private sensorIds: readonly string[] = [];
  private data: AnalyticsData | null = null;

  /**
   * @param root - The section element (a panel slot).
   * @param seasons - Seasons of the manifest.
   * @param load - Asks for the data of a season and sensors (the presenter calls back
   *   {@link showMessage} and {@link showData}).
   */
  constructor(
    private readonly root: HTMLElement,
    private readonly i18n: I18n,
    private readonly catalog: AnalyticsCatalog,
    private readonly sensors: SensorCatalog,
    private readonly colors: SensorColors,
    private readonly parts: AnalyticsParts,
    seasons: readonly number[],
    private readonly load: (season: number | null, sensorIds: readonly string[]) => void,
  ) {
    const sorted = [...seasons].sort((a, b) => b - a);
    this.season = sorted[0] ?? null;
    this.seasonSelect.append(...sorted.map((year) => el('option', { value: year }, [String(year)])));
    this.seasonSelect.addEventListener('change', () => {
      this.season = Number(this.seasonSelect.value);
      this.request();
    });
    root.classList.add('analytics');
    root.append(
      this.heading,
      el('label', { class: 'analytics__season-label' }, [this.seasonLabel, this.seasonSelect]),
      this.status,
      this.body,
    );
  }

  /** Show the analytics of `sensorIds`; loads only when they or the season changed. */
  render(sensorIds: readonly string[]): void {
    this.heading.textContent = this.i18n.t('analyticsHeading');
    this.seasonLabel.textContent = this.i18n.t('analyticsSeason');
    this.root.hidden = sensorIds.length === 0;
    if (this.season === null) {
      this.status.textContent = this.i18n.t('analyticsNoSeason');
      this.body.replaceChildren();
      return;
    }
    const changed = sensorIds.length !== this.sensorIds.length || sensorIds.some((id, i) => id !== this.sensorIds[i]);
    this.sensorIds = sensorIds;
    if (changed) {
      this.request();
    } else if (this.data !== null) {
      this.showData(this.data);
    }
  }

  showMessage(text: string): void {
    this.status.textContent = text;
  }

  showData(data: AnalyticsData): void {
    this.data = data;
    this.status.textContent = '';
    const columns: SensorColumn[] = data.sensors.map((sensor) => ({
      id: sensor.sensorId,
      label: this.sensors.get(sensor.sensorId)?.label ?? sensor.sensorId,
      color: this.colors.colorFor(sensor.sensorId),
    }));
    this.body.replaceChildren(
      ...[
        this.parts.cards.render(this.catalog.cards, data, columns),
        this.parts.risks.render(this.catalog.risks, data, columns),
        this.parts.records.render(data, columns),
      ].filter((part): part is HTMLElement => part !== null),
    );
  }

  private request(): void {
    this.data = null;
    if (this.sensorIds.length === 0) {
      this.body.replaceChildren();
      return;
    }
    this.load(this.season, this.sensorIds);
  }
}
