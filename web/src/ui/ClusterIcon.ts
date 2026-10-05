import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import { STALE_COLOR, type TemperatureScale } from './palette';

/** Diameter of a cluster badge on the map, px (a little larger than a selected marker). */
export const CLUSTER_ICON_SIZE_PX = 34;

/** Dark and light text on a badge; the one with the higher WCAG contrast is used. */
const DARK_INK = '#0b0b0b';
const LIGHT_INK = '#ffffff';
/** WCAG 2.x relative luminance: sRGB channel linearisation constants. */
const SRGB_LINEAR_LIMIT = 0.04045;
const SRGB_LINEAR_DIVISOR = 12.92;
const SRGB_OFFSET = 0.055;
const SRGB_SCALE = 1.055;
const SRGB_GAMMA = 2.4;
const LUMINANCE_WEIGHTS = [0.2126, 0.7152, 0.0722] as const;
/** WCAG contrast ratio offset (`(L1 + 0.05) / (L2 + 0.05)`). */
const CONTRAST_OFFSET = 0.05;
const HEX_COLOR = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i;
const CHANNEL_MAX = 255;
const HEX_RADIX = 16;

const BASE_CLASS = 'sensor-cluster';
const SELECTED_CLASS = 'sensor-cluster--selected';
const NO_VALUE_CLASS = 'sensor-cluster--no-value';

/** WCAG relative luminance of a `#rrggbb` colour (0 = black, 1 = white). */
export function relativeLuminance(hex: string): number {
  const match = HEX_COLOR.exec(hex);
  if (match === null) {
    throw new RangeError(`Not a #rrggbb colour: ${hex}`);
  }
  const channels = match.slice(1).map((part) => {
    const value = parseInt(part, HEX_RADIX) / CHANNEL_MAX;
    return value <= SRGB_LINEAR_LIMIT ? value / SRGB_LINEAR_DIVISOR : ((value + SRGB_OFFSET) / SRGB_SCALE) ** SRGB_GAMMA;
  });
  return channels.reduce((sum, value, i) => sum + value * (LUMINANCE_WEIGHTS[i] ?? 0), 0);
}

/** Text colour (dark or white) with the higher WCAG contrast on `background`. */
export function inkFor(background: string): string {
  const luminance = relativeLuminance(background);
  const darkContrast = (luminance + CONTRAST_OFFSET) / (relativeLuminance(DARK_INK) + CONTRAST_OFFSET);
  const lightContrast = (relativeLuminance(LIGHT_INK) + CONTRAST_OFFSET) / (luminance + CONTRAST_OFFSET);
  return darkContrast >= lightContrast ? DARK_INK : LIGHT_INK;
}

/** Mean of the values that are present; `null` when none is. */
export function meanOfPresent(values: readonly (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length === 0 ? null : present.reduce((sum, value) => sum + value, 0) / present.length;
}

/** How a cluster badge looks. */
export interface ClusterAppearance {
  readonly className: string;
  readonly background: string;
  readonly ink: string;
}

/**
 * A marker-cluster badge: the number of sensors, an accessible name ("Skupina čidel: 5 –
 * přiblížit"), and the colour of the **mean latest temperature** of the members on the same
 * scale as the single markers, so the temperature picture stays visible when zoomed out. Grey
 * with a dashed outline only when no member has a current value. A ring marks a cluster that
 * hides a selected sensor.
 */
export class ClusterIcon {
  constructor(
    private readonly i18n: I18n,
    private readonly scale: TemperatureScale,
  ) {}

  /**
   * @param tempsC - Current temperature of each member in °C (`null` = stale or missing).
   * @param selectedCount - Members that are selected.
   */
  appearance(tempsC: readonly (number | null)[], selectedCount: number): ClusterAppearance {
    const meanC = meanOfPresent(tempsC);
    const background = meanC === null ? STALE_COLOR : this.scale.colorFor(meanC);
    const classes = [BASE_CLASS];
    if (meanC === null) {
      classes.push(NO_VALUE_CLASS);
    }
    if (selectedCount > 0) {
      classes.push(SELECTED_CLASS);
    }
    return { className: classes.join(' '), background, ink: inkFor(background) };
  }

  /** Badge content: the count for sight, the accessible name for screen readers. */
  content(count: number, appearance: ClusterAppearance): HTMLElement {
    const body = el('span', { class: 'sensor-cluster__body' }, [
      el('span', { 'aria-hidden': 'true' }, [String(count)]),
      el('span', { class: 'visually-hidden' }, [this.i18n.t('clusterLabel', { count })]),
    ]);
    body.style.background = appearance.background;
    body.style.color = appearance.ink;
    return body;
  }
}
