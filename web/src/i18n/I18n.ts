import type { LocalizedLabel } from '../contract';
import { MS_PER_SECOND } from '../domain/units';
import type { Dictionary, MessageKey } from './cs';
import { DEFAULT_LANGUAGE, LOCALES, type Language } from './languages';

/** Dictionaries per language; non-default languages may be incomplete and fall back. */
export type Dictionaries = Readonly<Record<Language, Partial<Dictionary>>>;

const PLACEHOLDER_PATTERN = /\{(\w+)\}/g;

/**
 * Translates UI strings and formats numbers and times for the current language.
 *
 * Lookup order: current language → fallback language (Czech) → the key itself.
 */
export class I18n {
  private current: Language;

  /**
   * @param dictionaries - UI strings per language.
   * @param language - Initial language.
   * @param fallback - Language used when a string is missing.
   */
  constructor(
    private readonly dictionaries: Dictionaries,
    language: Language,
    private readonly fallback: Language = DEFAULT_LANGUAGE,
  ) {
    this.current = language;
  }

  get language(): Language {
    return this.current;
  }

  setLanguage(language: Language): void {
    this.current = language;
  }

  /** Translate `key`, replacing `{name}` placeholders with `params.name`. */
  t(key: MessageKey, params: Readonly<Record<string, string | number>> = {}): string {
    const template =
      this.dictionaries[this.current][key] ?? this.dictionaries[this.fallback][key] ?? key;
    return template.replace(PLACEHOLDER_PATTERN, (match, name: string) =>
      name in params ? String(params[name]) : match,
    );
  }

  /** Pick a manifest label (`{cs, de, en}`) for the current language, then fallback, then `defaultText`. */
  label(label: LocalizedLabel, defaultText: string): string {
    return label[this.current] ?? label[this.fallback] ?? defaultText;
  }

  get locale(): string {
    return LOCALES[this.current];
  }

  /**
   * Format a number in the current locale with at most `fractionDigits` decimals (and at least
   * `minFractionDigits`, by default the same, so values line up).
   */
  formatNumber(value: number, fractionDigits: number, minFractionDigits = fractionDigits): string {
    return new Intl.NumberFormat(this.locale, {
      minimumFractionDigits: minFractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(value);
  }

  /** Format Unix seconds as local date and time in `timeZone`. */
  formatDateTime(tS: number, timeZone: string): string {
    return new Intl.DateTimeFormat(this.locale, {
      timeZone,
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(tS * MS_PER_SECOND));
  }

  /** Format Unix seconds as local day and month (e.g. `1. 6.`) in `timeZone`. */
  formatDayMonth(tS: number, timeZone: string): string {
    return new Intl.DateTimeFormat(this.locale, { timeZone, day: 'numeric', month: 'numeric' }).format(
      new Date(tS * MS_PER_SECOND),
    );
  }

  /** Format Unix seconds as local hours and minutes in `timeZone`. */
  formatTime(tS: number, timeZone: string): string {
    return new Intl.DateTimeFormat(this.locale, { timeZone, hour: '2-digit', minute: '2-digit' }).format(
      new Date(tS * MS_PER_SECOND),
    );
  }

  /** Format Unix seconds as a local date in `timeZone`. */
  formatDate(tS: number, timeZone: string): string {
    return new Intl.DateTimeFormat(this.locale, { timeZone, dateStyle: 'medium' }).format(
      new Date(tS * MS_PER_SECOND),
    );
  }
}
