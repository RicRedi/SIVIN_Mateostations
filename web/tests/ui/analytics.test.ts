// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { AnalyticsCatalog } from '../../src/app/AnalyticsCatalog';
import { AnalyticsLoader, type AnalyticsData, type AnalyticsSource } from '../../src/app/AnalyticsLoader';
import { AnalyticsPresenter, type AnalyticsView } from '../../src/app/AnalyticsPresenter';
import { IndexDocs } from '../../src/app/IndexDocs';
import { SensorCatalog } from '../../src/app/SensorCatalog';
import { parseDailyFile, parseIndicesFile, parseLatestFile, parseManifest, parseSensorsGeoJSON, type DailyFile, type IndexValue } from '../../src/contract';
import { DataClient } from '../../src/data/DataClient';
import { dateRange } from '../../src/domain/isoDates';
import { RecordsCalculator } from '../../src/domain/SensorRecords';
import { AnalyticsTerms } from '../../src/i18n/analyticsTerms';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { AnalyticsSection } from '../../src/ui/AnalyticsSection';
import { IndexCardsView } from '../../src/ui/IndexCardsView';
import { IndexFormat } from '../../src/ui/IndexFormat';
import { RecordsView } from '../../src/ui/RecordsView';
import { RiskStripView } from '../../src/ui/RiskStripView';
import { SensorColors } from '../../src/ui/SensorColors';
import { fakeFetcher, fixtureJson } from '../helpers';

// The "Ukazatele" section on the synthetic demo fixture and on hand-made synthetic entries (WP-3.4).

const manifest = parseManifest(fixtureJson('manifest.json'));
const catalog = SensorCatalog.build(
  parseSensorsGeoJSON(fixtureJson('sensors.geojson')),
  manifest,
  parseLatestFile(fixtureJson('latest.json')),
);
const DOCS = 'https://example.org/repo/blob/main/';
const A = '77678271';
const B = '77680921';

function setup(language: 'cs' | 'en' = 'cs') {
  const i18n = new I18n({ cs, de, en }, language);
  const terms = new AnalyticsTerms(i18n);
  const format = new IndexFormat(i18n);
  const docs = new IndexDocs(DOCS);
  const colors = new SensorColors();
  colors.update([A, B]);
  const root = document.createElement('section');
  const requests: [number | null, readonly string[]][] = [];
  const section = new AnalyticsSection(
    root,
    i18n,
    AnalyticsCatalog.fromManifest(manifest),
    catalog,
    colors,
    {
      cards: new IndexCardsView(i18n, terms, format, docs),
      risks: new RiskStripView(i18n, terms, format, docs),
      records: new RecordsView(i18n, format, new RecordsCalculator(0.9)),
    },
    [2025, 2026],
    (season, ids) => requests.push([season, ids]),
  );
  return { i18n, root, section, requests };
}

const fixtureIndices = parseIndicesFile(fixtureJson('indices/2026.json'), 'indices/2026.json');
const fixtureDaily = (id: string): DailyFile => parseDailyFile(fixtureJson(`series/${id}/daily.json`), 'daily.json');

function fixtureData(): AnalyticsData {
  return {
    season: 2026,
    indicesError: null,
    sensors: [A, B].map((id) => ({ sensorId: id, indices: fixtureIndices.sensors[id] ?? null, daily: fixtureDaily(id), dailyError: null })),
  };
}

/** Text of a node with its child elements separated by spaces (as a reader would hear them). */
function text(node: Node | null): string {
  if (node === null) {
    return '';
  }
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent ?? '';
  }
  return [...node.childNodes].map(text).join(' ').replace(/\s+/g, ' ').trim();
}

