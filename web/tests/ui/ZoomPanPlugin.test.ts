// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type uPlot from 'uplot';
import { ViewRange } from '../../src/domain/ViewRange';
import { WHEEL_LINE_PX, ZoomPanPlugin, animationFrames, type FrameScheduler } from '../../src/ui/ZoomPanPlugin';

/** The plot area starts at clientX 100 and is 1000 px wide; the window is [0, 1000) s, 1 s per px. */
const LEFT_PX = 100;
const WIDTH_PX = 1000;
const BOUNDS = new ViewRange(0, 1000);

class ManualFrames implements FrameScheduler {
  callbacks: (() => void)[] = [];
  cancelled: number[] = [];
  request(callback: () => void): number {
    this.callbacks.push(callback);
    return this.callbacks.length;
  }
  cancel(handle: number): void {
    this.cancelled.push(handle);
  }
  flush(): void {
    const pending = this.callbacks;
    this.callbacks = [];
    pending.forEach((callback) => {
      callback();
    });
  }
}

function setup() {
  const frames = new ManualFrames();
  const changes: [number, number][] = [];
  const plugin = new ZoomPanPlugin((view) => changes.push([view.startT, view.endT]), frames);
  const over = document.createElement('div');
  over.getBoundingClientRect = () => ({ left: LEFT_PX, width: WIDTH_PX }) as DOMRect;
  const capture = vi.fn();
  const release = vi.fn();
  over.setPointerCapture = capture;
  over.hasPointerCapture = () => true;
  over.releasePointerCapture = release;
  const plot = {
    over,
    select: { left: 0, top: 0, width: 0, height: 0 },
    setSelect: vi.fn(),
    setScale: vi.fn(),
    posToVal: (px: number) => plugin.view.startT + (px * plugin.view.spanS) / WIDTH_PX,
  };
  plugin.configure(BOUNDS, 10);
  const hooks = plugin.plugin().hooks;
  const ready = hooks.ready as (u: uPlot) => void;
  ready(plot as unknown as uPlot);
  return { plugin, plot, over, frames, changes, hooks, capture, release };
}

function pointer(type: string, pointerId: number, clientX: number, init: PointerEventInit = {}): PointerEvent {
  return new PointerEvent(type, { pointerId, clientX, button: 0, bubbles: true, cancelable: true, ...init });
}

function range(view: ViewRange): [number, number] {
  return [view.startT, view.endT];
}

