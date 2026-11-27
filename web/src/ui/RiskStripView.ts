import type { Indicator } from '../app/AnalyticsCatalog';
import type { AnalyticsData } from '../app/AnalyticsLoader';
import type { IndexDocs } from '../app/IndexDocs';
import type { IndexValue } from '../contract';
import { levelTones, RiskStrip, type RiskDay, type RiskTone } from '../domain/RiskStrip';
import type { AnalyticsTerms } from '../i18n/analyticsTerms';
import type { MessageKey } from '../i18n/cs';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import type { IndexFormat } from './IndexFormat';
import { sensorSwatch, type SensorColumn } from './IndexCardsView';

/** Explanation of the bands and the inputs of each index with a risk strip (from `docs/indices`). */
const EXPLANATIONS: Readonly<Record<string, readonly [MessageKey, MessageKey]>> = {
  botrytis_broome: ['riskBands_botrytis_broome', 'riskInputs_botrytis_broome'],
  powdery_mildew_gt: ['riskBands_powdery_mildew_gt', 'riskInputs_powdery_mildew_gt'],
  frost: ['riskBands_frost', 'riskInputs_frost'],
};

/** CSS modifier of a day: its tone, or `none` for a day without data (grey). */
function toneClass(tone: RiskTone | null): string {
  return `risk-day risk-day--${tone ?? 'none'}`;
}

/**
 * The daily risk strips: per risk index and selected sensor one row of days over the index
 * period in traffic-light colours (green / amber / red by the level's rank, grey without data),
 * with hatching for amber and red, month ticks, a text summary (days per level, last day) that
 * is also the strip's accessible name, a legend and an explanation of bands and inputs.
 */
export class RiskStripView {
  constructor(
    private readonly i18n: I18n,
    private readonly terms: AnalyticsTerms,
    private readonly format: IndexFormat,
    private readonly docs: IndexDocs,
  ) {}

  render(indicators: readonly Indicator[], data: AnalyticsData, sensors: readonly SensorColumn[]): HTMLElement | null {
    if (indicators.length === 0 || data.indicesError !== null) {
      return null;
    }
    return el('div', { class: 'analytics__block' }, [
      el('h4', {}, [this.i18n.t('riskHeading')]),
      ...indicators.map((indicator) => this.indexBlock(indicator, data, sensors)),
    ]);
  }

  private indexBlock(indicator: Indicator, data: AnalyticsData, sensors: readonly SensorColumn[]): HTMLElement {
    const { spec } = indicator;
    const label = this.i18n.label(spec.label, spec.id);
    const entries = data.sensors.map((sensor) => sensor.indices?.[spec.id]);
    const strips = sensors.map((sensor, i) => this.sensorRow(spec.id, label, sensor, entries[i]));
    const levels = entries.find((entry) => entry?.daily !== undefined)?.daily?.levels ?? [];
    return el('section', { class: 'risk' }, [
      el('h5', { class: 'risk__title' }, [
        label,
        el('a', { class: 'index-table__doc', href: this.docs.url(spec.doc), target: '_blank', rel: 'noopener' }, [this.i18n.t('howComputed')]),
      ]),
      ...strips,
      this.legend(spec.id, levels),
      this.explanation(spec.id, entries.some((entry) => entry?.estimated === true)),
    ]);
  }

  private sensorRow(indexId: string, indexLabel: string, sensor: SensorColumn, entry: IndexValue | undefined): HTMLElement {
    const name = el('span', { class: 'risk__sensor' }, [sensorSwatch(sensor.color), sensor.label]);
    if (entry?.daily === undefined) {
      const reason = entry === undefined || entry.status === 'no_data' ? 'riskNoData' : 'riskNoDailyData';
      return el('div', { class: 'risk__row' }, [name, el('p', { class: 'risk__empty' }, [this.i18n.t(reason)])]);
    }
    const strip = RiskStrip.fromDaily(entry.daily);
    const summary = this.summary(indexId, strip);
    const accessibleName = this.i18n.t('riskStripLabel', {
      index: indexLabel,
      sensor: sensor.label,
      start: this.format.date(entry.daily.start),
      end: this.format.date(entry.daily.end),
      summary,
    });
    const cells = strip.days.map((day) =>
      el('span', { class: toneClass(day.tone), title: this.dayTitle(indexId, day, entry.unit) }),
    );
    const bar = el('div', { class: 'risk__strip', role: 'img', 'aria-label': accessibleName }, cells);
    bar.style.gridTemplateColumns = `repeat(${String(strip.days.length)}, 1fr)`;
    return el('div', { class: 'risk__row' }, [
      name,
      bar,
      this.monthTicks(strip.days),
      el('p', { class: 'risk__summary' }, [summary]),
    ]);
  }

  /** Days per level, no data last, then the last day with data. */
  private summary(indexId: string, strip: RiskStrip): string {
    const counts = strip
      .counts()
      .filter((count) => count.days > 0)
      .map((count) =>
        this.i18n.t('riskDays', { level: this.levelLabel(indexId, count.level), days: count.days }),
      )
      .join(', ');
    const last = strip.lastKnown();
    const lastText =
      last === null
        ? this.i18n.t('riskNoDays')
        : this.i18n.t('riskLastDay', { date: this.format.date(last.date), level: this.levelLabel(indexId, last.level) });
    return `${counts}. ${lastText}`;
  }

  private levelLabel(indexId: string, level: string | null): string {
    return level === null ? this.i18n.t('riskNoData') : this.terms.label(indexId, level);
  }

  private dayTitle(indexId: string, day: RiskDay, unit: string): string {
    const value = day.value === null ? '' : ` (${this.format.number(day.value, unit)})`;
    return `${this.format.date(day.date)}: ${this.levelLabel(indexId, day.level)}${value}`;
  }

  /** Labels of the first day of each month, placed at its position along the strip. */
  private monthTicks(days: readonly RiskDay[]): HTMLElement {
    const month = new Intl.DateTimeFormat(this.i18n.locale, { month: 'short', timeZone: 'UTC' });
    const ticks = days.flatMap((day, i) => {
      if (!day.date.endsWith('-01')) {
        return [];
      }
      const tick = el('span', { class: 'risk__tick' }, [month.format(new Date(`${day.date}T12:00:00Z`))]);
      tick.style.left = `${String((i / days.length) * 100)}%`;
      return [tick];
    });
    return el('div', { class: 'risk__ticks', 'aria-hidden': 'true' }, ticks);
  }

  private legend(indexId: string, levels: readonly string[]): HTMLElement {
    const items = levelTones(levels).map((count) =>
      el('li', {}, [el('span', { class: toneClass(count.tone), 'aria-hidden': 'true' }), this.levelLabel(indexId, count.level)]),
    );
    return el('ul', { class: 'risk__legend' }, items);
  }

  private explanation(indexId: string, estimated: boolean): HTMLElement {
    const keys = EXPLANATIONS[indexId];
    return el('details', { class: 'risk__explain' }, [
      el('summary', {}, [this.i18n.t('riskBandsHeading')]),
      keys === undefined ? null : el('p', {}, [this.i18n.t(keys[0])]),
      keys === undefined ? null : el('p', {}, [this.i18n.t(keys[1])]),
      estimated ? el('p', { class: 'risk__estimated' }, [el('span', { class: 'badge badge--estimated' }, [this.i18n.t('indexEstimated')]), ' ', this.i18n.t('riskEstimatedInput')]) : null,
      el('p', {}, [this.i18n.t('riskGreyNote')]),
    ]);
  }
}
