import type { ChartPresenter } from '../app/ChartPresenter';
import type { SensorCatalog, SensorInfo } from '../app/SensorCatalog';
import type { I18n } from '../i18n/I18n';
import type { LanguagePreference } from '../i18n/LanguagePreference';
import { selectOnly, toggleInSelection, type AppState, type AppStore } from '../state/AppState';
import type { HeaderView } from './HeaderView';
import type { MapView } from './MapView';
import type { SensorList } from './SensorList';
import type { SensorPanel } from './SensorPanel';
import type { SeriesChart } from './SeriesChart';
import type { TimeWindowControl, WindowChange } from './TimeWindowControl';

/** The UI components the application coordinates. */
export interface AppViews {
  readonly header: HeaderView;
  readonly map: MapView;
  readonly panel: SensorPanel;
  readonly list: SensorList;
  readonly windowControl: TimeWindowControl;
  readonly chart: SeriesChart;
}

/**
 * Coordinates state and views: user actions update the store, store changes re-render the views
 * and reload the chart when the selection or the window changed.
 */
export class App {
  private limitReached = false;

  constructor(
    private readonly store: AppStore,
    private readonly catalog: SensorCatalog,
    private readonly i18n: I18n,
    private readonly preference: LanguagePreference,
    private readonly presenter: ChartPresenter,
    private readonly views: AppViews,
  ) {
    store.subscribe((state, previous) => {
      this.onStateChange(state, previous);
    });
  }

  /** Render everything once and load the chart for the initial state. */
  start(): void {
    this.renderAll(this.store.state);
    this.views.map.invalidateSize();
    this.views.map.fitToSensors();
    void this.presenter.refresh(this.store.state, this.store.state.selectedSensorIds);
  }

  /** Marker click: plain click selects one sensor, `compare` toggles it in the comparison. */
  readonly onSensorClick = (sensorId: string, compare: boolean): void => {
    this.select(compare ? this.toggled(sensorId) : selectOnly(sensorId));
  };

  /** Checkbox in the sensor list: toggles the sensor in the comparison. */
  readonly onSensorToggle = (sensorId: string): void => {
    this.select(this.toggled(sensorId));
  };

  readonly onWindowChange = (change: WindowChange): void => {
    this.store.update(change);
  };

  readonly onLanguage = (language: AppState['language']): void => {
    this.store.update({ language });
  };

  private toggled(sensorId: string): readonly string[] {
    const current = this.store.state.selectedSensorIds;
    const next = toggleInSelection(current, sensorId);
    this.limitReached = next === current;
    return next;
  }

  private select(sensorIds: readonly string[]): void {
    if (sensorIds === this.store.state.selectedSensorIds) {
      this.renderAll(this.store.state);
      return;
    }
    this.store.update({ selectedSensorIds: sensorIds });
  }

  private onStateChange(state: AppState, previous: AppState): void {
    const known = this.catalog.knownIds(state.selectedSensorIds);
    if (known.length !== state.selectedSensorIds.length) {
      this.store.update({ selectedSensorIds: known });
      return;
    }
    if (state.language !== previous.language) {
      this.i18n.setLanguage(state.language);
      this.preference.save(state.language);
      this.views.header.render();
      this.views.chart.render();
    }
    this.renderAll(state);
    const reload =
      state.selectedSensorIds !== previous.selectedSensorIds ||
      state.window !== previous.window ||
      state.resolution !== previous.resolution;
    if (reload) {
      void this.presenter.refresh(state, state.selectedSensorIds);
    }
  }

  private renderAll(state: AppState): void {
    const selected = state.selectedSensorIds
      .map((id) => this.catalog.get(id))
      .filter((sensor): sensor is SensorInfo => sensor !== undefined);
    this.views.map.render(state.selectedSensorIds);
    this.views.list.render(state.selectedSensorIds);
    this.views.panel.render(selected, this.limitReached);
    this.views.windowControl.render({
      spec: state.window,
      resolution: state.resolution,
      window: this.presenter.windowFor(state),
    });
    this.limitReached = false;
  }
}
