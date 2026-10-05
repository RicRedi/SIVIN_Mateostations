import type { SensorInfo } from '../app/SensorCatalog';
import { MS_PER_SECOND } from '../domain/units';
import type { MessageKey } from '../i18n/cs';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import type { SensorColors } from './SensorColors';

const VALUE_DECIMALS = 1;
const ELEVATION_DECIMALS = 0;

/**
 * Side panel (a bottom sheet on phones): sensor list, metadata and latest values of the selected
 * sensors, time-window controls and the chart. The list, controls and chart are separate
 * components rendered into the slots this panel exposes.
 */
export class SensorPanel {
  readonly listSlot = el('section', { class: 'panel__section' });
  readonly windowSlot = el('section', { class: 'panel__section' });
  readonly chartSlot = el('section', { class: 'panel__section chart' });
  private readonly toggle = el('button', {
    type: 'button',
    class: 'panel__toggle',
    'aria-expanded': 'true',
    'aria-controls': 'panel-body',
  });
  private readonly body = el('div', { class: 'panel__body', id: 'panel-body' });
  private readonly hint = el('p', { class: 'panel__hint' });
  private readonly details = el('div', { class: 'panel__details' });
  private expanded = true;

  /**
   * @param root - The panel element.
   * @param i18n - Translations and formatting.
   * @param timeZone - Display time zone.
   * @param colors - Line colours of the compared sensors.
   * @param onToggle - Called after the panel was expanded or collapsed (map must resize).
   */
  constructor(
    root: HTMLElement,
    private readonly i18n: I18n,
    private readonly timeZone: string,
    private readonly colors: SensorColors,
    onToggle: () => void,
  ) {
    this.toggle.addEventListener('click', () => {
      this.expanded = !this.expanded;
      root.classList.toggle('panel--collapsed', !this.expanded);
      this.renderToggle();
      onToggle();
    });
    this.body.append(this.listSlot, this.hint, this.details, this.windowSlot, this.chartSlot);
    root.append(this.toggle, this.body);
  }

  /** Show metadata of `selected`; the controls and chart are shown only with a selection. */
  render(selected: readonly SensorInfo[], limitReached: boolean): void {
    this.renderToggle();
    const hasSelection = selected.length > 0;
    this.hint.textContent = limitReached ? this.i18n.t('comparisonLimit', { max: selected.length }) : this.i18n.t('selectHint');
    this.hint.hidden = hasSelection && !limitReached;
    this.windowSlot.hidden = !hasSelection;
    this.chartSlot.hidden = !hasSelection;
    this.details.replaceChildren(...selected.map((sensor) => this.card(sensor)));
  }

  private renderToggle(): void {
    this.toggle.textContent = this.i18n.t(this.expanded ? 'hidePanel' : 'showPanel');
    this.toggle.setAttribute('aria-expanded', String(this.expanded));
  }

  private card(sensor: SensorInfo): HTMLElement {
    const swatch = el('span', { class: 'swatch', 'aria-hidden': 'true' });
    swatch.style.background = this.colors.colorFor(sensor.id) ?? 'transparent';
    const rows: [MessageKey, string | null][] = [
      ['sensorId', sensor.id],
      ['elevation', sensor.elevation_m === null ? null : `${this.i18n.formatNumber(sensor.elevation_m, ELEVATION_DECIMALS)} m`],
      ['placedSince', sensor.placedSince === null ? null : this.formatIsoDate(sensor.placedSince)],
      ['site', sensor.site],
      ['variety', sensor.variety],
    ];
    const definitions = rows
      .filter((row): row is [MessageKey, string] => row[1] !== null)
      .flatMap(([key, value]) => [el('dt', {}, [this.i18n.t(key)]), el('dd', {}, [value])]);
    return el('article', { class: 'sensor-card' }, [
      el('h3', { class: 'sensor-card__title' }, [swatch, sensor.label]),
      el('dl', { class: 'sensor-card__meta' }, definitions),
      this.latest(sensor),
    ]);
  }

  private latest(sensor: SensorInfo): HTMLElement {
    const latest = sensor.latest;
    const heading = el('h4', {}, [this.i18n.t('latestHeading')]);
    if (latest === null) {
      return el('div', { class: 'sensor-card__latest' }, [heading, this.i18n.t('noValue')]);
    }
    const format = (value: number | null, unit: string): string =>
      value === null ? this.i18n.t('noValue') : `${this.i18n.formatNumber(value, VALUE_DECIMALS)} ${unit}`;
    return el('div', { class: latest.stale ? 'sensor-card__latest is-stale' : 'sensor-card__latest' }, [
      heading,
      el('span', { class: 'sensor-card__value' }, [format(latest.temp_c, '°C')]),
      el('span', { class: 'sensor-card__value' }, [format(latest.rh_pct, '%')]),
      el('span', { class: 'sensor-card__time' }, [
        this.i18n.formatDateTime(latest.t, this.timeZone),
        latest.stale ? ` (${this.i18n.t('stale')})` : null,
      ]),
    ]);
  }

  private formatIsoDate(iso: string): string {
    const ms = Date.parse(iso);
    return Number.isNaN(ms) ? iso : this.i18n.formatDate(ms / MS_PER_SECOND, this.timeZone);
  }
}
