import type { ResolutionChoice, WindowSpec } from '../domain/WindowSpec';
import { DEFAULT_WINDOW } from '../domain/WindowSpec';
import type { Language } from '../i18n/languages';
import { DEFAULT_LANGUAGE } from '../i18n/languages';
import { Store } from './Store';

/** Everything the URL hash keeps shareable. */
export interface AppState {
  /** Selected sensors in selection order; the first one is shown in the detail panel. */
  readonly selectedSensorIds: readonly string[];
  readonly window: WindowSpec;
  readonly resolution: ResolutionChoice;
  readonly language: Language;
}

export const DEFAULT_APP_STATE: AppState = {
  selectedSensorIds: [],
  window: DEFAULT_WINDOW,
  resolution: 'auto',
  language: DEFAULT_LANGUAGE,
};

export type AppStore = Store<AppState>;

/**
 * Most sensors compared in one chart: the size of the colour-blind-checked categorical palette
 * (see `ui/palette.ts`), so every compared sensor keeps a distinct colour.
 */
export const MAX_COMPARED_SENSORS = 8;

/** Selection after a plain click: only `sensorId`. */
export function selectOnly(sensorId: string): readonly string[] {
  return [sensorId];
}

/**
 * Selection after a comparison click: removes `sensorId` if selected, otherwise appends it
 * unless `max` sensors are already selected.
 */
export function toggleInSelection(
  selected: readonly string[],
  sensorId: string,
  max: number = MAX_COMPARED_SENSORS,
): readonly string[] {
  if (selected.includes(sensorId)) {
    return selected.filter((id) => id !== sensorId);
  }
  return selected.length >= max ? selected : [...selected, sensorId];
}
