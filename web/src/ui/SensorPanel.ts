import type { SensorInfo } from '../app/SensorCatalog';
import { formatPosition } from '../domain/position';
import { MS_PER_SECOND } from '../domain/units';
import type { MessageKey } from '../i18n/cs';
import type { I18n } from '../i18n/I18n';
import { CopyButton, type TextClipboard } from './CopyButton';
import { el } from './dom';
import type { SensorColors } from './SensorColors';

const VALUE_DECIMALS = 1;
const ELEVATION_DECIMALS = 0;

/**
 * Side panel (a bottom sheet on phones): sensor picker, metadata and latest values of the selected
 * sensors, time-window controls and the chart. The picker, controls and chart are separate
 * components rendered into the slots this panel exposes.
 */
export class SensorPanel {
  readonly pickerSlot = el('section', { class: 'panel__section' });
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
  private copyButtons: CopyButton[] = [];

  /**
   * @param root - The panel element.
   * @param i18n - Translations and formatting.
   * @param timeZone - Display time zone.
   * @param colors - Line colours of the compared sensors.
   * @param onToggle - Called after the panel was expanded or collapsed (map must resize).
   * @param clipboard - Clipboard for copying a sensor position, `null` where the API is missing.
   */
  constructor(
    root: HTMLElement,
    private readonly i18n: I18n,
    private readonly timeZone: string,
    private readonly colors: SensorColors,
    onToggle: () => void,
    private readonly clipboard: TextClipboard | null,
  ) {
    this.toggle.addEventListener('click', () => {
      this.expanded = !this.expanded;
      root.classList.toggle('panel--collapsed', !this.expanded);
      this.renderToggle();
      onToggle();
    });
    this.body.append(this.pickerSlot, this.hint, this.details, this.windowSlot, this.chartSlot);
    root.append(this.toggle, this.body);
  }

  /**
   * Show metadata of `selected`; the controls and chart are shown only with a selection. The
   * comparison limit is reported by the sensor picker, once.
   */
  render(selected: readonly SensorInfo[]): void {
    this.renderToggle();
    const hasSelection = selected.length > 0;
    this.hint.textContent = this.i18n.t('selectHint');
    this.hint.hidden = hasSelection;
    this.windowSlot.hidden = !hasSelection;
    this.chartSlot.hidden = !hasSelection;
    for (const button of this.copyButtons) {
      button.dispose();
    }
    this.copyButtons = [];
    this.details.replaceChildren(...selected.map((sensor) => this.card(sensor)));
  }

  private renderToggle(): void {
    this.toggle.textContent = this.i18n.t(this.expanded ? 'hidePanel' : 'showPanel');
    this.toggle.setAttribute('aria-expanded', String(this.expanded));
  }

  private card(sensor: SensorInfo): HTMLElement {
    const swatch = el('span', { class: 'swatch', 'aria-hidden': 'true' });
    swatch.style.background = this.colors.colorFor(sensor.id) ?? 'transparent';
    const rows: [MessageKey, string | Node | null][] = [
      ['sensorId', sensor.id],
      ['elevation', sensor.elevation_m === null ? null : `${this.i18n.formatNumber(sensor.elevation_m, ELEVATION_DECIMALS)} m`],
      ['placedSince', sensor.placedSince === null ? null : this.formatIsoDate(sensor.placedSince)],
      ['municipality', sensor.municipality],
      ['track', sensor.track],
      ['variety', sensor.variety],
      ['position', this.position(sensor)],
    ];
    const definitions = rows
      .filter((row): row is [MessageKey, string | Node] => row[1] !== null)
      .flatMap(([key, value]) => [el('dt', {}, [this.i18n.t(key)]), el('dd', {}, [value])]);
    return el('article', { class: 'sensor-card' }, [
      el('h3', { class: 'sensor-card__title' }, [swatch, sensor.label]),
      el('dl', { class: 'sensor-card__meta' }, definitions),
      this.latest(sensor),
    ]);
  }

  /** Current position as selectable text with its own copy button. */
  private position(sensor: SensorInfo): HTMLElement {
    const text = formatPosition(sensor.lat, sensor.lon);
    const coordinates = el('span', { class: 'sensor-card__coords' }, [text]);
    const copy = new CopyButton(text, coordinates, this.clipboard, {
      idle: this.i18n.t('copyPosition'),
      action: this.i18n.t('copyPositionLabel'),
      copied: this.i18n.t('positionCopied'),
      selected: this.i18n.t('positionSelected'),
    });
    this.copyButtons.push(copy);
    return el('span', { class: 'sensor-card__position' }, [coordinates, copy.button, copy.announcer]);
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