describe('ZoomPanPlugin', () => {
  let s: ReturnType<typeof setup>;
  beforeEach(() => {
    s = setup();
  });

  it('starts with the whole window as x range', () => {
    expect(s.plugin.xRange()).toEqual([0, 1000]);
    expect(s.plugin.isZoomed).toBe(false);
  });

  it('zooms around the cursor on wheel, once per animation frame', () => {
    const wheel = new WheelEvent('wheel', { deltaY: -100, clientX: LEFT_PX + 500, cancelable: true });
    s.over.dispatchEvent(wheel);
    expect(wheel.defaultPrevented).toBe(true);
    expect(s.changes).toEqual([]);
    s.frames.flush();
    // factor exp(−0.15) = 0.860708; span 860.708 around t = 500 (the centre).
    const [start, end] = s.changes[0] ?? [0, 0];
    expect(start).toBeCloseTo(500 - 0.5 * 860.708, 2);
    expect(end - start).toBeCloseTo(860.708, 2);
    expect(s.plot.setScale).toHaveBeenCalledWith('x', { min: start, max: end });
    expect(s.plugin.isZoomed).toBe(true);
    expect(s.plugin.xRange()).toEqual([start, end]);
  });

  it('combines wheel events of one frame and scales line and page deltas', () => {
    s.over.dispatchEvent(new WheelEvent('wheel', { deltaY: -3, deltaMode: 1, clientX: LEFT_PX, cancelable: true }));
    s.over.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, clientX: LEFT_PX, cancelable: true }));
    expect(s.frames.callbacks).toHaveLength(1);
    s.frames.flush();
    // Anchor t = 0 at the left edge; span 1000·exp(−0.0015·(3·16 + 100)).
    expect(s.changes).toHaveLength(1);
    expect(s.changes[0]?.[0]).toBe(0);
    expect(s.changes[0]?.[1]).toBeCloseTo(1000 * Math.exp(-0.0015 * (3 * WHEEL_LINE_PX + 100)), 6);
    s.over.dispatchEvent(new WheelEvent('wheel', { deltaY: 1, deltaMode: 2, clientX: LEFT_PX, cancelable: true }));
    s.frames.flush();
    expect(range(s.plugin.view)).toEqual([0, 1000]);
  });

  it('pans with a plain drag and stops at the window', () => {
    s.plugin.configure(BOUNDS, 10, new ViewRange(100, 600));
    s.over.dispatchEvent(pointer('pointerdown', 1, LEFT_PX + 600));
    expect(s.capture).toHaveBeenCalledWith(1);
    // 100 px to the left at 0.5 s/px moves the view 50 s later.
    s.over.dispatchEvent(pointer('pointermove', 1, LEFT_PX + 500));
    expect(range(s.plugin.view)).toEqual([150, 650]);
    s.over.dispatchEvent(pointer('pointermove', 1, LEFT_PX - 5000));
    expect(range(s.plugin.view)).toEqual([500, 1000]);
    s.over.dispatchEvent(pointer('pointerup', 1, LEFT_PX - 5000));
    expect(s.release).toHaveBeenCalledWith(1);
    s.over.dispatchEvent(pointer('pointermove', 1, LEFT_PX + 900));
    expect(range(s.plugin.view)).toEqual([500, 1000]);
  });

  it('leaves Shift-drags, other buttons and event markers alone', () => {
    s.plugin.configure(BOUNDS, 10, new ViewRange(100, 600));
    s.over.dispatchEvent(pointer('pointerdown', 1, LEFT_PX + 600, { shiftKey: true }));
    s.over.dispatchEvent(pointer('pointerdown', 2, LEFT_PX + 600, { button: 2 }));
    const marker = document.createElement('button');
    marker.className = 'event-marker';
    s.over.append(marker);
    marker.dispatchEvent(pointer('pointerdown', 3, LEFT_PX + 600));
    for (const id of [1, 2, 3]) {
      s.over.dispatchEvent(pointer('pointermove', id, LEFT_PX + 100));
    }
    s.over.dispatchEvent(pointer('pointerup', 4, LEFT_PX));
    expect(s.changes).toEqual([]);
  });

  it('pinch-zooms around the midpoint of two touches and follows it', () => {
    s.over.dispatchEvent(pointer('pointerdown', 1, LEFT_PX + 300, { pointerType: 'touch' }));
    s.over.dispatchEvent(pointer('pointerdown', 2, LEFT_PX + 700, { pointerType: 'touch' }));
    s.over.dispatchEvent(pointer('pointermove', 2, LEFT_PX + 900, { pointerType: 'touch' }));
    // Distance 400 → 600 px: span × 2/3 around t = 500 → [166.67, 833.33); the midpoint moved
    // 100 px to the right, which pans 100 px · 0.6667 s/px = 66.67 s earlier.
    const [start, end] = range(s.plugin.view);
    expect(start).toBeCloseTo(100, 6);
    expect(end).toBeCloseTo(766.667, 3);
    // Lifting one finger continues as a pan from the current view.
    s.over.dispatchEvent(pointer('pointerup', 1, LEFT_PX + 300, { pointerType: 'touch' }));
    s.over.dispatchEvent(pointer('pointermove', 2, LEFT_PX + 1000, { pointerType: 'touch' }));
    expect(s.plugin.view.startT).toBeCloseTo(100 - 100 * 0.666667, 3);
  });

  it('resets on double-click and through reset()', () => {
    s.plugin.configure(BOUNDS, 10, new ViewRange(100, 600));
    s.over.dispatchEvent(new MouseEvent('dblclick'));
    expect(range(s.plugin.view)).toEqual([0, 1000]);
    expect(s.changes).toEqual([[0, 1000]]);
    s.plugin.reset();
    expect(s.changes).toHaveLength(1);
  });

  it('zooms to a Shift-selection and clears it', () => {
    s.plot.select = { left: 200, top: 0, width: 100, height: 50 };
    (s.hooks.setSelect as (u: uPlot) => void)(s.plot as unknown as uPlot);
    expect(range(s.plugin.view)).toEqual([200, 300]);
    expect(s.plot.setSelect).toHaveBeenCalledWith({ left: 0, top: 0, width: 0, height: 0 }, false);
    s.plot.select = { left: 0, top: 0, width: 0, height: 0 };
    (s.hooks.setSelect as (u: uPlot) => void)(s.plot as unknown as uPlot);
    expect(s.changes).toHaveLength(1);
  });

  it('passes only Shift + left-button presses to uPlot and disables its double-click', () => {
    const handler = vi.fn(() => null);
    const { mousedown, dblclick } = s.plugin.cursorBindings();
    const listener = mousedown?.(s.plot as unknown as uPlot, s.over, handler);
    listener?.(new MouseEvent('mousedown', { button: 0 }));
    listener?.(new MouseEvent('mousedown', { button: 0, shiftKey: true }));
    listener?.(new MouseEvent('mousedown', { button: 1, shiftKey: true }));
    expect(handler).toHaveBeenCalledTimes(1);
    expect(dblclick?.(s.plot as unknown as uPlot, s.over, handler)).toBeNull();
  });

  it('keeps a given view on configure, clamped, and stops listening when destroyed', () => {
    s.plugin.configure(new ViewRange(0, 500), 10, new ViewRange(400, 900));
    expect(range(s.plugin.view)).toEqual([400, 500]);
    s.over.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, clientX: LEFT_PX }));
    (s.hooks.destroy as (u: uPlot) => void)(s.plot as unknown as uPlot);
    expect(s.frames.cancelled).toEqual([1]);
    s.over.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, clientX: LEFT_PX }));
    s.over.dispatchEvent(pointer('pointerdown', 1, LEFT_PX));
    expect(s.frames.callbacks).toHaveLength(1);
    expect(s.capture).not.toHaveBeenCalled();
  });

  it('uses the window animation frames', () => {
    const cancel = vi.fn();
    const view = { requestAnimationFrame: vi.fn(() => 7), cancelAnimationFrame: cancel } as unknown as Window;
    const frames = animationFrames(view);
    expect(frames.request(() => undefined)).toBe(7);
    frames.cancel(7);
    expect(cancel).toHaveBeenCalledWith(7);
  });
});
