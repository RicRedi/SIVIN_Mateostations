/**
 * Quantities the chart can show: the measured temperature and humidity, quantities derived from
 * them in the browser, and the auxiliary measurements precipitation and battery voltage.
 */
export const QUANTITY_IDS = [
  'temp_c',
  'rh_pct',
  'dew_point_c',
  'leaf_wetness',
  'vpd_kpa',
  'abs_humidity_g_m3',
  'precip_mm',
  'battery_v',
] as const;
export type QuantityId = (typeof QUANTITY_IDS)[number];

/**
 * Quantities with an axis of their own (a third axis next to °C and %). To keep the chart
 * readable at most one of them is shown at a time.
 */
export const EXTRA_AXIS_QUANTITIES = ['vpd_kpa', 'abs_humidity_g_m3', 'precip_mm', 'battery_v'] as const satisfies readonly QuantityId[];
export type ExtraAxisQuantity = (typeof EXTRA_AXIS_QUANTITIES)[number];

/** Quantities drawn on the temperature or humidity axis, or as a band: freely combinable. */
export const BASE_QUANTITIES = ['temp_c', 'rh_pct', 'dew_point_c', 'leaf_wetness'] as const satisfies readonly QuantityId[];
export type BaseQuantity = (typeof BASE_QUANTITIES)[number];

/** Shown by default: the measured temperature and humidity, as before the derived quantities. */
export const DEFAULT_QUANTITIES: readonly QuantityId[] = Object.freeze(['temp_c', 'rh_pct']);

export function isQuantityId(value: unknown): value is QuantityId {
  return QUANTITY_IDS.includes(value as QuantityId);
}

export function isExtraAxisQuantity(id: QuantityId): id is ExtraAxisQuantity {
  return EXTRA_AXIS_QUANTITIES.includes(id as ExtraAxisQuantity);
}
