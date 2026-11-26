import type { ChartQuantity, QuantityRegistry } from '../app/ChartQuantities';
import { BASE_QUANTITIES, EXTRA_AXIS_QUANTITIES, type ExtraAxisQuantity, type QuantityId } from '../domain/quantities';
import type { Resolution } from '../domain/TimeWindow';
import type { I18n } from '../i18n/I18n';
import { extraAxisOf, toggleQuantity, withExtraAxis } from '../state/QuantitySelection';
import { el } from './dom';
import type { QuantityLabels } from './QuantityLabels';

/** What the control displays. */
export interface QuantityControlState {
  readonly quantities: readonly QuantityId[];
  /** Resolution of the shown data (labels such as "daily precipitation" depend on it). */
  readonly resolution: Resolution;
}

/** Value of the "no third axis" radio button. */
const NO_EXTRA_AXIS = 'none';

/**
 * Chooses the chart quantities: check boxes for those on the temperature and humidity axes or
 * drawn as a band (temperature, humidity, dew point, leaf wetness), and radio buttons for the
 * single third axis (none, VPD, absolute humidity, precipitation, battery voltage), so that at
 * most one extra axis is visible at a time.
 */
export class QuantityControl {
  private readonly legend = el('legend', { class: 'panel__heading' });
  private readonly extraLegend = el('legend', { class: 'quantity-control__subheading' });
  private readonly boxes = new Map<QuantityId, { input: HTMLInputElement; text: HTMLSpanElement }>();
  private readonly radios = new Map<string, { input: HTMLInputElement; text: HTMLSpanElement }>();
  private current: QuantityControlState = { quantities: [], resolution: 'raw' };

  /**
   * @param root - Container element.
   * @param registry - The chart quantities.
   * @param labels - Quantity labels.
   * @param i18n - Translations.
   * @param onChange - Called with the new selection when the user changes it.
   * @param name - Name of the radio group (unique in the page).
   */
  constructor(
    root: HTMLElement,
    private readonly registry: QuantityRegistry,
    private readonly labels: QuantityLabels,
    private readonly i18n: I18n,
    private readonly onChange: (quantities: readonly QuantityId[]) => void,
    name = 'chart-extra-axis',
  ) {
    const baseList = el('div', { class: 'quantity-control__list' });
    for (const id of BASE_QUANTITIES) {
      const input = el('input', { type: 'checkbox', value: id });
      input.addEventListener('change', () => {
        this.onChange(toggleQuantity(this.current.quantities, id));
      });
      const text = el('span');
      this.boxes.set(id, { input, text });
      baseList.append(el('label', { class: 'quantity-control__option' }, [input, text]));
    }
    const extraList = el('div', { class: 'quantity-control__list' });
    for (const value of [NO_EXTRA_AXIS, ...EXTRA_AXIS_QUANTITIES]) {
      const input = el('input', { type: 'radio', name, value });
      input.addEventListener('change', () => {
        const extra = value === NO_EXTRA_AXIS ? null : (value as ExtraAxisQuantity);
        this.onChange(withExtraAxis(this.current.quantities, extra));
      });
      const text = el('span');
      this.radios.set(value, { input, text });
      extraList.append(el('label', { class: 'quantity-control__option' }, [input, text]));
    }
    root.append(
      el('fieldset', { class: 'quantity-control' }, [
        this.legend,
        baseList,
        el('fieldset', { class: 'quantity-control__extra' }, [this.extraLegend, extraList]),
      ]),
    );
  }

  render(state: QuantityControlState): void {
    this.current = state;
    this.legend.textContent = this.i18n.t('quantitiesHeading');
    this.extraLegend.textContent = this.i18n.t('extraAxisHeading');
    for (const [id, { input, text }] of this.boxes) {
      input.checked = state.quantities.includes(id);
      text.textContent = this.label(this.registry.get(id), state.resolution);
    }
    const extra = extraAxisOf(state.quantities) ?? NO_EXTRA_AXIS;
    for (const [value, { input, text }] of this.radios) {
      input.checked = value === extra;
      text.textContent =
        value === NO_EXTRA_AXIS ? this.i18n.t('extraAxisNone') : this.label(this.registry.get(value as QuantityId), state.resolution);
    }
  }

  /** Label with unit; a band has no axis, so its label (with the threshold) stands alone. */
  private label(quantity: ChartQuantity, resolution: Resolution): string {
    return quantity.display.axis === 'band' ? this.labels.label(quantity, resolution) : this.labels.labelWithUnit(quantity, resolution);
  }
}
