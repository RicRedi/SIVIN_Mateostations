import type uPlot from 'uplot';
import { ViewRange, wheelZoomFactor } from '../domain/ViewRange';

/** Pixels per wheel "line" (`WheelEvent.DOM_DELTA_LINE`), as browsers scroll text. */
export const WHEEL_LINE_PX = 16;
/** Pixels per wheel "page" (`WheelEvent.DOM_DELTA_PAGE`). */
export const WHEEL_PAGE_PX = 800;
const DOM_DELTA_LINE = 1;
const DOM_DELTA_PAGE = 2;
const PRIMARY_BUTTON = 0;
const PINCH_POINTERS = 2;
const HALF = 0.5;

/** Elements over the plot that keep their own pointer behaviour (event marker buttons). */
const OWN_POINTER_TARGETS = '.event-marker';

/** Schedules work for the next animation frame (injected, so tests can run it at once). */
export interface FrameScheduler {
  request(callback: () => void): number;
  cancel(handle: number): void;
}

/** `requestAnimationFrame` of a window. */
export function animationFrames(view: Window): FrameScheduler {
  return {
    request: (callback) => view.requestAnimationFrame(callback),
    cancel: (handle) => {
      view.cancelAnimationFrame(handle);
    },
  };
}

interface PointerStart {
  readonly view: ViewRange;
  /** Single pointer: its x; two pointers: their midpoint (CSS px relative to the plot). */
  readonly x: number;
  /** Distance of two pointers, px; 0 for one. */
  readonly distancePx: number;
}

/**
 * Mouse and touch navigation on the time axis of a uPlot chart, inside the loaded window only:
 *
 * - **wheel** zooms in or out around the time under the cursor (applied once per animation
 *   frame, so fast wheels stay smooth); a wheel that cannot zoom any further is not consumed,
 *   so the page scrolls,
 * - **drag** with the left button (or one finger) pans,
 * - **Shift + drag** selects a range and zooms to it (uPlot's selection, which therefore needs
 *   the modifier: a plain drag pans),
 * - **double-click** shows the whole window again,
 * - **two fingers** pinch-zoom around their midpoint.
 *
 * The plugin owns the visible range: the x scale's `range` is {@link xRange}, and every change is
 * reported through `onChange`. The zoom and pan arithmetic is {@link ViewRange}.
 */
export class ZoomPanPlugin {
  private bounds = new ViewRange(0, 1);
  private minSpanS = 0;
  private current = this.bounds;
  private plot: uPlot | null = null;
  private pendingFactor = 1;
  private pendingAnchorT = 0;
  private frame: number | null = null;
  private readonly pointers = new Map<number, number>();
  private start: PointerStart | null = null;
  private detach: (() => void) | null = null;

  /**
   * @param onChange - Called with the new visible range after every zoom, pan or reset.
   * @param frames - Animation-frame scheduler for wheel zoom.
   */
  constructor(
    private readonly onChange: (view: ViewRange) => void,
    private readonly frames: FrameScheduler,
  ) {}

  /** The visible range. */
  get view(): ViewRange {
    return this.current;
  }

  /** True if the view shows less than the whole window. */
  get isZoomed(): boolean {
    return !this.current.covers(this.bounds);
  }

  /**
   * Set the loaded window and the view for the next plot (before creating it).
   *
   * @param bounds - The loaded window.
   * @param minSpanS - Smallest view span, seconds.
   * @param view - View to keep (e.g. after a re-render), clamped to `bounds`; default all of it.
   */
  configure(bounds: ViewRange, minSpanS: number, view: ViewRange = bounds): void {
    this.bounds = bounds;
    this.minSpanS = minSpanS;
    this.current = view.clampTo(bounds, minSpanS);
  }

  /** Range function of the x scale: always the plugin's view. */
  readonly xRange = (): uPlot.Range.MinMax => [this.current.startT, this.current.endT];

  /**
   * uPlot cursor bindings: the built-in drag selection only starts with Shift held (a plain drag
   * pans), and the built-in double-click (which would rescale to the data) is replaced.
   */
  cursorBindings(): uPlot.Cursor.Bind {
    return {
      mousedown: (_plot, _target, handler) => (event) => {
        if (event.button === PRIMARY_BUTTON && event.shiftKey) {
          handler(event);
        }
        return null;
      },
      dblclick: () => null,
    };
  }

  /** The uPlot plugin (hooks). */
  plugin(): uPlot.Plugin {
    return {
      hooks: {
        ready: (plot) => {
          this.attach(plot);
        },
        setSelect: (plot) => {
          this.zoomToSelection(plot);
        },
        destroy: () => {
          this.release();
        },
      },
    };
  }

  /** Show the whole window. */
  reset(): void {
    this.apply(this.bounds);
  }

