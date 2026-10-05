import uPlot, { type AlignedData, type Options, type Series } from 'uplot';
import 'uplot/dist/uPlot.min.css';
import type { ChartData, SensorChartData } from '../app/ChartDataLoader';
import type { SensorCatalog } from '../app/SensorCatalog';
import type { ChartView } from '../app/ChartPresenter';
import type { SensorEvent, VariableSpec } from '../contract';
import { alignSeries } from '../domain/alignSeries';
import type { TimeZone } from '../domain/TimeZone';
import { MS_PER_SECOND, SECONDS_PER_DAY } from '../domain/units';
import type { MessageKey } from '../i18n/cs';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import { sensorColor } from './palette';

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
const EVENT_LINE_DASH_PX = [3, 3];
const EVENT_LINE_COLOR = '#52514e';
const VALUE_DECIMALS = 1;
const PERCENT = 100;
/** `uPlot.Axis.Side.Right`; the ambient const enum cannot be referenced under `isolatedModules`. */
// eslint-disable-next-line @typescript-eslint/no-unsafe-enum-assignment -- numeric value of Side.Right
const AXIS_SIDE_RIGHT = 1 as uPlot.Axis.Side;

const EVENT_LABELS: Readonly<Record<SensorEvent['type'], MessageKey>> = {
  deployment: 'eventDeployment',
  retrieval: 'eventRetrieval',
  step: 'eventStep',
};

/**
 * uPlot chart of temperature (left axis, °C) and relative humidity (right axis, %) for one or
 * more sensors, with sensor events as dashed vertical markers. Times are shown in the display
 * time zone; `null` values are drawn as gaps.
 */
export class SeriesChart implements ChartView {
  private readonly message = el('p', { class: 'chart__message', role: 'status' });
  private readonly plotHost = el('div', { class: 'chart__plot' });
  private readonly markers = el('div', { class: 'chart__events' });
  private plot: uPlot | null = null;
  private data: ChartData | null = null;

  /**
   * @param root - Container element; the chart follows its width.
   * @param i18n - Translations and number formatting.
   * @param catalog - Sensor labels and colours.
   * @param variables - Variable specs from the manifest (labels and units).
   * @param zone - Display time zone (from the manifest).
   */
  constructor(
    private readonly root: HTMLElement,
    private readonly i18n: I18n,
    private readonly catalog: SensorCatalog,
    private readonly variables: readonly VariableSpec[],
    private readonly zone: TimeZone,
  ) {
    this.plotHost.setAttribute('role', 'img');
    root.append(this.message, this.plotHost);
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
    this.plot?.destroy();
    this.plot = null;
    this.showMessage(text);
  }

  showData(data: ChartData): void {
    this.data = data;
    this.render();
  }

  /** Redraw with the current language. */
  render(): void {
    this.plot?.destroy();
    this.plot = null;
    const data = this.data;
    if (data === null || data.sensors.length === 0) {
      return;
    }
    const hasValues = data.sensors.some((s) => s.temp_c.validCount + s.rh_pct.validCount > 0);
    this.showMessage(hasValues ? '' : this.i18n.t('noData'));
    this.message.hidden = hasValues;
    this.plotHost.setAttribute('aria-label', this.i18n.t('chartLabel'));
    const aligned = alignSeries(data.sensors.flatMap((s) => [s.temp_c, s.rh_pct]));
    const plotData = [aligned.t, ...aligned.columns] as unknown as AlignedData;
    this.plot = new uPlot(this.options(data), plotData, this.plotHost);
    this.plot.over.append(this.markers);
    this.placeEventMarkers();
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
        draw: [
          (u) => {
            this.drawEventLines(u);
          },
        ],
        setSize: [
          () => {
            this.placeEventMarkers();
          },
        ],
      },
      legend: { live: true },
    };
  }

  private sensorSeries(sensor: SensorChartData, tempUnit: string, rhUnit: string): Series[] {
    const info = this.catalog.get(sensor.sensorId);
    const name = info?.label ?? sensor.sensorId;
    const color = sensorColor(info?.colorIndex ?? 0);
    const value = (unit: string) => (_: uPlot, v: number | null) =>
      v === null ? '–' : `${this.format(v)} ${unit}`;
    return [
      {
        label: `${name} · ${this.variableLabel('temp_c')}`,
        scale: 'temp',
        stroke: color,
        width: TEMP_LINE_WIDTH_PX,
        spanGaps: false,
        value: value(tempUnit),
      },
      {
        label: `${name} · ${this.variableLabel('rh_pct')}`,
        scale: 'rh',
        stroke: color,
        width: RH_LINE_WIDTH_PX,
        dash: RH_DASH_PX,
        spanGaps: false,
        value: value(rhUnit),
      },
    ];
  }

  private drawEventLines(u: uPlot): void {
    const { ctx } = u;
    const { top, height } = u.bbox;
    ctx.save();
    ctx.setLineDash(EVENT_LINE_DASH_PX.map((px) => px * uPlot.pxRatio));
    ctx.strokeStyle = EVENT_LINE_COLOR;
    ctx.lineWidth = uPlot.pxRatio;
    for (const { event } of this.events()) {
      const x = Math.round(u.valToPos(event.t, 'x', true));
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, top + height);
      ctx.stroke();
    }
    ctx.restore();
  }

  private placeEventMarkers(): void {
    const plot = this.plot;
    if (plot === null) {
      return;
    }
    const markers = this.events().map(({ event, sensorId }) => {
      const text = this.eventText(event, sensorId);
      const marker = el('button', { type: 'button', class: 'event-marker', 'aria-label': text, 'data-tip': text });
      marker.style.left = `${plot.valToPos(event.t, 'x')}px`;
      return marker;
    });
    this.markers.replaceChildren(...markers);
  }

  private events(): readonly { event: SensorEvent; sensorId: string }[] {
    return (this.data?.sensors ?? []).flatMap((s) => s.events.map((event) => ({ event, sensorId: s.sensorId })));
  }

  private eventText(event: SensorEvent, sensorId: string): string {
    const parts = [
      `${this.i18n.t(EVENT_LABELS[event.type])} – ${this.catalog.get(sensorId)?.label ?? sensorId}`,
      this.i18n.formatDateTime(event.t, this.zone.name),
    ];
    if (event.confidence !== null) {
      parts.push(this.i18n.t('eventConfidence', { pct: Math.round(event.confidence * PERCENT) }));
    }
    if (event.detail !== null) {
      parts.push(event.detail);
    }
    return parts.join(' · ');
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

  private format(value: number): string {
    return this.i18n.formatNumber(value, VALUE_DECIMALS);
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
