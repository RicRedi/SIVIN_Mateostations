/**
 * Decimal places of a copied or displayed position. Six decimals of a degree are about 0.11 m of
 * latitude, finer than the accuracy of a sensor placement; the registry
 * coordinates have the same precision.
 */
export const POSITION_DECIMALS = 6;

/**
 * Format a WGS 84 position as `"<lat>, <lon>"` with {@link POSITION_DECIMALS} decimals and a
 * decimal point, independent of the UI language, so navigation and map apps accept the pasted text.
 *
 * @param latDeg - Latitude in decimal degrees (north positive).
 * @param lonDeg - Longitude in decimal degrees (east positive).
 * @returns E.g. `"48.880215, 16.673002"`.
 */
export function formatPosition(latDeg: number, lonDeg: number): string {
  return `${formatDegrees(latDeg)}, ${formatDegrees(lonDeg)}`;
}

/** `toFixed` with a negative zero (e.g. -0.0000001 → "-0.000000") written without the sign. */
function formatDegrees(valueDeg: number): string {
  const text = valueDeg.toFixed(POSITION_DECIMALS);
  return Number(text) === 0 ? (0).toFixed(POSITION_DECIMALS) : text;
}
