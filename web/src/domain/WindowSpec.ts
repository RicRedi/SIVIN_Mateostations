import type { Resolution } from './TimeWindow';

/** Presets measured back from the end of the available data. */
export const RELATIVE_PRESETS = ['24h', '7d', '30d'] as const;
export type RelativePreset = (typeof RELATIVE_PRESETS)[number];

/**
 * What the user asked for, independent of the data: a relative preset, a growing season of a
 * year, or a custom range of local calendar days (both inclusive, `YYYY-MM-DD`).
 */
export type WindowSpec =
  | { readonly kind: RelativePreset }
  | { readonly kind: 'season'; readonly year: number }
  | { readonly kind: 'custom'; readonly from: string; readonly to: string };

export type WindowKind = WindowSpec['kind'];

/** `auto` lets {@link ResolutionPolicy} pick a resolution from the window length. */
export type ResolutionChoice = Resolution | 'auto';

export const DEFAULT_WINDOW: WindowSpec = { kind: '7d' };
