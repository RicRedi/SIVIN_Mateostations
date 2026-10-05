import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet.markercluster';
import 'leaflet.markercluster/dist/MarkerCluster.css';
import type { SensorCatalog, SensorInfo } from '../app/SensorCatalog';
import type { I18n } from '../i18n/I18n';
import { CLUSTER_ICON_SIZE_PX, ClusterIcon } from './ClusterIcon';
import { el } from './dom';
import { STALE_COLOR, TemperatureScale } from './palette';

/** Free tile layers (no API key); attribution as required by the providers. */
const OSM_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const TOPO_URL = 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png';
const TOPO_ATTRIBUTION = `${OSM_ATTRIBUTION}, SRTM | style &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)`;
/** Highest zoom the providers serve (OpenTopoMap stops at 17). */
const OSM_MAX_ZOOM = 19;
const TOPO_MAX_ZOOM = 17;
/** Zoom used when the sensors are too close together to fit meaningfully. */
const MAX_FIT_ZOOM = 16;
const FIT_PADDING_PX = 40;
const MARKER_RADIUS_PX = 10;
const SELECTED_MARKER_RADIUS_PX = 13;
const MARKER_OUTLINE = '#0b0b0b';
const MARKER_OUTLINE_WIDTH_PX = 1.5;
const SELECTED_OUTLINE_WIDTH_PX = 3;
const STALE_DASH = '4 3';
/**
 * Markers closer than this on screen are merged into a cluster: about one marker diameter plus a
 * small margin, so clusters form only where markers would overlap.
 */
const CLUSTER_RADIUS_PX = 2 * MARKER_RADIUS_PX + 8;
const VALUE_DECIMALS = 1;

/** Receives clicks on sensor markers; `compare` is true for ctrl/cmd-click. */
export type SensorClickHandler = (sensorId: string, compare: boolean) => void;

/**
 * Leaflet map of the sensors: circle markers coloured by the latest temperature (grey with a
 * dashed outline when stale or missing), a legend, tooltips and click selection. Markers that
 * would overlap are merged into clusters (`leaflet.markercluster`); a click on a cluster, or
 * Enter on a focused one, zooms in (or spreads the markers at the highest zoom).
 */
export class MapView {
  private readonly map: L.Map;
  private readonly markers = new Map<string, L.CircleMarker>();
  private readonly sensorIds = new Map<L.Layer, string>();
  private readonly clusters: L.MarkerClusterGroup;
  private readonly clusterIcon: ClusterIcon;
  private selectedIds: readonly string[] = [];
  private readonly legend: L.Control;
  private readonly legendBody: HTMLDetailsElement;
  private readonly legendSummary = el('summary', { class: 'map-legend__title' });
  private readonly legendList = el('ul');

