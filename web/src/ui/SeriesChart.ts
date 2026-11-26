import uPlot, { type AlignedData, type Options } from 'uplot';
import 'uplot/dist/uPlot.min.css';
import type { ChartData } from '../app/ChartDataLoader';
import type { ChartView } from '../app/ChartPresenter';
import type { QuantityRegistry } from '../app/ChartQuantities';
import type { SensorCatalog } from '../app/SensorCatalog';
import { DEFAULT_QUANTITIES, type QuantityId } from '../domain/quantities';
import type { TimeWindow } from '../domain/TimeWindow';
import type { TimeZone } from '../domain/TimeZone';
import { MS_PER_SECOND, SECONDS_PER_DAY } from '../domain/units';
import { minViewSpanS } from '../domain/ViewRange';
import type { I18n } from '../i18n/I18n';
import { ChartModel } from './ChartModel';
import { ChartSeriesFactory } from './ChartSeriesFactory';
import type { ChartSnapshot } from './ChartToolbar';
import { el } from './dom';
import { EventMarkers } from './EventMarkers';
import type { QuantityLabels } from './QuantityLabels';
import type { SensorColors } from './SensorColors';
import { WetnessBands } from './WetnessBands';
import { ZoomPanPlugin, type FrameScheduler } from './ZoomPanPlugin';

/** Chart height in px on wide and on narrow containers. */
const CHART_HEIGHT_PX = 300;
const CHART_HEIGHT_NARROW_PX = 220;
/** Smallest plot height in the maximised dialog, px. */
const MIN_FILL_HEIGHT_PX = 200;
/** Containers narrower than this get the shorter chart and narrower axes (phones). */
const NARROW_WIDTH_PX = 500;
/** The maximised dialog; inside it the chart fills the available height. */
const DIALOG_SELECTOR = '.chart-dialog';
const FALLBACK_COLOR = '#52514e';

/** Toolbar-relevant state of the chart. */
export interface ChartViewState {
  readonly zoomed: boolean;
  readonly exportable: boolean;
}

/**
 * uPlot chart of the shown quantities for one or more sensors: temperature and dew point on the
 * left axis (°C), relative humidity on the right axis (%), at most one more quantity on a third
 * axis (right), leaf wetness as bands; one colour per sensor, one line style per quantity. Sensor
 * events are markers, `off_site` periods grey bands in which the sensor's series are not drawn.
 * Times are shown in the display time zone; `null` values are drawn as gaps.
 *
 * Wheel zoom, drag pan and double-click reset are the {@link ZoomPanPlugin}; the zoom is kept
 * when the chart is redrawn (language, quantities) and reset when new data arrive. Inside the
 * maximised dialog the plot fills the available height. Data shaping is {@link ChartModel}.
 */
export class SeriesChart implements ChartView {
  private readonly message = el('p', { class: 'chart__message', role: 'status' });
  private readonly failures = el('ul', { class: 'chart__failures' });
  private readonly plotHost = el('div', { class: 'chart__plot' });
  private readonly markers: EventMarkers;
  private readonly wetness: WetnessBands;
  private readonly zoomPan: ZoomPanPlugin;
  private readonly factory: ChartSeriesFactory;
  private plot: uPlot | null = null;
  private data: ChartData | null = null;
  private model: ChartModel | null = null;
  private quantities: readonly QuantityId[] = DEFAULT_QUANTITIES;
  /** The window whose zoom {@link zoomPan} holds; another window (bounds or resolution) resets the zoom. */
  private zoomedWindow: TimeWindow | null = null;

  /**
   * @param root - Container element; the chart follows its width.
   * @param i18n - Translations and number formatting.
   * @param catalog - Sensor labels.
   * @param colors - Line colours of the compared sensors.
   * @param registry - The chart quantities.
   * @param labels - Quantity labels.
   * @param zone - Display time zone (from the manifest).
   * @param frames - Animation frames for smooth wheel zoom.
   * @param onState - Called when zoom or exportability change (for the toolbar).
   */
  constructor(
    private readonly root: HTMLElement,
    private readonly i18n: I18n,
    private readonly catalog: SensorCatalog,
    private readonly colors: SensorColors,
    private readonly registry: QuantityRegistry,
    labels: QuantityLabels,
    private readonly zone: TimeZone,
    frames: FrameScheduler,
    private readonly onState: (state: ChartViewState) => void,
  ) {
    this.markers = new EventMarkers(i18n, catalog, zone);
    this.wetness = new WetnessBands((id) => this.color(id));
    this.factory = new ChartSeriesFactory(i18n, catalog, registry, labels, (id) => this.color(id));
    this.zoomPan = new ZoomPanPlugin(() => {
      this.notify();
    }, frames);
    root.append(this.message, this.failures, this.plotHost);
    new ResizeObserver(() => {
      this.resize();
    }).observe(root);
  }

  showMessage(text: string): void {
    this.message.textContent = text;
    this.message.hidden = false;
  }

  showError(text: string): void {
    this.data = null;
    this.destroyPlot();
    this.failures.replaceChildren();
    this.showMessage(text);
    this.notify();
  }

  showData(data: ChartData): void {
    this.data = data;
    this.render();
  }

  /** Show other quantities (keeps the zoom). */
  setQuantities(quantities: readonly QuantityId[]): void {
    this.quantities = quantities;
    this.render();
  }