describe('AnalyticsCatalog, IndexDocs, AnalyticsTerms', () => {
  it('shows only the configured indices the manifest lists, in display order', () => {
    const analytics = AnalyticsCatalog.fromManifest(manifest);
    expect(analytics.cards.map((card) => card.spec.id)).toEqual(['gdd_winkler', 'huglin', 'bedd', 'gst', 'cool_night', 'budburst', 'gfv', 'gsr']);
    expect(analytics.cards.find((card) => card.spec.id === 'gfv')?.kind).toBe('phenology');
    expect(analytics.risks.map((risk) => risk.spec.id)).toEqual(['botrytis_broome', 'powdery_mildew_gt', 'frost']);
    const few = AnalyticsCatalog.fromManifest({ ...manifest, indices: manifest.indices.filter((spec) => spec.id === 'huglin') });
    expect([few.cards.length, few.risks.length]).toEqual([1, 0]);
  });

  it('builds documentation links from one base URL', () => {
    expect(new IndexDocs(DOCS).url('docs/indices/huglin.md')).toBe(`${DOCS}docs/indices/huglin.md`);
    expect(new IndexDocs(DOCS).url('/docs/x.md')).toBe(`${DOCS}docs/x.md`);
    expect(() => new IndexDocs('https://example.org')).toThrow(RangeError);
  });

  it('labels classes per index and language, falling back to Czech and the id', () => {
    const i18n = new I18n({ cs, de, en }, 'en');
    const terms = new AnalyticsTerms(i18n, { cs: { 'gst.cool': 'chladné', 'x.only_cs': 'jen česky' }, de: {}, en: { 'gst.cool': 'cool' } });
    expect(terms.label('gst', 'cool')).toBe('cool');
    expect(terms.label('x', 'only_cs')).toBe('jen česky');
    expect(terms.label('x', 'unknown')).toBe('unknown');
    expect(new AnalyticsTerms(i18n).label('huglin', 'temperate_warm')).toBe('temperate warm');
  });
});

describe('IndexFormat', () => {
  it('formats values by unit and days of the year as dates', () => {
    const format = new IndexFormat(new I18n({ cs, de, en }, 'en'));
    const entry = (value: number | null, unit: string): IndexValue => ({ value, unit, coverage: 1, complete: true, class: null });
    expect(format.value(entry(1834.24, '°C·d'), 2026)).toBe('1,834 °C·d');
    expect(format.value(entry(0.1312, '1'), 2026)).toBe('0.13');
    expect(format.value(entry(152, 'DOY'), 2026)).toBe('1 Jun 2026'); // 2026 is a common year
    expect(format.value(entry(152, 'DOY'), 2028)).toBe('31 May 2028'); // leap year
    expect(format.value(entry(null, '°C'), 2026)).toBeNull();
    expect(format.percent(0.974)).toBe('97');
  });
});

describe('AnalyticsLoader and AnalyticsPresenter', () => {
  it('loads indices once and daily files per sensor; failures degrade only their part', async () => {
    const base = 'https://example.org/data/';
    const { fetcher, requested } = fakeFetcher(base, {
      'indices/2026.json': fixtureJson('indices/2026.json'),
      [`series/${A}/daily.json`]: fixtureJson(`series/${A}/daily.json`),
    });
    const data = await new AnalyticsLoader(new DataClient(base, fetcher)).load(2026, [A, B]);
    expect(requested).toHaveLength(3);
    expect(data.indicesError).toBeNull();
    expect(data.sensors[0]?.indices?.huglin?.unit).toBe('°C·d');
    expect(data.sensors[1]).toMatchObject({ sensorId: B, daily: null });
    expect(data.sensors[1]?.dailyError).toContain('HTTP 404');
    const missing = await new AnalyticsLoader(new DataClient(base, fetcher)).load(2025, [A]);
    expect(missing.indicesError).toContain('HTTP 404');
    expect(missing.sensors[0]?.indices).toBeNull();
    expect(missing.sensors[0]?.daily?.sensor_id).toBe(A);
  });

  it('shows loading, then only the latest response', async () => {
    const resolvers: ((value: never) => void)[] = [];
    const source: AnalyticsSource = {
      getIndices: () => new Promise((resolve) => resolvers.push(resolve)),
      getDaily: () => Promise.reject(new Error('none')),
    };
    const shown: (string | number)[] = [];
    const view: AnalyticsView = { showMessage: (message) => shown.push(message), showData: (data) => shown.push(data.season) };
    const presenter = new AnalyticsPresenter(new AnalyticsLoader(source), new I18n({ cs, de, en }, 'cs'), view);
    await presenter.refresh(null, [A]);
    await presenter.refresh(2026, []);
    expect(shown).toEqual([]);
    const first = presenter.refresh(2025, [A]);
    const second = presenter.refresh(2026, [A]);
    for (const resolve of resolvers) {
      resolve({ sensors: {} } as never);
    }
    await Promise.all([first, second]);
    expect(shown).toEqual([cs.loading, cs.loading, 2026]);
  });
});