  private attach(plot: uPlot): void {
    this.release();
    this.plot = plot;
    const over = plot.over;
    const wheel = (event: WheelEvent) => {
      this.onWheel(event);
    };
    const down = (event: PointerEvent) => {
      this.onPointerDown(event);
    };
    const move = (event: PointerEvent) => {
      this.onPointerMove(event);
    };
    const up = (event: PointerEvent) => {
      this.onPointerUp(event);
    };
    const dblclick = () => {
      this.reset();
    };
    over.addEventListener('wheel', wheel, { passive: false });
    over.addEventListener('pointerdown', down);
    over.addEventListener('pointermove', move);
    over.addEventListener('pointerup', up);
    over.addEventListener('pointercancel', up);
    over.addEventListener('dblclick', dblclick);
    this.detach = () => {
      over.removeEventListener('wheel', wheel);
      over.removeEventListener('pointerdown', down);
      over.removeEventListener('pointermove', move);
      over.removeEventListener('pointerup', up);
      over.removeEventListener('pointercancel', up);
      over.removeEventListener('dblclick', dblclick);
    };
  }

  private release(): void {
    this.detach?.();
    this.detach = null;
    if (this.frame !== null) {
      this.frames.cancel(this.frame);
      this.frame = null;
    }
    this.pendingFactor = 1;
    this.pointers.clear();
    this.start = null;
    this.plot = null;
  }

  private onWheel(event: WheelEvent): void {
    const plot = this.plot;
    if (plot === null) {
      return;
    }
    const unitPx = event.deltaMode === DOM_DELTA_LINE ? WHEEL_LINE_PX : event.deltaMode === DOM_DELTA_PAGE ? WHEEL_PAGE_PX : 1;
    const factor = this.pendingFactor * wheelZoomFactor(event.deltaY * unitPx);
    if (!this.canZoom(factor)) {
      return;
    }
    event.preventDefault();
    this.pendingFactor = factor;
    this.pendingAnchorT = plot.posToVal(this.localX(plot, event.clientX), 'x');
    this.frame ??= this.frames.request(() => {
      this.frame = null;
      const factor = this.pendingFactor;
      this.pendingFactor = 1;
      this.apply(this.current.zoom(this.pendingAnchorT, factor, this.bounds, this.minSpanS));
    });
  }

  /**
   * False if a zoom by `factor` would change nothing: zooming out of the whole window or in
   * below the minimum span. The wheel event then stays unhandled, so the page or the side panel
   * scrolls as usual.
   */
  private canZoom(factor: number): boolean {
    if (factor > 1) {
      return !this.current.covers(this.bounds);
    }
    if (factor < 1) {
      return this.current.spanS > Math.min(this.minSpanS, this.bounds.spanS);
    }
    return false;
  }

  private onPointerDown(event: PointerEvent): void {
    const plot = this.plot;
    const target = event.target;
    const ownTarget = target instanceof Element && target.closest(OWN_POINTER_TARGETS) !== null;
    if (plot === null || event.button !== PRIMARY_BUTTON || event.shiftKey || ownTarget) {
      return;
    }
    this.pointers.set(event.pointerId, this.localX(plot, event.clientX));
    plot.over.setPointerCapture(event.pointerId);
    this.restartGesture();
  }

  private onPointerMove(event: PointerEvent): void {
    const plot = this.plot;
    const start = this.start;
    if (plot === null || start === null || !this.pointers.has(event.pointerId)) {
      return;
    }
    this.pointers.set(event.pointerId, this.localX(plot, event.clientX));
    const widthPx = plot.over.getBoundingClientRect().width;
    if (widthPx <= 0) {
      return;
    }
    const { x, distancePx } = this.gesture();
    const secondsPerPx = start.view.spanS / widthPx;
    let view = start.view;
    if (distancePx > 0 && start.distancePx > 0) {
      const anchorT = start.view.startT + start.x * secondsPerPx;
      view = view.zoom(anchorT, start.distancePx / distancePx, this.bounds, this.minSpanS);
    }
    const panPx = x - start.x;
    this.apply(view.pan((-panPx * view.spanS) / widthPx, this.bounds));
  }

  private onPointerUp(event: PointerEvent): void {
    if (!this.pointers.delete(event.pointerId)) {
      return;
    }
    if (this.plot?.over.hasPointerCapture(event.pointerId) === true) {
      this.plot.over.releasePointerCapture(event.pointerId);
    }
    this.restartGesture();
  }

  /** Begin a new gesture from the current pointers (after one was added or lifted). */
  private restartGesture(): void {
    this.start = this.pointers.size === 0 ? null : { view: this.current, ...this.gesture() };
  }

  private gesture(): { x: number; distancePx: number } {
    const xs = [...this.pointers.values()].slice(0, PINCH_POINTERS);
    const [first = 0, second] = xs;
    return second === undefined
      ? { x: first, distancePx: 0 }
      : { x: (first + second) * HALF, distancePx: Math.abs(second - first) };
  }

  private zoomToSelection(plot: uPlot): void {
    const { left, width } = plot.select;
    if (width <= 0) {
      return;
    }
    const startT = plot.posToVal(left, 'x');
    const endT = plot.posToVal(left + width, 'x');
    plot.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
    if (endT > startT) {
      this.apply(new ViewRange(startT, endT).clampTo(this.bounds, this.minSpanS));
    }
  }

  private localX(plot: uPlot, clientX: number): number {
    return clientX - plot.over.getBoundingClientRect().left;
  }

  private apply(view: ViewRange): void {
    if (view.equals(this.current)) {
      return;
    }
    this.current = view;
    this.plot?.setScale('x', { min: view.startT, max: view.endT });
    this.onChange(view);
  }
}
