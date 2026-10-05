import uPlot from 'uplot';
import type { SensorCatalog } from '../app/SensorCatalog';
import { isOffSiteEvent, type OffSiteEvent, type PointSensorEvent, type SensorEvent } from '../contract';
import { TimeSeries } from '../domain/TimeSeries';
import type { TimeZone } from '../domain/TimeZone';
import type { MessageKey } from '../i18n/cs';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';

const EVENT_LINE_DASH_PX = [3, 3];
const EVENT_LINE_COLOR = '#52514e';
/** Fill of an off-site band: the event line colour at low opacity, so lines of other sensors stay visible. */
const OFF_SITE_BAND_COLOR = 'rgba(82, 81, 78, 0.16)';
/** The band's focusable handle: grey square instead of the round point marker. */
const OFF_SITE_HANDLE_COLOR = '#8c8a85';
const OFF_SITE_HANDLE_RADIUS = '2px';
const PERCENT = 100;

const EVENT_LABELS: Readonly<Record<PointSensorEvent['type'], MessageKey>> = {
  deployment: 'eventDeployment',
  retrieval: 'eventRetrieval',
  step: 'eventStep',
};

/** An event together with the sensor it belongs to. */
export interface ChartEvent {
  readonly sensorId: string;
  readonly event: SensorEvent;
}

/** A point event together with the sensor it belongs to. */
interface ChartPointEvent {
  readonly sensorId: string;
  readonly event: PointSensorEvent;
}

/**
 * An off-site period clipped to the chart window: `[startT, endT)` in Unix seconds. The event keeps
 * the unclipped times for the label.
 */
export interface OffSiteBand {
  readonly sensorId: string;
  readonly startT: number;
  readonly endT: number;
  readonly event: OffSiteEvent;
}

/**
 * The `off_site` periods of `events` that overlap the window `[startT, endT)`, clipped to it.
 * An open period (`t_end` null) runs to the end of the window.
 */
export function offSiteBands(events: readonly ChartEvent[], startT: number, endT: number): OffSiteBand[] {
  const bands: OffSiteBand[] = [];
  for (const { sensorId, event } of events) {
    if (!isOffSiteEvent(event)) {
      continue;
    }
    const bandStart = Math.max(event.t, startT);
    const bandEnd = Math.min(event.t_end ?? Number.POSITIVE_INFINITY, endT);
    if (bandEnd > bandStart) {
      bands.push({ sensorId, startT: bandStart, endT: bandEnd, event });
    }
  }
  return bands;
}

/**
 * `series` without values inside the bands (`startT <= t < endT` becomes `null`), with a `null`
 * break inserted at the start of a band that has samples on both sides, so no line is drawn
 * across the band even when it contains no sample (e.g. daily means). Works from the event times
 * alone, independent of the `qc` flags.
 */
export function withoutBands(series: TimeSeries, bands: readonly { startT: number; endT: number }[]): TimeSeries {
  if (bands.length === 0 || series.length === 0) {
    return series;
  }
  const inside = (t: number) => bands.some((band) => t >= band.startT && t < band.endT);
  const first = series.t[0] ?? 0;
  const last = series.t[series.length - 1] ?? 0;
  const present = new Set(series.t);
  const points = series.t.map((t, i) => ({ t, value: inside(t) ? null : (series.values[i] ?? null) }));
  for (const band of bands) {
    if (band.startT > first && band.startT < last && !present.has(band.startT)) {
      points.push({ t: band.startT, value: null });
      present.add(band.startT);
    }
  }
  points.sort((a, b) => a.t - b.t);
  return TimeSeries.of(
    points.map((p) => p.t),
    points.map((p) => p.value),
  );
}

/**
 * Sensor events on a uPlot chart:
 * - point events: dashed vertical lines on the canvas plus one focusable button each,
 * - `off_site` periods: grey bands across the plotting area (drawn under the series) plus one
 *   focusable handle each, labelled "Not in the vineyard: <detail>".
 * Every button has an accessible name and a hover/focus tooltip (type, sensor, time, detail).
 */
