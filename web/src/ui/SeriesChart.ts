import uPlot, { type AlignedData, type Options, type Series } from 'uplot';
import 'uplot/dist/uPlot.min.css';
import type { ChartData, SensorChartData } from '../app/ChartDataLoader';
import type { ChartView } from '../app/ChartPresenter';
import type { SensorCatalog } from '../app/SensorCatalog';
import type { VariableSpec } from '../contract';
import { alignSeries } from '../domain/alignSeries';
import type { TimeZone } from '../domain/TimeZone';
import { MS_PER_SECOND, SECONDS_PER_DAY } from '../domain/units';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import { EventMarkers, offSiteBands, withoutBands } from './EventMarkers';
import type { SensorColors } from './SensorColors';

/** Chart height in px on wide and on narrow containers. */
const CHART_HEIGHT_PX = 300;
const CHART_HEIGHT_NARROW_PX = 220;
/** Containers narrower than this get the shorter chart (phones). */
const NARROW_WIDTH_PX = 500;
/** Relative humidity axis range, %. */
const RH_RANGE_PCT: [number, number] = [0, 100];
const TEMP_LINE_WIDTH_PX = 2;
const RH_LINE_WIDTH_PX = 1.5;
const RH_DASH_PX = [6, 4];
const VALUE_DECIMALS = 1;
const FALLBACK_COLOR = '#52514e';
/** `uPlot.Axis.Side.Right`; the ambient const enum cannot be referenced under `isolatedModules`. */
// eslint-disable-next-line @typescript-eslint/no-unsafe-enum-assignment -- numeric value of Side.Right
const AXIS_SIDE_RIGHT = 1 as uPlot.Axis.Side;

/**
 * uPlot chart of temperature (left axis, °C) and relative humidity (right axis, %) for one or
 * more sensors, with sensor events as markers and `off_site` periods as grey bands in which the
 * sensor's lines are not drawn. Times are shown in the display time zone; `null` values are drawn
 * as gaps. Sensors that failed to load are listed with their error.
 */
export class SeriesChart implements ChartView {
  private readonly message = el('p', { class: 'chart__message', role: 'status' });
  private readonly failures = el('ul', { class: 'chart__failures' });
  private readonly plotHost = el('div', { class: 'chart__plot' });
  private readonly markers: EventMarkers;
  private plot: uPlot | null = null;
  private data: ChartData | null = null;

  /**
   * @param root - Container element; the chart follows its width.
   * @param i18n - Translations and number formatting.
   * @param catalog - Sensor labels.
   * @param colors - Line colours of the compared sensors.
   * @param variables - Variable specs from the manifest (labels and units).
   * @param zone - Display time zone (from the manifest).
   */
  constructor(
    private readonly root: HTMLElement,
    private readonly i18n: I18n,
    private readonly catalog: SensorCatalog,
    private readonly colors: SensorColors,
    private readonly variables: readonly VariableSpec[],
    private readonly zone: TimeZone,
  ) {
    this.markers = new EventMarkers(i18n, catalog, zone);
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
  }

  showData(data: ChartData): void {
    this.data = data;
    this.render();
  }

