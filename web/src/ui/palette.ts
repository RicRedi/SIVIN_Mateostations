/**
 * Categorical colours for compared sensors, assigned by registry position (never by selection
 * order) so a sensor keeps its colour. Order and steps from the colour-blind-validated
 * reference palette of the dataviz guidelines (adjacent-pair CVD ΔE ≥ 8 on a light surface).
 */
export const SENSOR_COLORS = [
  '#2a78d6',
  '#eb6834',
  '#1baf7a',
  '#eda100',
  '#e87ba4',
  '#008300',
  '#4a3aa7',
  '#e34948',
] as const;

/** Colour of sensor number `colorIndex` (wraps around after {@link SENSOR_COLORS}). */
export function sensorColor(colorIndex: number): string {
  return SENSOR_COLORS[colorIndex % SENSOR_COLORS.length] ?? SENSOR_COLORS[0];
}

/** Fill for markers without a current value (stale or missing); paired with a dashed outline. */
export const STALE_COLOR = '#9a9890';

/** One class of the temperature legend: `[lowerC, upperC)`, open-ended where `null`. */
export interface TemperatureClass {
  readonly lowerC: number | null;
  readonly upperC: number | null;
  readonly color: string;
}

/**
 * Class edges in °C. The neutral middle class 10–15 °C contains 10 °C, the base temperature of
 * grapevine growing-degree days (MIGRATION_PLAN.md §3.1), so blue reads "below vine growth
 * base", red "warm".
 */
export const TEMPERATURE_EDGES_C = [-5, 0, 5, 10, 15, 20, 25, 30] as const;

/**
 * ColorBrewer RdBu, 9 classes, reversed (cold = blue). Diverging, colour-blind safe, with a
 * neutral light-grey midpoint (Brewer & Harrower, colorbrewer2.org).
 */
export const TEMPERATURE_COLORS = [
  '#2166ac',
  '#4393c3',
  '#92c5de',
  '#d1e5f0',
  '#f7f7f7',
  '#fddbc7',
  '#f4a582',
  '#d6604d',
  '#b2182b',
] as const;

/** Diverging, classed colour scale for the latest temperature on the map. */
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
