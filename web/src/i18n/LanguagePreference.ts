import { isLanguage, type Language } from './languages';

const STORAGE_KEY = 'sivin.language';

/**
 * Remembers the chosen language in `localStorage`. Storage may be unavailable (private mode,
 * blocked cookies), so every access is guarded and failures are ignored.
 */
export class LanguagePreference {
  /** @param storage - Returns the storage to use; may throw. */
  constructor(private readonly storage: () => Storage) {}

  load(): Language | null {
    try {
      const value = this.storage().getItem(STORAGE_KEY);
      return isLanguage(value) ? value : null;
    } catch {
      return null;
    }
  }

  save(language: Language): void {
    try {
      this.storage().setItem(STORAGE_KEY, language);
    } catch {
      return;
    }
  }
}
