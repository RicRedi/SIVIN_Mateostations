import { describe, expect, it } from 'vitest';
import { minViewSpanS, ViewRange, wheelZoomFactor } from '../src/domain/ViewRange';

const BOUNDS = new ViewRange(0, 1000);

function range(view: ViewRange): [number, number] {
  return [view.startT, view.endT];
}

describe('ViewRange', () => {
  it('rejects an empty or non-finite range', () => {
    expect(() => new ViewRange(5, 5)).toThrow(RangeError);
    expect(() => new ViewRange(0, Number.NaN)).toThrow(RangeError);
  });

  it('zooms in around the anchor, which keeps its screen position', () => {
    // Anchor 250 is at 25 % of [0, 1000); half the span keeps it at 25 %: start 250 − 0.25·500.
    expect(range(BOUNDS.zoom(250, 0.5, BOUNDS, 10))).toEqual([125, 625]);
  });

  it('zooms out up to the bounds and stays inside them', () => {
    const view = new ViewRange(800, 900);
    // Span 400 around anchor 900 (100 % of the view) would end at 900 + 0 = 900, start 500.
    expect(range(view.zoom(900, 4, BOUNDS, 10))).toEqual([500, 900]);
    // Span 400 anchored at the start 800 would be [800, 1200) → shifted back to [600, 1000).
    expect(range(view.zoom(800, 4, BOUNDS, 10))).toEqual([600, 1000]);
    expect(range(view.zoom(850, 100, BOUNDS, 10))).toEqual([0, 1000]);
  });

  it('never zooms in below the minimum span and clamps the anchor into the view', () => {
    expect(range(new ViewRange(100, 200).zoom(150, 0.01, BOUNDS, 40))).toEqual([130, 170]);
    expect(range(new ViewRange(100, 200).zoom(-50, 0.5, BOUNDS, 10))).toEqual([100, 150]);
  });

  it('pans and stops at the bounds without changing the span', () => {
    const view = new ViewRange(100, 300);
    expect(range(view.pan(50, BOUNDS))).toEqual([150, 350]);
    expect(range(view.pan(-500, BOUNDS))).toEqual([0, 200]);
    expect(range(view.pan(5000, BOUNDS))).toEqual([800, 1000]);
  });

  it('clamps a selection to the bounds and to the minimum span', () => {
    expect(range(new ViewRange(-100, 200).clampTo(BOUNDS, 10))).toEqual([0, 200]);
    // 20 s around 500 widened to 100 s, centred.
    expect(range(new ViewRange(490, 510).clampTo(BOUNDS, 100))).toEqual([450, 550]);
    expect(new ViewRange(2000, 3000).clampTo(BOUNDS, 10)).toBe(BOUNDS);
  });

  it('knows whether it covers the bounds', () => {
    expect(BOUNDS.covers(BOUNDS)).toBe(true);
    expect(new ViewRange(0, 999).covers(BOUNDS)).toBe(false);
    expect(new ViewRange(0, 999).equals(new ViewRange(0, 999))).toBe(true);
    expect(BOUNDS.spanS).toBe(1000);
  });
});

describe('zoom helpers', () => {
  it('derives the wheel factor exponentially so that opposite wheels cancel', () => {
    expect(wheelZoomFactor(0)).toBe(1);
    expect(wheelZoomFactor(100)).toBeCloseTo(Math.exp(0.15), 12);
    expect(wheelZoomFactor(100) * wheelZoomFactor(-100)).toBeCloseTo(1, 12);
  });

  it('limits the zoom to four point spacings of the resolution', () => {
    expect(minViewSpanS('raw')).toBe(4 * 1830);
    expect(minViewSpanS('hourly')).toBe(4 * 3600);
    expect(minViewSpanS('daily')).toBe(4 * 86_400);
  });
});
