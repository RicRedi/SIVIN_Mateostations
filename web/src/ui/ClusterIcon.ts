import type { I18n } from '../i18n/I18n';
import { el } from './dom';

/** Diameter of a cluster badge on the map, px (a little larger than a selected marker). */
export const CLUSTER_ICON_SIZE_PX = 34;

const BASE_CLASS = 'sensor-cluster';
const SELECTED_CLASS = 'sensor-cluster--selected';

/**
 * Content of a marker-cluster badge: the number of sensors, an accessible name ("Group of 5
 * sensors – zoom in") and a highlight ring when the cluster hides a selected sensor. The badge
 * is neutral grey on purpose: the temperature colours belong to single sensors.
 */
export class ClusterIcon {
  constructor(private readonly i18n: I18n) {}

  /** CSS classes of the badge (Leaflet `divIcon` `className`). */
  className(selectedCount: number): string {
    return selectedCount > 0 ? `${BASE_CLASS} ${SELECTED_CLASS}` : BASE_CLASS;
  }

  /** Badge content: the count for sight, the accessible name for screen readers. */
  content(count: number): HTMLElement {
    return el('span', { class: 'sensor-cluster__body' }, [
      el('span', { 'aria-hidden': 'true' }, [String(count)]),
      el('span', { class: 'visually-hidden' }, [this.i18n.t('clusterLabel', { count })]),
    ]);
  }
}
