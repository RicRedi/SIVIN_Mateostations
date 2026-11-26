import { MeasuredQuantity, type ChartQuantity } from '../app/ChartQuantities';
import type { VariableSpec } from '../contract';
import type { Resolution } from '../domain/TimeWindow';
import type { I18n } from '../i18n/I18n';

/**
 * Labels of chart quantities in the current language. Temperature and humidity take the
 * manifest's label (as before the derived quantities); the others, whose label depends on the
 * resolution (e.g. "daily precipitation"), come from the dictionaries.
 */
export class QuantityLabels {
  /** @param variables - Variable specs of the manifest. */
  constructor(
    private readonly i18n: I18n,
    private readonly variables: readonly VariableSpec[],
  ) {}

  /** Label of `quantity` at `resolution`, without unit. */
  label(quantity: ChartQuantity, resolution: Resolution): string {
    const fromManifest = quantity instanceof MeasuredQuantity && quantity.manifestLabelled
      ? this.variables.find((variable) => variable.id === quantity.id)
      : undefined;
    const translated = this.i18n.t(quantity.labelKey(resolution), quantity.labelParams());
    return fromManifest === undefined ? translated : this.i18n.label(fromManifest.label, translated);
  }

  /** Label with the unit, e.g. "Rosný bod (°C)". */
  labelWithUnit(quantity: ChartQuantity, resolution: Resolution): string {
    return `${this.label(quantity, resolution)} (${quantity.display.unit})`;
  }
}
