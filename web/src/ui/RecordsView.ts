import type { AnalyticsData, SensorAnalytics } from '../app/AnalyticsLoader';
import { HALF_OBSERVED_SHARE, type DatedValue, type DaySpan, type FrostFinding, type RecordsCalculator, type RecordsSummary } from '../domain/SensorRecords';
import type { MessageKey } from '../i18n/cs';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import { sensorSwatch, type SensorColumn } from './IndexCardsView';
import type { IndexFormat } from './IndexFormat';

type DatedRow = readonly [MessageKey, (summary: RecordsSummary) => DatedValue | null, string];
type FrostRow = readonly [MessageKey, (summary: RecordsSummary) => FrostFinding | null];

const DATED_ROWS: readonly DatedRow[] = [
  ['recordTempMin', (summary) => summary.tempMin, '°C'],
  ['recordTempMax', (summary) => summary.tempMax, '°C'],
  ['recordHighestMean', (summary) => summary.highestMean, '°C'],
  ['recordLowestMean', (summary) => summary.lowestMean, '°C'],
  ['recordMaxPrecip', (summary) => summary.maxPrecip, 'mm'],
];
const FROST_ROWS: readonly FrostRow[] = [
  ['recordLastSpringFrost', (summary) => summary.lastSpringFrost],
  ['recordFirstAutumnFrost', (summary) => summary.firstAutumnFrost],
];
const TEMPERATURE_DECIMALS = 1;
const PERCENT = 100;

/**
 * Records and extremes per selected sensor, for the season and for all its data, computed in
 * the browser from `daily.json` ({@link RecordsCalculator}); a note names the period, how many of
 * its days were complete and used, and that incomplete days do not count. "No frost" is said only
 * for an observed half season.
 */
export class RecordsView {
  constructor(
    private readonly i18n: I18n,
    private readonly format: IndexFormat,
    private readonly calculator: RecordsCalculator,
  ) {}

  render(data: AnalyticsData, sensors: readonly SensorColumn[]): HTMLElement {
    return el('div', { class: 'analytics__block' }, [
      el('h4', {}, [this.i18n.t('recordsHeading')]),
      ...data.sensors.map((sensor, i) => this.sensorRecords(sensor, sensors[i], data.season)),
      el('p', { class: 'analytics__note' }, [
        this.i18n.t('recordsCoverageRule', { coverage: this.percent(this.calculator.minDailyCoverage) }),
        ' ',
        this.i18n.t('recordsFrostNote', { share: this.percent(HALF_OBSERVED_SHARE) }),
      ]),
    ]);
  }

  private sensorRecords(sensor: SensorAnalytics, column: SensorColumn | undefined, season: number): HTMLElement {
    const title = el('h5', { class: 'records__title' }, [sensorSwatch(column?.color ?? null), column?.label ?? sensor.sensorId]);
    if (sensor.daily === null) {
      const message = sensor.dailyError ?? '';
      return el('div', { class: 'records' }, [title, el('p', { class: 'analytics__error', role: 'alert' }, [this.i18n.t('analyticsDailyError', { message })])]);
    }
    const inSeason = this.calculator.season(sensor.daily, season);
    const all = this.calculator.allData(sensor.daily);
    const seasonHead = this.i18n.t('recordsSeason', { season });
    const allHead = this.i18n.t('recordsAll');
    const rows = [
      ...DATED_ROWS.map(([key, pick, unit]) => this.row(key, this.dated(pick(inSeason), unit), this.dated(pick(all), unit))),
      ...FROST_ROWS.map(([key, pick]) => this.row(key, this.frost(pick(inSeason)), this.i18n.t('recordNone'))),
    ];
    return el('div', { class: 'records' }, [
      title,
      el('div', { class: 'analytics__scroll' }, [
        el('table', { class: 'records__table' }, [
          el('thead', {}, [el('tr', {}, [el('td', {}), el('th', { scope: 'col' }, [seasonHead]), el('th', { scope: 'col' }, [allHead])])]),
          el('tbody', {}, rows),
        ]),
      ]),
      el('p', { class: 'analytics__note' }, [`${seasonHead}: ${this.daysUsed(inSeason.span)}`]),
      el('p', { class: 'analytics__note' }, [`${allHead}: ${this.daysUsed(all.span)}`]),
    ]);
  }

  private row(key: MessageKey, seasonText: string, allText: string): HTMLElement {
    return el('tr', {}, [el('th', { scope: 'row' }, [this.i18n.t(key)]), el('td', {}, [seasonText]), el('td', {}, [allText])]);
  }

  private dated(value: DatedValue | null, unit: string): string {
    if (value === null) {
      return this.i18n.t('recordNone');
    }
    return `${this.i18n.formatNumber(value.value, TEMPERATURE_DECIMALS)} ${unit} (${this.format.date(value.date)})`;
  }

  /** A frost finding; "none" only for an observed half (see {@link FrostFinding}). */
  private frost(finding: FrostFinding | null): string {
    if (finding === null) {
      return this.i18n.t('recordNone');
    }
    const { span } = finding;
    const range = {
      first: span.firstUsed === null ? '' : this.format.date(span.firstUsed),
      last: span.lastUsed === null ? '' : this.format.date(span.lastUsed),
      used: span.daysUsed,
      period: span.periodDays,
    };
    switch (finding.kind) {
      case 'found':
        return finding.observed
          ? this.format.date(finding.date)
          : this.i18n.t('recordFrostPartial', { ...range, date: this.format.date(finding.date) });
      case 'none':
        return this.i18n.t('recordNoFrost');
      case 'noneInData':
        return this.i18n.t('recordNoFrostInData', range);
      case 'noData':
        return this.i18n.t('recordFrostNoData');
    }
  }

  private daysUsed(span: DaySpan): string {
    const period = {
      start: span.start === '' ? '' : this.format.date(span.start),
      end: span.end === '' ? '' : this.format.date(span.end),
      period: span.periodDays,
    };
    if (span.firstUsed === null || span.lastUsed === null) {
      return this.i18n.t('recordsNoDaysUsed', period);
    }
    return this.i18n.t('recordsDaysUsed', {
      ...period,
      used: span.daysUsed,
      first: this.format.date(span.firstUsed),
      last: this.format.date(span.lastUsed),
    });
  }

  private percent(share: number): string {
    return this.i18n.formatNumber(share * PERCENT, 0);
  }
}
