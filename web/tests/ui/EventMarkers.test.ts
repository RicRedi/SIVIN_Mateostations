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
import { TimeSeries } from '../../src/domain/TimeSeries';
import { EventMarkers, offSiteBands, withoutBands, type ChartEvent } from '../../src/ui/EventMarkers';
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
  const ctx = { save: vi.fn(), restore: vi.fn(), setLineDash: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), fillRect: vi.fn(), strokeStyle: '', fillStyle: '', lineWidth: 0 };
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

const HOUR = 3600;
const offSite = (t: number, tEnd: number | null, detail: string | null = 'service: battery'): ChartEvent => ({
  sensorId: '77799986',
  event: { type: 'off_site', t, t_end: tEnd, source: 'log', confidence: null, detail },
});

describe('offSiteBands', () => {
  it('clips periods to the window and drops the ones outside', () => {
    const events: ChartEvent[] = [
      offSite(T - 2 * HOUR, T + HOUR),
      offSite(T + 2 * HOUR, T + 3 * HOUR),
      offSite(T + 5 * HOUR, null),
      offSite(T - 5 * HOUR, T - HOUR),
      offSite(T + 10 * HOUR, T + 11 * HOUR),
      { sensorId: '77799986', event: { type: 'step', t: T, source: 'detected', confidence: null, detail: null } },
    ];
    const bands = offSiteBands(events, T, T + 6 * HOUR);
    expect(bands.map((b) => [b.startT - T, b.endT - T])).toEqual([
      [0, HOUR],
      [2 * HOUR, 3 * HOUR],
      [5 * HOUR, 6 * HOUR],
    ]);
    expect(bands[0]?.event.t).toBe(T - 2 * HOUR);
    expect(offSiteBands(events, T + HOUR, T + 2 * HOUR)).toEqual([]);
  });
});

describe('withoutBands', () => {
  const series = TimeSeries.of([0, 10, 20, 30, 40], [1, 2, 3, null, 5]);

  it('blanks values inside [start, end) whatever their qc flags', () => {
    const result = withoutBands(series, [{ startT: 10, endT: 30 }]);
    expect(result.t).toEqual([0, 10, 20, 30, 40]);
    expect(result.values).toEqual([1, null, null, null, 5]);
  });

  it('breaks the line at a band without samples inside', () => {
    const result = withoutBands(series, [{ startT: 21, endT: 29 }, { startT: 41, endT: 50 }, { startT: -5, endT: 0 }]);
    expect(result.t).toEqual([0, 10, 20, 21, 30, 40]);
    expect(result.values).toEqual([1, 2, 3, null, null, 5]);
  });

  it('returns the series unchanged without bands or samples', () => {
    expect(withoutBands(series, [])).toBe(series);
    expect(withoutBands(TimeSeries.EMPTY, [{ startT: 0, endT: 10 }])).toBe(TimeSeries.EMPTY);
  });
});

describe('EventMarkers with off-site bands', () => {
  const window = [T, T + 6 * HOUR] as const;
  const events = [offSite(T + HOUR, T + 3 * HOUR), offSite(T + 4 * HOUR, null, null)];

  function markersIn(language: 'cs' | 'de' | 'en'): EventMarkers {
    const markers = new EventMarkers(new I18n({ cs, de, en }, language), catalog, new TimeZone('Europe/Prague'));
    markers.setEvents(events);
    markers.setBands(offSiteBands(events, ...window));
    return markers;
  }

  it('draws one grey rectangle per band across the plotting area and no dashed line', () => {
    const { plot, ctx } = fakePlot();
    const markers = markersIn('en');
    markers.drawBands(plot);
    expect(ctx.fillRect.mock.calls).toEqual([
      [1060, 10, 120, 100],
      [1240, 10, 120, 100],
    ]);
    expect(ctx.fillStyle).not.toBe('');
    markers.drawLines(plot);
    expect(ctx.moveTo).not.toHaveBeenCalled();
  });

  it('gives each band a focusable, labelled handle in the middle of the band', () => {
    const { plot } = fakePlot();
    markersIn('en').attach(plot);
    const buttons = [...plot.over.querySelectorAll<HTMLButtonElement>('button.event-marker--off-site')];
    expect(buttons.map((b) => b.style.left)).toEqual(['170px', '350px']);
    expect(buttons[0]?.getAttribute('aria-label')).toBe(
      'Not in the vineyard: service: battery – 77799986 (VUT) · 3 Jun 2026, 11:00 – 3 Jun 2026, 13:00',
    );
    expect(buttons[1]?.dataset.tip).toBe('Not in the vineyard – 77799986 (VUT) · 3 Jun 2026, 14:00 – ongoing');
  });

  it('labels bands in Czech and German', () => {
    const czech = fakePlot();
    markersIn('cs').attach(czech.plot);
    expect(czech.plot.over.querySelector('button')?.getAttribute('aria-label')).toMatch(/^Mimo vinici: service: battery – 77799986 \(VUT\)/);
    const german = fakePlot();
    markersIn('de').attach(german.plot);
    expect(german.plot.over.querySelectorAll('button')[1]?.getAttribute('aria-label')).toMatch(/^Nicht im Weinberg – .* – bis heute$/);
  });
});