describe('AnalyticsSection', () => {
  it('requests data only when the sensors or the season change', () => {
    const { root, section, requests } = setup();
    section.render([]);
    expect(root.hidden).toBe(true);
    expect(requests).toEqual([]);
    section.render([A]);
    section.render([A]);
    expect(requests).toEqual([[2026, [A]]]); // latest season by default
    const select = root.querySelector('select');
    expect([...(select?.options ?? [])].map((option) => option.value)).toEqual(['2026', '2025']);
    if (select !== null) {
      select.value = '2025';
      select.dispatchEvent(new Event('change'));
    }
    expect(requests.at(-1)).toEqual([2025, [A]]);
    section.showMessage('…');
    expect(text(root.querySelector('.analytics__status'))).toBe('…');
  });

  it('says so when there is no season', () => {
    const i18n = new I18n({ cs, de, en }, 'cs');
    const root = document.createElement('section');
    const parts = { cards: {} as IndexCardsView, risks: {} as RiskStripView, records: {} as RecordsView };
    const section = new AnalyticsSection(root, i18n, AnalyticsCatalog.fromManifest(manifest), catalog, new SensorColors(), parts, [], () => {
      throw new Error('no request expected');
    });
    section.render([A]);
    expect(text(root.querySelector('.analytics__status'))).toBe(cs.analyticsNoSeason);
  });

  it('renders cards, risk strips and records of the demo fixture and redraws on a language change', () => {
    const { root, section, i18n } = setup();
    section.render([A, B]);
    section.showData(fixtureData());
    const table = root.querySelector('.index-table');
    const headers = [...(table?.querySelectorAll('thead th') ?? [])].map(text);
    expect(headers).toEqual(['Ukazatel', `${A} (VUT)`, `${B} (VUT)`]);
    const gddRow = [...(table?.querySelectorAll('tbody tr') ?? [])].find((row) => text(row).startsWith('Suma efektivních'));
    expect(gddRow?.querySelector('a')?.getAttribute('href')).toBe(`${DOCS}docs/indices/gdd_winkler.md`);
    expect(text(gddRow?.querySelector('td') ?? null)).toContain('neúplná data – bez třídy');
    const gfvRow = [...(table?.querySelectorAll('tbody tr') ?? [])].find((row) => text(row).includes('GFV'));
    expect(text(gfvRow ?? null)).toContain('orientační');
    expect(text(gfvRow?.querySelector('td') ?? null)).toContain('bez odhadu');

    const strips = root.querySelectorAll('.risk__strip');
    expect(strips).toHaveLength(6); // 3 risk indices x 2 sensors
    const first = strips[0];
    expect(first?.children).toHaveLength(214); // Apr 1 - Oct 31
    // The demo data start on 1 Jun: April and May have no data and are grey, never green.
    expect(first?.children[0]?.className).toBe('risk-day risk-day--none');
    expect(first?.getAttribute('role')).toBe('img');
    expect(first?.getAttribute('aria-label')).toContain('bez dat');
    expect(root.querySelector('.risk__estimated')).not.toBeNull(); // botrytis uses estimated wetness
    expect(text(root.querySelector('.risk__legend'))).toContain('bez ovlhčení');
    expect(root.querySelector('.risk__ticks')?.children).toHaveLength(7); // Apr..Oct

    const records = root.querySelectorAll('.records__table');
    expect(records).toHaveLength(2);
    expect(text(records[0]?.querySelector('thead') ?? null)).toBe('Sezóna 2026 Všechna data');
    expect(text(root.querySelector('.records .analytics__note'))).toBe(
      'Sezóna 2026: 1. 1. 2026 – 31. 12. 2026: 121 úplných dní z 365, první 1. 6. 2026, poslední 30. 9. 2026.',
    );
    const frostRows = [...(records[0]?.querySelectorAll('tbody tr') ?? [])].slice(5).map(text);
    // Demo data cover only Jun-Sep: neither half of the season is observed, so no "žádný".
    expect(frostRows).toEqual([
      'Poslední jarní mráz žádný v úplných dnech 1. 6. 2026 – 30. 6. 2026 (30 z 181 dní) –',
      'První podzimní mráz žádný v úplných dnech 1. 7. 2026 – 30. 9. 2026 (91 z 184 dní) –',
    ]);
    expect(text(root.querySelector('.analytics__block:last-child > .analytics__note'))).toContain('pod 90 %');
    // GFV is labelled as the véraison date.
    expect(text(gfvRow?.querySelector('th') ?? null)).toContain('zaměkání');

    i18n.setLanguage('en');
    section.render([A, B]);
    expect(text(root.querySelector('h3'))).toBe('Indicators');
    expect(text(root.querySelector('.records__table thead'))).toBe('Season 2026 All data');
  });
});

