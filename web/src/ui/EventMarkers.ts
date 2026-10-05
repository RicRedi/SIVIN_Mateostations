import uPlot from 'uplot';
import type { SensorCatalog } from '../app/SensorCatalog';
import type { SensorEvent } from '../contract';
import type { TimeZone } from '../domain/TimeZone';
import type { MessageKey } from '../i18n/cs';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';

const EVENT_LINE_DASH_PX = [3, 3];
const EVENT_LINE_COLOR = '#52514e';
const PERCENT = 100;

const EVENT_LABELS: Readonly<Record<SensorEvent['type'], MessageKey>> = {
  deployment: 'eventDeployment',
  retrieval: 'eventRetrieval',
  step: 'eventStep',
};

/** An event together with the sensor it belongs to. */
export interface ChartEvent {
  readonly sensorId: string;
  readonly event: SensorEvent;
}

/**
 * Sensor events on a uPlot chart: dashed vertical lines on the canvas plus one focusable button
 * per event (accessible name and hover/focus tooltip with type, sensor, time, confidence, detail).
 */
export class EventMarkers {
  /** Layer for the buttons; placed over the plotting area by {@link attach}. */
  readonly element = el('div', { class: 'chart__events' });
  private events: readonly ChartEvent[] = [];

  constructor(
    private readonly i18n: I18n,
    private readonly catalog: SensorCatalog,
    private readonly zone: TimeZone,
  ) {}

  setEvents(events: readonly ChartEvent[]): void {
    this.events = events;
  }

  attach(plot: uPlot): void {
    plot.over.append(this.element);
    this.place(plot);
  }

  /** uPlot `draw` hook: dashed vertical line per event. */
  drawLines(plot: uPlot): void {
    const { ctx } = plot;
    const { top, height } = plot.bbox;
    ctx.save();
    ctx.setLineDash(EVENT_LINE_DASH_PX.map((px) => px * uPlot.pxRatio));
    ctx.strokeStyle = EVENT_LINE_COLOR;
    ctx.lineWidth = uPlot.pxRatio;
    for (const { event } of this.events) {
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
    const buttons = this.events.map(({ event, sensorId }) => {
      const text = this.describe(event, sensorId);
      const button = el('button', { type: 'button', class: 'event-marker', 'aria-label': text, 'data-tip': text });
      button.style.left = `${plot.valToPos(event.t, 'x')}px`;
      return button;
    });
    this.element.replaceChildren(...buttons);
  }

  private describe(event: SensorEvent, sensorId: string): string {
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
}