  /** Redraw with the current language. */
  render(): void {
    this.destroyPlot();
    const data = this.data;
    if (data === null) {
      return;
    }
    this.renderFailures(data);
    const hasValues = data.sensors.some((s) => s.temp_c.validCount + s.rh_pct.validCount > 0);
    this.message.textContent = hasValues ? '' : this.i18n.t('noData');
    this.message.hidden = hasValues || data.sensors.length === 0;
    if (data.sensors.length === 0) {
      return;
    }
    const events = data.sensors.flatMap((s) => s.events.map((event) => ({ event, sensorId: s.sensorId })));
    const bands = offSiteBands(events, data.window.startT, data.window.endT);
    const aligned = alignSeries(
      data.sensors.flatMap((s) => {
        const own = bands.filter((band) => band.sensorId === s.sensorId);
        return [withoutBands(s.temp_c, own), withoutBands(s.rh_pct, own)];
      }),
    );
    const plotData = [aligned.t, ...aligned.columns] as unknown as AlignedData;
    this.markers.setEvents(events);
    this.markers.setBands(bands);
    this.plot = new uPlot(this.options(data), plotData, this.plotHost);
    this.plot.ctx.canvas.setAttribute('role', 'img');
    this.plot.ctx.canvas.setAttribute('aria-label', this.i18n.t('chartLabel'));
    this.markers.attach(this.plot);
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

  private options(data: ChartData): Options {
    const tempUnit = this.unit('temp_c', '°C');
    const rhUnit = this.unit('rh_pct', '%');
    return {
      width: this.width(),
      height: this.height(),
      tzDate: (ts) => uPlot.tzDate(new Date(ts * MS_PER_SECOND), this.zone.name),
      scales: {
        x: { time: true, range: [data.window.startT, data.window.endT] },
        rh: { range: RH_RANGE_PCT },
      },
      series: [
        {
          label: this.i18n.t('time'),
          value: (_, t: number | null) => (t === null ? '–' : this.i18n.formatDateTime(t, this.zone.name)),
        },
        ...data.sensors.flatMap((sensor) => this.sensorSeries(sensor, tempUnit, rhUnit)),
      ],
      axes: [
        { values: (_, ticks, _axis, _space, incrS) => ticks.map((t) => this.timeTick(t, incrS)) },
        { scale: 'temp', label: tempUnit, values: (_, ticks) => ticks.map((v) => this.i18n.formatNumber(v, VALUE_DECIMALS, 0)) },
        { scale: 'rh', side: AXIS_SIDE_RIGHT, label: rhUnit, grid: { show: false } },
      ],
      hooks: {
        drawClear: [
          (u) => {
            this.markers.drawBands(u);
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
      },
      legend: { live: true },
    };
  }

  private sensorSeries(sensor: SensorChartData, tempUnit: string, rhUnit: string): Series[] {
    const name = this.catalog.get(sensor.sensorId)?.label ?? sensor.sensorId;
    const color = this.colors.colorFor(sensor.sensorId) ?? FALLBACK_COLOR;
    const value = (unit: string) => (_: uPlot, v: number | null) =>
      v === null ? '–' : `${this.i18n.formatNumber(v, VALUE_DECIMALS)} ${unit}`;
    return [
      { label: `${name} · ${this.variableLabel('temp_c')}`, scale: 'temp', stroke: color, width: TEMP_LINE_WIDTH_PX, spanGaps: false, value: value(tempUnit) },
      { label: `${name} · ${this.variableLabel('rh_pct')}`, scale: 'rh', stroke: color, width: RH_LINE_WIDTH_PX, dash: RH_DASH_PX, spanGaps: false, value: value(rhUnit) },
    ];
  }

  /** Day and month at local midnight or for steps of a day and more, otherwise HH:MM. */
  private timeTick(t: number, incrS: number): string {
    const local = this.zone.toLocal(t);
    const isMidnight = local.hour === 0 && local.minute === 0;
    return incrS >= SECONDS_PER_DAY || isMidnight
      ? this.i18n.formatDayMonth(t, this.zone.name)
      : this.i18n.formatTime(t, this.zone.name);
  }

  private variableLabel(id: string): string {
    const variable = this.variables.find((v) => v.id === id);
    return variable ? this.i18n.label(variable.label, id) : id;
  }

  private unit(id: string, fallback: string): string {
    return this.variables.find((v) => v.id === id)?.unit ?? fallback;
  }

  private destroyPlot(): void {
    this.plot?.destroy();
    this.plot = null;
  }

  private width(): number {
    return Math.max(1, this.root.clientWidth);
  }

  private height(): number {
    return this.root.clientWidth < NARROW_WIDTH_PX ? CHART_HEIGHT_NARROW_PX : CHART_HEIGHT_PX;
  }

  private resize(): void {
    this.plot?.setSize({ width: this.width(), height: this.height() });
  }
}
