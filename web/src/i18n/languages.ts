/** Supported UI languages; Czech is primary. */
export const LANGUAGES = ['cs', 'de', 'en'] as const;
export type Language = (typeof LANGUAGES)[number];
export const DEFAULT_LANGUAGE: Language = 'cs';

/** BCP 47 locale used for number and date formatting per language. */
export const LOCALES: Readonly<Record<Language, string>> = {
  cs: 'cs-CZ',
  de: 'de-DE',
  en: 'en-GB',
};

export function isLanguage(value: unknown): value is Language {
  return LANGUAGES.includes(value as Language);
}