export class EventMarkers {
  /** Layer for the buttons; placed over the plotting area by {@link attach}. */
  readonly element = el('div', { class: 'chart__events' });
  private points: readonly ChartPointEvent[] = [];
  private bands: readonly OffSiteBand[] = [];

  constructor(
    private readonly i18n: I18n,
    private readonly catalog: SensorCatalog,
    private readonly zone: TimeZone,
  ) {}

  /** Set the point events; `off_site` events are ignored here (see {@link setBands}). */
  setEvents(events: readonly ChartEvent[]): void {
    this.points = events.filter((item): item is ChartPointEvent => !isOffSiteEvent(item.event));
  }

  /** Set the off-site bands (from {@link offSiteBands}). */
  setBands(bands: readonly OffSiteBand[]): void {
    this.bands = bands;
  }

  attach(plot: uPlot): void {
    plot.over.append(this.element);
    this.place(plot);
  }

  /** uPlot `drawClear` hook: one grey rectangle per band, under the series and the grid. */
  drawBands(plot: uPlot): void {
    const { ctx } = plot;
    const { top, height } = plot.bbox;
    ctx.save();
    ctx.fillStyle = OFF_SITE_BAND_COLOR;
    for (const band of this.bands) {
      const x0 = plot.valToPos(band.startT, 'x', true);
      const x1 = plot.valToPos(band.endT, 'x', true);
      ctx.fillRect(x0, top, x1 - x0, height);
    }
    ctx.restore();
  }

  /** uPlot `draw` hook: dashed vertical line per point event. */
  drawLines(plot: uPlot): void {
    const { ctx } = plot;
    const { top, height } = plot.bbox;
    ctx.save();
    ctx.setLineDash(EVENT_LINE_DASH_PX.map((px) => px * uPlot.pxRatio));
    ctx.strokeStyle = EVENT_LINE_COLOR;
    ctx.lineWidth = uPlot.pxRatio;
    for (const { event } of this.points) {
      const x = Math.round(plot.valToPos(event.t, 'x', true));
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, top + height);
      ctx.stroke();
    }
    ctx.restore();
  }

  /** Position the buttons; also the uPlot `setSize` hook. */
  place(plot: uPlot): void {
    const markers = this.points.map(({ event, sensorId }) =>
      this.button(this.describePoint(event, sensorId), plot.valToPos(event.t, 'x')),
    );
    const handles = this.bands.map((band) => {
      const middleT = (band.startT + band.endT) / 2;
      const button = this.button(this.describeBand(band), plot.valToPos(middleT, 'x'));
      button.classList.add('event-marker--off-site');
      button.style.background = OFF_SITE_HANDLE_COLOR;
      button.style.borderRadius = OFF_SITE_HANDLE_RADIUS;
      return button;
    });
    this.element.replaceChildren(...handles, ...markers);
  }

  private button(text: string, leftPx: number): HTMLButtonElement {
    const button = el('button', { type: 'button', class: 'event-marker', 'aria-label': text, 'data-tip': text });
    button.style.left = `${leftPx}px`;
    return button;
  }

  private sensorLabel(sensorId: string): string {
    return this.catalog.get(sensorId)?.label ?? sensorId;
  }

  private describePoint(event: PointSensorEvent, sensorId: string): string {
    const parts = [
      `${this.i18n.t(EVENT_LABELS[event.type])} – ${this.sensorLabel(sensorId)}`,
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

  private describeBand({ event, sensorId }: OffSiteBand): string {
    const title = this.i18n.t('eventOffSite');
    const heading = event.detail === null ? title : `${title}: ${event.detail}`;
    const end =
      event.t_end === null ? this.i18n.t('eventOngoing') : this.i18n.formatDateTime(event.t_end, this.zone.name);
    return [
      `${heading} – ${this.sensorLabel(sensorId)}`,
      `${this.i18n.formatDateTime(event.t, this.zone.name)} – ${end}`,
    ].join(' · ');
  }
}
