import type { SensorCatalog } from '../../app/SensorCatalog';
import type { I18n } from '../../i18n/I18n';
import { el } from '../dom';
import type { SensorColors } from '../SensorColors';

/**
 * The selected sensors as removable chips in their line colour, in selection order. The chips
 * double as the legend of the chart. Removing a chip moves focus to the next chip, or to
 * `fallbackFocus` when it was the last one.
 */
export class SensorChips {
  readonly element = el('ul', { class: 'picker-chips' });

  /**
   * @param catalog - Labels of the sensors.
   * @param i18n - Translations.
   * @param colors - Line colours of the compared sensors.
   * @param onRemove - Called with the id of the sensor whose chip was removed.
   * @param fallbackFocus - Receives focus when the last chip is removed.
   */
  constructor(
    private readonly catalog: SensorCatalog,
    private readonly i18n: I18n,
    private readonly colors: SensorColors,
    private readonly onRemove: (sensorId: string) => void,
    private readonly fallbackFocus: HTMLElement,
  ) {}

  render(selectedIds: readonly string[]): void {
    this.element.setAttribute('aria-label', this.i18n.t('selectedSensors'));
    this.element.hidden = selectedIds.length === 0;
    this.element.replaceChildren(...selectedIds.map((id, index) => this.chip(id, index)));
  }

  private chip(sensorId: string, index: number): HTMLLIElement {
    const label = this.catalog.get(sensorId)?.label ?? sensorId;
    const color = this.colors.colorFor(sensorId) ?? 'transparent';
    const swatch = el('span', { class: 'swatch', 'aria-hidden': 'true' });
    swatch.style.background = color;
    const remove = el('button', { type: 'button', class: 'picker-chip__remove', 'aria-label': this.i18n.t('removeSensor', { sensor: label }) }, [
      el('span', { 'aria-hidden': 'true' }, ['×']),
    ]);
    remove.addEventListener('click', () => {
      this.onRemove(sensorId);
      this.focusAfterRemoval(index);
    });
    const chip = el('li', { class: 'picker-chip' }, [swatch, el('span', { class: 'picker-chip__label' }, [label]), remove]);
    chip.style.borderColor = color;
    return chip;
  }

  private focusAfterRemoval(index: number): void {
    const buttons = [...this.element.querySelectorAll<HTMLButtonElement>('.picker-chip__remove')];
    (buttons[index] ?? buttons.at(-1) ?? this.fallbackFocus).focus();
  }
}
