import type { SensorCatalog } from '../app/SensorCatalog';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import { sensorColor } from './palette';

/**
 * Keyboard-accessible checkbox list of all sensors; checking adds a sensor to the comparison.
 */
export class SensorList {
  private readonly heading = el('h2', { class: 'panel__heading', id: 'sensor-list-heading' });
  private readonly list = el('ul', { class: 'sensor-list', 'aria-labelledby': 'sensor-list-heading' });
  private readonly checkboxes = new Map<string, HTMLInputElement>();

  /**
   * @param root - Container element.
   * @param catalog - Sensors to list.
   * @param i18n - Translations.
   * @param onToggle - Called with the id of the sensor whose checkbox changed.
   */
  constructor(
    root: HTMLElement,
    catalog: SensorCatalog,
    private readonly i18n: I18n,
    onToggle: (sensorId: string) => void,
  ) {
    for (const sensor of catalog.sensors) {
      const checkbox = el('input', { type: 'checkbox', value: sensor.id, id: `sensor-${sensor.id}` });
      checkbox.addEventListener('change', () => {
        onToggle(sensor.id);
      });
      this.checkboxes.set(sensor.id, checkbox);
      const swatch = el('span', { class: 'swatch', 'aria-hidden': 'true' });
      swatch.style.background = sensorColor(sensor.colorIndex);
      this.list.append(
        el('li', {}, [el('label', { for: checkbox.id }, [checkbox, swatch, sensor.label])]),
      );
    }
    root.append(this.heading, this.list);
  }

  render(selectedIds: readonly string[]): void {
    this.heading.textContent = this.i18n.t('sensorsHeading');
    for (const [id, checkbox] of this.checkboxes) {
      checkbox.checked = selectedIds.includes(id);
    }
  }
}
