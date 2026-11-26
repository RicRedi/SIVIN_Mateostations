import type { IndexValue } from '../contract';
import { addDays, noonUtcSeconds } from '../domain/isoDates';
import type { I18n } from '../i18n/I18n';

/** Unit of the phenology indices: the value is a day of the year (1 = January 1). */
export const DAY_OF_YEAR_UNIT = 'DOY';
/** Unit of a dimensionless index (e.g. an infection probability 0-1); not shown. */
export const DIMENSIONLESS_UNIT = '1';

/** Display decimals per index unit; other units use {@link DEFAULT_DECIMALS}. */
const UNIT_DECIMALS: Readonly<Record<string, number>> = {
  '°C·d': 0,
  '°C': 1,
  h: 1,
  [DIMENSIONLESS_UNIT]: 2,
  points: 0,
  d: 0,
  kPa: 2,
};
const DEFAULT_DECIMALS = 1;
const PERCENT = 100;

/**
 * Formats index values for the UI: numbers with the decimals of their unit, days of the year
 * as dates of the season, shares as percentages, local dates without a time-zone shift.
 */
export class IndexFormat {
  constructor(private readonly i18n: I18n) {}

  /** A number in `unit` with its unit, e.g. `1 834 °C·d`; dimensionless without a unit. */
  number(value: number, unit: string): string {
    const text = this.i18n.formatNumber(value, UNIT_DECIMALS[unit] ?? DEFAULT_DECIMALS);
    return unit === DIMENSIONLESS_UNIT ? text : `${text} ${unit}`;
  }

  /** The value of an entry; a day of the year becomes the date in `season`. `null` = no value. */
  value(entry: IndexValue, season: number): string | null {
    if (entry.value === null) {
      return null;
    }
    if (entry.unit === DAY_OF_YEAR_UNIT) {
      return this.date(addDays(`${String(season)}-01-01`, Math.round(entry.value) - 1));
    }
    return this.number(entry.value, entry.unit);
  }

  /** A share 0-1 as a whole percentage number (no `%` sign), e.g. `0.974` → `97`. */
  percent(share: number): string {
    return this.i18n.formatNumber(share * PERCENT, 0);
  }

  /** A local calendar date `YYYY-MM-DD` in the current language. */
  date(isoDate: string): string {
    return this.i18n.formatDate(noonUtcSeconds(isoDate), 'UTC');
  }
}
