/**
 * Psychrometric formulas for the derived chart quantities. They mirror the Python index
 * implementations (`src/sivin/analytics/ripening/psychrometry.py`) so that the chart and the
 * indices agree: dew point as `docs/indices/dew_point.md`, saturation vapour pressure and vapour
 * pressure deficit as `docs/indices/vpd.md`.
 *
 * A relative humidity of 0 % or less is a sensor artefact (the logarithm of the dew point is
 * undefined there); like the Python functions, which return `NaN`, these return `null`.
 */

/** Magnus coefficient `a` (dimensionless), Alduchov & Eskridge (1996); `docs/indices/dew_point.md`. */
export const MAGNUS_A = 17.625;
/** Magnus coefficient `b` in °C, Alduchov & Eskridge (1996); `docs/indices/dew_point.md`. */
export const MAGNUS_B_C = 243.04;

/** Saturation vapour pressure at 0 °C in kPa, FAO-56 eq. 11 (Allen et al., 1998); `docs/indices/vpd.md`. */
export const FAO56_E0_KPA = 0.6108;
/** Exponent coefficient of FAO-56 eq. 11 (dimensionless). */
export const FAO56_A = 17.27;
/** Temperature offset of FAO-56 eq. 11 in °C. */
export const FAO56_B_C = 237.3;

/**
 * Specific gas constant of water vapour, J kg⁻¹ K⁻¹ (461.5; e.g. Wallace & Hobbs, *Atmospheric
 * Science*, 2nd ed., 2006, give 461.51 [source not verified]). Used in the ideal-gas law for
 * absolute humidity.
 */
export const WATER_VAPOUR_GAS_CONSTANT_J_KG_K = 461.5;
/** 0 °C in kelvin. */
export const ZERO_CELSIUS_K = 273.15;

/**
 * Leaf wetness proxy threshold, %: a sample with relative humidity at or above it counts as
 * "leaf probably wet". The same default as `wet_rh_threshold_pct` of the botrytis index
 * (`docs/indices/botrytis_broome.md`; a project default to be tuned, not from literature).
 */
export const LEAF_WET_RH_THRESHOLD_PCT = 90;

const PERCENT = 100;
const PA_PER_KPA = 1000;
const G_PER_KG = 1000;

function isUsable(tempC: number, rhPct: number): boolean {
  return Number.isFinite(tempC) && Number.isFinite(rhPct) && rhPct > 0;
}

/**
 * Dew point (Magnus form, Alduchov & Eskridge 1996):
 * `γ = ln(RH/100) + a·T/(b + T)`, `T_d = b·γ/(a − γ)`.
 *
 * @param tempC - Air temperature, °C.
 * @param rhPct - Relative humidity, %.
 * @returns Dew point in °C, or `null` for `RH <= 0` or a non-finite input.
 */
export function dewPointC(tempC: number, rhPct: number): number | null {
  if (!isUsable(tempC, rhPct)) {
    return null;
  }
  const gamma = Math.log(rhPct / PERCENT) + (MAGNUS_A * tempC) / (MAGNUS_B_C + tempC);
  return (MAGNUS_B_C * gamma) / (MAGNUS_A - gamma);
}

/**
 * Saturation vapour pressure, FAO-56 eq. 11: `e_s = 0.6108·exp(17.27·T/(T + 237.3))`.
 *
 * @param tempC - Air temperature, °C.
 * @returns Saturation vapour pressure in kPa.
 */
export function saturationVapourPressureKpa(tempC: number): number {
  return FAO56_E0_KPA * Math.exp((FAO56_A * tempC) / (tempC + FAO56_B_C));
}

/**
 * Actual vapour pressure from relative humidity, `e_a = e_s(T)·RH/100` (FAO-56).
 *
 * @param tempC - Air temperature, °C.
 * @param rhPct - Relative humidity, %.
 * @returns Actual vapour pressure in kPa, or `null` for `RH <= 0` or a non-finite input.
 */
export function actualVapourPressureKpa(tempC: number, rhPct: number): number | null {
  return isUsable(tempC, rhPct) ? (saturationVapourPressureKpa(tempC) * rhPct) / PERCENT : null;
}

/**
 * Vapour pressure deficit `VPD = e_s(T) − e_a` (FAO-56, `docs/indices/vpd.md`). RH above 100 %
 * gives a negative value and is passed through, as in the Python index.
 *
 * @param tempC - Air temperature, °C.
 * @param rhPct - Relative humidity, %.
 * @returns VPD in kPa, or `null` for `RH <= 0` or a non-finite input.
 */
export function vapourPressureDeficitKpa(tempC: number, rhPct: number): number | null {
  const actualKpa = actualVapourPressureKpa(tempC, rhPct);
  return actualKpa === null ? null : saturationVapourPressureKpa(tempC) - actualKpa;
}

/**
 * Absolute humidity (water vapour density) from the ideal-gas law for water vapour,
 * `ρ_v = e_a / (R_v · T_K)`, with `e_a` from FAO-56 as for the VPD.
 *
 * @param tempC - Air temperature, °C.
 * @param rhPct - Relative humidity, %.
 * @returns Absolute humidity in g/m³, or `null` for `RH <= 0` or a non-finite input.
 */
export function absoluteHumidityGM3(tempC: number, rhPct: number): number | null {
  const actualKpa = actualVapourPressureKpa(tempC, rhPct);
  if (actualKpa === null) {
    return null;
  }
  const densityKgM3 = (actualKpa * PA_PER_KPA) / (WATER_VAPOUR_GAS_CONSTANT_J_KG_K * (tempC + ZERO_CELSIUS_K));
  return densityKgM3 * G_PER_KG;
}

/**
 * Leaf wetness proxy: `RH >= threshold`.
 *
 * @param rhPct - Relative humidity, %.
 * @param thresholdPct - Threshold, %; default {@link LEAF_WET_RH_THRESHOLD_PCT}.
 */
export function isLeafWet(rhPct: number, thresholdPct: number = LEAF_WET_RH_THRESHOLD_PCT): boolean {
  return rhPct >= thresholdPct;
}
