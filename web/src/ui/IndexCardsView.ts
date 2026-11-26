import type { Indicator } from '../app/AnalyticsCatalog';
import type { AnalyticsData } from '../app/AnalyticsLoader';
import type { IndexDocs } from '../app/IndexDocs';
import type { IndexValue } from '../contract';
import type { AnalyticsTerms } from '../i18n/analyticsTerms';
import type { MessageKey } from '../i18n/cs';
import type { I18n } from '../i18n/I18n';
import { el } from './dom';
import type { IndexFormat } from './IndexFormat';

/**
 * The stage whose date a phenology card shows, for models with several stages: GFV publishes
 * only the véraison date (its value), not the flowering date.
 */
const SHOWN_STAGE: Readonly<Record<string, MessageKey>> = { gfv: 'indexGfvStage' };

/** A selected sensor as a column of the comparison: its label and line colour. */
export interface SensorColumn {
  readonly id: string;
  readonly label: string;
  readonly color: string | null;
}

/** A colour swatch for a sensor (decorative: the label is next to it). */
export function sensorSwatch(color: string | null): HTMLElement {
  const swatch = el('span', { class: 'swatch', 'aria-hidden': 'true' });
  swatch.style.background = color ?? 'transparent';
  return swatch;
}

/**
 * The season index cards as a comparison table: one row per index (value with unit, class,
 * coverage, "orientational" / "estimate" marks and the "how it is computed" link), one column
 * per selected sensor. The table scrolls sideways inside its box on narrow screens.
 */
export class IndexCardsView {
  constructor(
    private readonly i18n: I18n,
    private readonly terms: AnalyticsTerms,
    private readonly format: IndexFormat,
    private readonly docs: IndexDocs,
  ) {}

  render(indicators: readonly Indicator[], data: AnalyticsData, sensors: readonly SensorColumn[]): HTMLElement {
    const heading = el('h4', {}, [this.i18n.t('indexCardsHeading')]);
    if (data.indicesError !== null) {
      return el('div', { class: 'analytics__block' }, [
        heading,
        el('p', { class: 'analytics__error', role: 'alert' }, [this.i18n.t('analyticsIndicesError', { message: data.indicesError })]),
      ]);
    }
    const head = el('tr', {}, [
      el('th', { scope: 'col' }, [this.i18n.t('indexColumn')]),
      ...sensors.map((sensor) => el('th', { scope: 'col' }, [sensorSwatch(sensor.color), sensor.label])),
    ]);
    const rows = indicators.map((indicator) =>
      el('tr', {}, [
        this.rowHeader(indicator),
        ...data.sensors.map((sensor) => el('td', {}, this.cell(indicator, sensor.indices?.[indicator.spec.id], data.season, sensor.indices !== null))),
      ]),
    );
    const hasPhenology = indicators.some((indicator) => indicator.kind === 'phenology');
    return el('div', { class: 'analytics__block' }, [
      heading,
      el('div', { class: 'analytics__scroll' }, [
        el('table', { class: 'index-table' }, [el('thead', {}, [head]), el('tbody', {}, rows)]),
      ]),
      hasPhenology ? el('p', { class: 'analytics__note' }, [this.i18n.t('phenologyNote')]) : null,
    ]);
  }

  private rowHeader(indicator: Indicator): HTMLElement {
    const { spec } = indicator;
    return el('th', { scope: 'row' }, [
      el('span', { class: 'index-table__label' }, [this.i18n.label(spec.label, spec.id)]),
      this.stage(spec.id),
      indicator.kind === 'phenology' ? el('span', { class: 'badge badge--orientational' }, [this.i18n.t('indexOrientational')]) : null,
      el('a', { class: 'index-table__doc', href: this.docs.url(spec.doc), target: '_blank', rel: 'noopener' }, [this.i18n.t('howComputed')]),
    ]);
  }

  /** "zaměkání" for GFV: the date shown is véraison. */
  private stage(indexId: string): HTMLElement | null {
    const key = SHOWN_STAGE[indexId];
    return key === undefined ? null : el('span', { class: 'index-table__stage' }, [this.i18n.t(key)]);
  }

  private cell(indicator: Indicator, entry: IndexValue | undefined, season: number, sensorInFile: boolean): (Node | string)[] {
    if (entry === undefined) {
      return [el('span', { class: 'index-table__empty' }, [this.i18n.t(sensorInFile ? 'indexNoData' : 'indexNotInSeason')])];
    }
    if (entry.status === 'no_data') {
      return [el('span', { class: 'index-table__empty' }, [this.i18n.t('indexNoData')])];
    }
    const value = this.format.value(entry, season);
    const parts: (Node | string)[] = [
      value === null
        ? el('span', { class: 'index-table__empty' }, [this.i18n.t('indexNoEstimate')])
        : el('strong', { class: 'index-table__value' }, [value]),
    ];
    if (value !== null) {
      const stage = this.stage(indicator.spec.id);
      if (stage !== null) {
        parts.unshift(stage);
      }
    }
    if (entry.class !== null) {
      parts.push(el('span', { class: 'index-table__class' }, [this.i18n.t('indexClass', { label: this.terms.label(indicator.spec.id, entry.class) })]));
    } else if (!entry.complete && value !== null && indicator.kind !== 'phenology') {
      parts.push(el('span', { class: 'index-table__incomplete' }, [this.i18n.t('indexIncomplete')]));
    }
    parts.push(el('span', { class: 'index-table__coverage' }, [this.i18n.t('indexCoverage', { coverage: this.format.percent(entry.coverage) })]));
    if (entry.estimated === true && indicator.kind !== 'phenology') {
      parts.push(el('span', { class: 'badge badge--estimated' }, [this.i18n.t('indexEstimated')]));
    }
    return parts;
  }
}