  /**
   * @param root - Element the map fills.
   * @param catalog - Sensors to show.
   * @param i18n - Translations and formatting.
   * @param scale - Temperature colour scale.
   * @param timeZone - Display time zone for tooltip times.
   * @param legendCollapsed - Start with the legend collapsed (phones).
   * @param onClick - Called when a marker is clicked or activated with Enter/Space.
   */
  constructor(
    root: HTMLElement,
    private readonly catalog: SensorCatalog,
    private readonly i18n: I18n,
    private readonly scale: TemperatureScale,
    private readonly timeZone: string,
    legendCollapsed: boolean,
    private readonly onClick: SensorClickHandler,
  ) {
    this.legendBody = el('details', { class: 'map-legend', open: !legendCollapsed }, [this.legendSummary, this.legendList]);
    L.DomEvent.disableClickPropagation(this.legendBody);
    this.map = L.map(root, { zoomControl: true });
    const osm = L.tileLayer(OSM_URL, { attribution: OSM_ATTRIBUTION, maxZoom: OSM_MAX_ZOOM });
    const topo = L.tileLayer(TOPO_URL, { attribution: TOPO_ATTRIBUTION, maxZoom: TOPO_MAX_ZOOM });
    osm.addTo(this.map);
    L.control.layers({ OpenStreetMap: osm, OpenTopoMap: topo }, {}, { position: 'topright' }).addTo(this.map);
    this.clusterIcon = new ClusterIcon(i18n);
    this.clusters = L.markerClusterGroup({
      maxClusterRadius: CLUSTER_RADIUS_PX,
      showCoverageOnHover: false,
      iconCreateFunction: (cluster) => this.createClusterIcon(cluster),
    });
    for (const sensor of catalog.sensors) {
      const marker = L.circleMarker([sensor.lat, sensor.lon], this.style(sensor, false));
      marker.on('click', (event: L.LeafletMouseEvent) => {
        onClick(sensor.id, event.originalEvent.ctrlKey || event.originalEvent.metaKey);
      });
      // Leaflet creates a new SVG element each time a marker enters the map (clusters split).
      marker.on('add', () => {
        this.decorate(sensor, marker);
      });
      this.markers.set(sensor.id, marker);
      this.sensorIds.set(marker, sensor.id);
      this.clusters.addLayer(marker);
    }
    this.clusters.addTo(this.map);
    this.legend = new L.Control({ position: 'bottomleft' });
    this.legend.onAdd = () => this.legendBody;
    this.legend.addTo(this.map);
    this.fitToSensors();
    new ResizeObserver(() => {
      this.map.invalidateSize();
    }).observe(root);
  }

  /** Update tooltips, legend, selection highlight and the cluster badges. */
  render(selectedIds: readonly string[]): void {
    this.selectedIds = selectedIds;
    this.map.getContainer().setAttribute('aria-label', this.i18n.t('mapLabel'));
    for (const sensor of this.catalog.sensors) {
      const marker = this.markers.get(sensor.id);
      if (marker !== undefined) {
        const selected = selectedIds.includes(sensor.id);
        marker.setStyle(this.style(sensor, selected));
        marker.setRadius(selected ? SELECTED_MARKER_RADIUS_PX : MARKER_RADIUS_PX);
        marker.bindTooltip(this.tooltip(sensor), { direction: 'top' });
        this.decorate(sensor, marker);
      }
    }
    this.clusters.refreshClusters();
    this.renderLegend();
  }

  /** Accessible name, pressed state and keyboard handling of a marker's element, if on the map. */
  private decorate(sensor: SensorInfo, marker: L.CircleMarker): void {
    const element = marker.getElement();
    if (element !== undefined) {
      this.makeKeyboardAccessible(element, sensor.id);
      element.setAttribute('aria-label', this.accessibleName(sensor));
      element.setAttribute('aria-pressed', String(this.selectedIds.includes(sensor.id)));
    }
  }

  /** Badge of a cluster; highlighted when it hides a selected sensor. */
  private createClusterIcon(cluster: L.MarkerCluster): L.DivIcon {
    const members = cluster.getAllChildMarkers();
    const selectedCount = members.filter((marker) => {
      const id = this.sensorIds.get(marker);
      return id !== undefined && this.selectedIds.includes(id);
    }).length;
    return L.divIcon({
      html: this.clusterIcon.content(members.length),
      className: this.clusterIcon.className(selectedCount),
      iconSize: L.point(CLUSTER_ICON_SIZE_PX, CLUSTER_ICON_SIZE_PX),
    });
  }