describe('IndexCardsView, RiskStripView and RecordsView on synthetic entries', () => {
  const i18n = new I18n({ cs, de, en }, 'en');
  const terms = new AnalyticsTerms(i18n);
  const format = new IndexFormat(i18n);
  const docs = new IndexDocs(DOCS);
  const analytics = AnalyticsCatalog.fromManifest(manifest);
  const columns = [{ id: A, label: 'A', color: '#2a78d6' }, { id: B, label: 'B', color: null }];
  const complete: IndexValue = { value: 1834.2, unit: '°C·d', coverage: 0.97, complete: true, class: 'temperate_warm' };
  const noData: IndexValue = { value: null, unit: '°C·d', coverage: 0, complete: false, class: null, status: 'no_data', detail: 'no data' };
  const data = (sensors: AnalyticsData['sensors'], indicesError: string | null = null): AnalyticsData => ({ season: 2026, indicesError, sensors });

  it('shows class, coverage and the no-data states', () => {
    const view = new IndexCardsView(i18n, terms, format, docs);
    const huglin = analytics.cards.filter((card) => card.spec.id === 'huglin');
    const node = view.render(huglin, data([
      { sensorId: A, indices: { huglin: complete }, daily: null, dailyError: null },
      { sensorId: B, indices: { huglin: noData }, daily: null, dailyError: null },
    ]), columns);
    const cells = [...node.querySelectorAll('td')].map(text);
    expect(cells[0]).toBe('1,834 °C·d class: temperate warm coverage 97 %');
    expect(cells[1]).toBe('no data');
    const absent = view.render(huglin, data([{ sensorId: A, indices: null, daily: null, dailyError: null }, { sensorId: B, indices: {}, daily: null, dailyError: null }]), columns);
    expect([...absent.querySelectorAll('td')].map(text)).toEqual(['no data in the season', 'no data']);
    const failed = view.render(huglin, data([], 'HTTP 500'), columns);
    expect(text(failed.querySelector('[role="alert"]'))).toContain('HTTP 500');
  });

  it('shows the daily strip with values, a missing daily block and a no-data entry', () => {
    const view = new RiskStripView(i18n, terms, format, docs);
    const mildew = analytics.risks.filter((risk) => risk.spec.id === 'powdery_mildew_gt');
    const withDaily: IndexValue = {
      value: 70, unit: 'points', coverage: 0.5, complete: false, class: null,
      daily: { levels: ['low', 'moderate', 'high'], start: '2026-06-01', end: '2026-06-03', date: ['2026-06-01', '2026-06-02'], value: [40, 70], level: ['moderate', 'high'] },
    };
    const node = view.render(mildew, data([
      { sensorId: A, indices: { powdery_mildew_gt: withDaily }, daily: null, dailyError: null },
      { sensorId: B, indices: { powdery_mildew_gt: { ...withDaily, daily: undefined } }, daily: null, dailyError: null },
    ]), columns);
    const cells = [...(node?.querySelectorAll('.risk__strip span') ?? [])];
    expect(cells.map((cell) => cell.className)).toEqual(['risk-day risk-day--elevated', 'risk-day risk-day--high', 'risk-day risk-day--none']);
    expect(cells[1]?.getAttribute('title')).toBe('2 Jun 2026: high (70 points)');
    expect(text(node?.querySelector('.risk__summary') ?? null)).toBe('moderate 1 d, high 1 d, no data 1 d. Last day with data 2 Jun 2026: high');
    expect(text(node?.querySelectorAll('.risk__empty')[0] ?? null)).toBe(en.riskNoDailyData);
    expect(node?.querySelector('.risk__estimated')).toBeNull();
    expect(text(node?.querySelector('details') ?? null)).toContain('UC IPM');
    const empty = view.render(mildew, data([{ sensorId: A, indices: null, daily: null, dailyError: null }]), columns.slice(0, 1));
    expect(text(empty?.querySelector('.risk__empty') ?? null)).toBe(en.riskNoData);
    expect(view.render([], data([]), columns)).toBeNull();
    expect(view.render(mildew, data([], 'down'), columns)).toBeNull();
  });

  it('qualifies frost findings and names a period without complete days', () => {
    const view = new RecordsView(i18n, format, new RecordsCalculator(0.9));
    const dates = dateRange('2026-01-01', '2026-12-31');
    const year: DailyFile = {
      sensor_id: A, date: dates, temp_min: dates.map((date) => (date === '2026-03-03' ? -2 : 4)), temp_mean: dates.map(() => 8),
      temp_max: dates.map(() => 12), rh_min: dates.map(() => null), rh_mean: dates.map(() => null), rh_max: dates.map(() => null),
      coverage: dates.map((date) => (date < '2026-02-01' ? 0.5 : 1)),
    };
    const node = view.render(data([{ sensorId: A, indices: null, daily: year, dailyError: null }]), columns.slice(0, 1));
    const rows = [...node.querySelectorAll('.records__table tbody tr')].map(text);
    // January incomplete: spring 150 of 181 days (83 %) -> the frost is qualified; autumn observed, no frost.
    expect(rows[5]).toBe('Last spring frost 3 Mar 2026 (complete days only 1 Feb 2026 – 30 Jun 2026) –');
    expect(rows[6]).toBe('First autumn frost none –');
    const empty = view.render(data([{ sensorId: A, indices: null, daily: { ...year, coverage: dates.map(() => 0) }, dailyError: null }]), columns.slice(0, 1));
    expect(text(empty.querySelector('.records > .analytics__note'))).toBe('Season 2026: 1 Jan 2026 – 31 Dec 2026: no complete day of 365.');
  });

  it('labels the GFV date as véraison', () => {
    const view = new IndexCardsView(i18n, terms, format, docs);
    const gfv = analytics.cards.filter((card) => card.spec.id === 'gfv');
    const entry: IndexValue = { value: 213, unit: 'DOY', coverage: 1, complete: true, class: null };
    const node = view.render(gfv, data([{ sensorId: A, indices: { gfv: entry }, daily: null, dailyError: null }]), columns.slice(0, 1));
    expect(text(node.querySelector('td'))).toBe('véraison 1 Aug 2026 coverage 100 %');
  });

  it('reports a failed daily file and a season without frost', () => {
    const view = new RecordsView(i18n, format, new RecordsCalculator(0.9));
    const warm: DailyFile = {
      sensor_id: A, date: ['2026-06-01'], temp_min: [12.04], temp_mean: [18], temp_max: [25], rh_min: [null], rh_mean: [null], rh_max: [null], coverage: [1],
    };
    const node = view.render(data([
      { sensorId: A, indices: null, daily: warm, dailyError: null },
      { sensorId: B, indices: null, daily: null, dailyError: 'HTTP 404' },
    ]), columns);
    const rows = [...node.querySelectorAll('.records__table tbody tr')].map(text);
    expect(rows[0]).toBe('Lowest temperature 12.0 °C (1 Jun 2026) 12.0 °C (1 Jun 2026)');
    expect(rows[4]).toBe('Highest daily precipitation – –');
    expect(rows[5]).toBe('Last spring frost none on the complete days 1 Jun 2026 – 1 Jun 2026 (1 of 181 days) –');
    expect(rows[6]).toBe('First autumn frost no data –');
    const notes = [...node.querySelectorAll('.records > .analytics__note')].map(text);
    expect(notes).toEqual([
      'Season 2026: 1 Jan 2026 – 31 Dec 2026: 1 complete of 365 days, first 1 Jun 2026, last 1 Jun 2026.',
      'All data: 1 Jun 2026 – 1 Jun 2026: 1 complete of 1 days, first 1 Jun 2026, last 1 Jun 2026.',
    ]);
    expect(text(node.querySelector('[role="alert"]'))).toContain('HTTP 404');
  });
});
