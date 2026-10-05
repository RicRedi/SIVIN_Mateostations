import { describe, expect, it } from 'vitest';
import { cs } from '../src/i18n/cs';
import { de } from '../src/i18n/de';
import { en } from '../src/i18n/en';
import { I18n } from '../src/i18n/I18n';
import { LanguagePreference } from '../src/i18n/LanguagePreference';

describe('I18n', () => {
  it('translates into the current language and switches', () => {
    const i18n = new I18n({ cs, de, en }, 'de');
    expect(i18n.t('sensorsHeading')).toBe('Sensoren');
    i18n.setLanguage('en');
    expect(i18n.language).toBe('en');
    expect(i18n.t('sensorsHeading')).toBe('Sensors');
  });

  it('falls back to Czech, then to the key', () => {
    const i18n = new I18n({ cs: { apply: 'Použít' }, de: {}, en: {} }, 'de');
    expect(i18n.t('apply')).toBe('Použít');
    expect(i18n.t('noData')).toBe('noData');
  });

  it('fills placeholders and leaves unknown ones', () => {
    const i18n = new I18n({ cs, de, en }, 'cs');
    expect(i18n.t('comparisonLimit', { max: 8 })).toBe('Srovnat lze nejvýše 8 čidel.');
    expect(i18n.t('loadError')).toBe('Data se nepodařilo načíst: {message}');
  });

  it('picks manifest labels with fallback', () => {
    const i18n = new I18n({ cs, de, en }, 'en');
    expect(i18n.label({ cs: 'Teplota', en: 'Temperature' }, 'temp_c')).toBe('Temperature');
    expect(i18n.label({ cs: 'Teplota' }, 'temp_c')).toBe('Teplota');
    expect(i18n.label({}, 'temp_c')).toBe('temp_c');
  });

  it('formats numbers and times per language in the display time zone', () => {
    const i18n = new I18n({ cs, de, en }, 'cs');
    expect(i18n.formatNumber(12.44, 1)).toBe('12,4');
    expect(i18n.locale).toBe('cs-CZ');
    // 2026-07-01 10:00Z is 12:00 in Prague (CEST).
    expect(i18n.formatDateTime(1782900000, 'Europe/Prague')).toContain('12:00');
    expect(i18n.formatDate(1782900000, 'Europe/Prague')).toContain('2026');
    expect(i18n.formatTime(1782900000, 'Europe/Prague')).toBe('12:00');
    expect(i18n.formatDayMonth(1782900000, 'Europe/Prague')).toBe('1. 7.');
    expect(i18n.formatNumber(20, 1, 0)).toBe('20');
  });

  it('has a translation of every key in every language', () => {
    expect(Object.keys(de).sort()).toEqual(Object.keys(cs).sort());
    expect(Object.keys(en).sort()).toEqual(Object.keys(cs).sort());
  });
});

describe('LanguagePreference', () => {
  function memoryStorage(): Storage {
    const data = new Map<string, string>();
    return {
      get length() {
        return data.size;
      },
      clear: () => { data.clear(); },
      getItem: (key) => data.get(key) ?? null,
      key: () => null,
      removeItem: (key) => data.delete(key),
      setItem: (key, value) => data.set(key, value),
    };
  }

  it('stores and loads a language', () => {
    const storage = memoryStorage();
    const preference = new LanguagePreference(() => storage);
    expect(preference.load()).toBeNull();
    preference.save('de');
    expect(preference.load()).toBe('de');
    storage.setItem('sivin.language', 'xx');
    expect(preference.load()).toBeNull();
  });

  it('ignores unavailable storage', () => {
    const preference = new LanguagePreference(() => {
      throw new Error('SecurityError');
    });
    expect(preference.load()).toBeNull();
    expect(() => { preference.save('en'); }).not.toThrow();
  });
});