  /**
   * Turn the marker's SVG path into a button: focusable, named, Enter/Space selects it and
   * Ctrl/⌘ + Enter/Space toggles it in the comparison (like a click). Leaflet creates the path
   * only once the map has a view, so this runs on render and only once per element.
   */
  private makeKeyboardAccessible(element: Element, sensorId: string): void {
    if (element.getAttribute('role') === 'button') {
      return;
    }
    element.setAttribute('role', 'button');
    element.setAttribute('tabindex', '0');
    element.addEventListener('keydown', (event: Event) => {
      if (!(event instanceof KeyboardEvent)) {
        return;
      }
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        this.onClick(sensorId, event.ctrlKey || event.metaKey);
      }
    });
  }

  private accessibleName(sensor: SensorInfo): string {
    const latest = sensor.latest;
    const value =
      latest?.temp_c === null || latest === null
        ? this.i18n.t('noValue')
        : `${this.i18n.formatNumber(latest.temp_c, VALUE_DECIMALS)} °C${latest.stale ? ` (${this.i18n.t('stale')})` : ''}`;
    return `${sensor.label}: ${value}`;
  }

  /** Recompute the map size after its container changed. */
  invalidateSize(): void {
    this.map.invalidateSize();
  }

  /** Zoom and pan so that all sensors are visible. */
  fitToSensors(): void {
    const points = this.catalog.sensors.map((s): L.LatLngTuple => [s.lat, s.lon]);
    if (points.length > 0) {
      const legendHeightPx = this.legendBody.offsetHeight;
      this.map.fitBounds(L.latLngBounds(points), {
        paddingTopLeft: [FIT_PADDING_PX, FIT_PADDING_PX],
        paddingBottomRight: [FIT_PADDING_PX, FIT_PADDING_PX + legendHeightPx],
        maxZoom: MAX_FIT_ZOOM,
      });
    }
  }

  private style(sensor: SensorInfo, selected: boolean): L.CircleMarkerOptions {
    const tempC = this.currentTemp(sensor);
    return {
      radius: selected ? SELECTED_MARKER_RADIUS_PX : MARKER_RADIUS_PX,
      fillColor: tempC === null ? STALE_COLOR : this.scale.colorFor(tempC),
      fillOpacity: 1,
      color: MARKER_OUTLINE,
      weight: selected ? SELECTED_OUTLINE_WIDTH_PX : MARKER_OUTLINE_WIDTH_PX,
      dashArray: tempC === null ? STALE_DASH : undefined,
    };
  }

  /** Latest temperature, or null when missing or stale. */
  private currentTemp(sensor: SensorInfo): number | null {
    const latest = sensor.latest;
    return latest === null || latest.stale ? null : latest.temp_c;
  }

  private tooltip(sensor: SensorInfo): HTMLElement {
    const latest = sensor.latest;
    const lines: (string | Node)[] = [el('strong', {}, [sensor.label])];
    if (latest?.temp_c === null || latest === null) {
      lines.push(el('br'), this.i18n.t('noValue'));
    } else {
      const value = `${this.i18n.formatNumber(latest.temp_c, VALUE_DECIMALS)} °C`;
      lines.push(el('br'), latest.stale ? `${value} (${this.i18n.t('stale')})` : value);
    }
    if (latest !== null) {
      lines.push(el('br'), this.i18n.formatDateTime(latest.t, this.timeZone));
    }
    return el('div', {}, lines);
  }

  private renderLegend(): void {
    const rows = [...this.scale.classes].reverse().map((cls) => {
      const swatch = el('span', { class: 'map-legend__swatch' });
      swatch.style.background = cls.color;
      return el('li', {}, [swatch, this.classLabel(cls.lowerC, cls.upperC)]);
    });
    const staleSwatch = el('span', { class: 'map-legend__swatch map-legend__swatch--stale' });
    staleSwatch.style.background = STALE_COLOR;
    rows.push(el('li', {}, [staleSwatch, this.i18n.t('legendStale')]));
    this.legendSummary.textContent = `${this.i18n.t('legendTitle')} (°C)`;
    this.legendList.replaceChildren(...rows);
  }

  private classLabel(lowerC: number | null, upperC: number | null): string {
    if (lowerC === null) {
      return `< ${upperC ?? ''}`;
    }
    return upperC === null ? `≥ ${lowerC}` : `${lowerC} – ${upperC}`;
  }
}
