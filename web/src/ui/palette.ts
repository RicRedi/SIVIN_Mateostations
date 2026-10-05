/**
 * Categorical line colours for compared sensors, in assignment order.
 *
 * Validated with the dataviz palette checker (light mode, surface #fcfcfb): every adjacent pair
 * is separated under simulated protan/deutan vision (worst ΔE 8.6, OKLab ×100) and under normal
 * vision (worst ΔE 15.8). WCAG contrast against white, all ≥ 3:1 (1.4.11 non-text contrast):
 * #2a78d6 4.42, #c4501f 4.65, #0e8a5f 4.36, #9a6b00 4.69, #c2457a 4.74, #008300 4.95,
 * #4a3aa7 8.56, #c62f2f 5.46.
 */
export const SENSOR_COLORS = [
  '#2a78d6',
  '#c4501f',
  '#0e8a5f',
  '#9a6b00',
  '#c2457a',
  '#008300',
  '#4a3aa7',
  '#c62f2f',
] as const;

/**
 * Fill for markers without a current value (stale or missing); always paired with a dashed
 * outline. Contrast against white 4.24:1.
 */
export const STALE_COLOR = '#7d7b74';

/** One class of the temperature legend: `[lowerC, upperC)`, open-ended where `null`. */
export interface TemperatureClass {
  readonly lowerC: number | null;
  readonly upperC: number | null;
  readonly color: string;
}

/**
 * Class edges in °C. The split between blue and warm classes is 10 °C, the base temperature of
 * grapevine growing-degree days (MIGRATION_PLAN.md §3.1): blue reads "below vine growth base".
 */
export const TEMPERATURE_EDGES_C = [-5, 0, 5, 10, 15, 20, 25, 30] as const;

/**
 * Diverging scale without a near-white class, so a marker never looks empty: four blues from
 * ColorBrewer "Blues" below 10 °C and five yellow-orange-browns from ColorBrewer "YlOrBr" from
 * 10 °C up (colorbrewer2.org, Brewer & Harrower). Blue against orange is the pair best preserved
 * under colour-vision deficiency, and lightness is monotonic within each arm.
 */
export const TEMPERATURE_COLORS = [
  '#08519c',
  '#3182bd',
  '#6baed6',
  '#9ecae1',
  '#fec44f',
  '#fe9929',
  '#ec7014',
  '#cc4c02',
  '#8c2d04',
] as const;

/** Classed diverging colour scale for the latest temperature on the map. */
export class TemperatureScale {
  readonly classes: readonly TemperatureClass[];

  constructor(
    private readonly edgesC: readonly number[] = TEMPERATURE_EDGES_C,
    colors: readonly string[] = TEMPERATURE_COLORS,
  ) {
    if (colors.length !== edgesC.length + 1) {
      throw new RangeError(`Need ${edgesC.length + 1} colours for ${edgesC.length} edges`);
    }
    this.classes = colors.map((color, i) => ({
      lowerC: edgesC[i - 1] ?? null,
      upperC: edgesC[i] ?? null,
      color,
    }));
  }

  /** Colour for `tempC`; a value equal to an edge belongs to the warmer class. */
  colorFor(tempC: number): string {
    const index = this.edgesC.filter((edge) => tempC >= edge).length;
    return this.classes[index]?.color ?? STALE_COLOR;
  }
}
