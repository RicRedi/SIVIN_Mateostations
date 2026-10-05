// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import type uPlot from 'uplot';
import { SensorCatalog } from '../../src/app/SensorCatalog';
import { parseLatestFile, parseManifest, parseSensorsGeoJSON } from '../../src/contract';
import { TimeZone } from '../../src/domain/TimeZone';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { EventMarkers } from '../../src/ui/EventMarkers';
import { fixtureJson, utc } from '../helpers';

vi.hoisted(() => {
  // uPlot reads the device pixel ratio through matchMedia when it is imported; jsdom has none.
  window.matchMedia = () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) as unknown as MediaQueryList;
});

const catalog = SensorCatalog.build(
  parseSensorsGeoJSON(fixtureJson('sensors.geojson')),
  parseManifest(fixtureJson('manifest.json')),
  parseLatestFile(fixtureJson('latest.json')),
);
const T = utc(2026, 6, 3, 8);

function fakePlot() {
  const ctx = { save: vi.fn(), restore: vi.fn(), setLineDash: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), strokeStyle: '', lineWidth: 0 };
  const plot = {
    over: document.createElement('div'),
    ctx,
    bbox: { top: 10, height: 100 },
    valToPos: (value: number, _scale: string, canvasPixels?: boolean) => (value - T) / 60 + (canvasPixels ? 1000 : 50),
  };
  return { plot: plot as unknown as uPlot, ctx };
}

describe('EventMarkers', () => {
  const markers = new EventMarkers(new I18n({ cs, de, en }, 'en'), catalog, new TimeZone('Europe/Prague'));
  markers.setEvents([
    { sensorId: '77799986', event: { type: 'deployment', t: T, source: 'detected', confidence: 0.93, detail: 'office → vineyard' } },
    { sensorId: '00000000', event: { type: 'retrieval', t: T + 600, source: 'registry', confidence: null, detail: null } },
  ]);

  it('adds one named, positioned button per event over the plot', () => {
    const { plot } = fakePlot();
    markers.attach(plot);
    const buttons = [...plot.over.querySelectorAll<HTMLButtonElement>('button.event-marker')];
    expect(buttons.map((b) => b.style.left)).toEqual(['50px', '60px']);
    expect(buttons[0]?.getAttribute('aria-label')).toBe(
      'Deployed in the vineyard – 77799986 (VUT) · 3 Jun 2026, 10:00 · confidence 93 % · office → vineyard',
    );
    expect(buttons[1]?.dataset.tip).toBe('Retrieved from the vineyard – 00000000 · 3 Jun 2026, 10:10');
  });

  it('draws one dashed vertical line per event across the plotting area', () => {
    const { plot, ctx } = fakePlot();
    markers.drawLines(plot);
    expect(ctx.moveTo.mock.calls).toEqual([[1000, 10], [1010, 10]]);
    expect(ctx.lineTo.mock.calls).toEqual([[1000, 110], [1010, 110]]);
    expect(ctx.restore).toHaveBeenCalledOnce();
  });
});