  /** What is shown now, for the CSV export; `null` without a chart. */
  snapshot(): ChartSnapshot | null {
    return this.model === null || this.plot === null ? null : { model: this.model, view: this.zoomPan.view };
  }

  /** Show the whole loaded window. */
  resetZoom(): void {
    this.zoomPan.reset();
  }

  /** Redraw with the current language and quantities. */
  render(): void {
    this.destroyPlot();
    const data = this.data;
    if (data === null) {
      this.notify();
      return;
    }
    this.renderFailures(data);
    const model = ChartModel.build(data, this.registry.select(this.quantities));
    this.message.textContent = model.hasValues ? '' : this.i18n.t('noData');
    this.message.hidden = model.hasValues || data.sensors.length === 0;
    if (data.sensors.length > 0) {
      const keep = this.zoomedWindow?.equals(data.window) === true ? this.zoomPan.view : undefined;
      this.zoomPan.configure(model.bounds, minViewSpanS(data.window.resolution), keep);
      this.zoomedWindow = data.window;
      this.markers.setEvents(model.events);
      this.markers.setBands(model.offSiteBands);
      this.wetness.setLanes(model.wetLanes);
      const plotData = [model.t, ...model.columns.map((column) => column.values)] as unknown as AlignedData;
      this.plot = new uPlot(this.options(model), plotData, this.plotHost);
      this.plot.ctx.canvas.setAttribute('role', 'img');
      this.plot.ctx.canvas.setAttribute('aria-label', this.i18n.t('chartLabel'));
      this.markers.attach(this.plot);
      this.model = model;
      this.resize();
    }
    this.notify();
  }

  private notify(): void {
    const snapshot = this.snapshot();
    this.onState({ zoomed: snapshot !== null && this.zoomPan.isZoomed, exportable: snapshot?.model.hasValues === true });
  }

  private renderFailures(data: ChartData): void {
    this.failures.replaceChildren(
      ...data.failures.map((failure) =>
        el('li', { class: 'chart__failure', role: 'alert' }, [
          this.i18n.t('sensorLoadError', {
            sensor: this.catalog.get(failure.sensorId)?.label ?? failure.sensorId,
            message: failure.message,
          }),
        ]),
      ),
    );
  }

  private options(model: ChartModel): Options {
    const narrow = this.root.clientWidth < NARROW_WIDTH_PX;
    return {
      width: this.width(),
      height: this.height(),
      tzDate: (ts) => uPlot.tzDate(new Date(ts * MS_PER_SECOND), this.zone.name),
      scales: { x: { time: true, range: this.zoomPan.xRange }, ...this.factory.scales(model) },
      series: [
        {
          label: this.i18n.t('time'),
          value: (_, t: number | null) => (t === null ? '–' : this.i18n.formatDateTime(t, this.zone.name)),
        },
        ...model.columns.map((column) => this.factory.series(column, model.window.resolution)),
      ],
      axes: [
        { values: (_, ticks, _axis, _space, incrS) => ticks.map((t) => this.timeTick(t, incrS)) },
        ...this.factory.axes(model, narrow),
      ],
      cursor: { bind: this.zoomPan.cursorBindings(), drag: { x: true, y: false, setScale: false } },
      plugins: [this.zoomPan.plugin()],
      hooks: {
        drawClear: [
          (u) => {
            this.markers.drawBands(u);
            this.wetness.draw(u);
          },
        ],
        draw: [
          (u) => {
            this.markers.drawLines(u);
          },
        ],
        setSize: [
          (u) => {
            this.markers.place(u);
          },
        ],
        setScale: [
          (u, key) => {
            if (key === 'x') {
              this.markers.place(u);
            }
          },
        ],
      },
      legend: { live: true },
    };
  }

  private color(sensorId: string): string {
    return this.colors.colorFor(sensorId) ?? FALLBACK_COLOR;
  }

  /** Day and month at local midnight or for steps of a day and more, otherwise HH:MM. */
  private timeTick(t: number, incrS: number): string {
    const local = this.zone.toLocal(t);
    const isMidnight = local.hour === 0 && local.minute === 0;
    return incrS >= SECONDS_PER_DAY || isMidnight
      ? this.i18n.formatDayMonth(t, this.zone.name)
      : this.i18n.formatTime(t, this.zone.name);
  }

  private destroyPlot(): void {
    this.plot?.destroy();
    this.plot = null;
    this.model = null;
  }

  private width(): number {
    return Math.max(1, this.root.clientWidth);
  }

  private height(): number {
    if (this.root.closest(DIALOG_SELECTOR) !== null) {
      const legendPx = this.plot?.root.querySelector<HTMLElement>('.u-legend')?.offsetHeight ?? 0;
      return Math.max(MIN_FILL_HEIGHT_PX, this.plotHost.clientHeight - legendPx);
    }
    return this.root.clientWidth < NARROW_WIDTH_PX ? CHART_HEIGHT_NARROW_PX : CHART_HEIGHT_PX;
  }

  /**
   * Fit the plot to its container. In the dialog the height depends on the legend, whose height
   * depends on the width, so the size is applied a second time if the legend changed.
   */
  private resize(): void {
    const plot = this.plot;
    if (plot === null) {
      return;
    }
    plot.setSize({ width: this.width(), height: this.height() });
    const height = this.height();
    if (height !== plot.height) {
      plot.setSize({ width: this.width(), height });
    }
  }
}
