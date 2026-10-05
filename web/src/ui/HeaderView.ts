import type { I18n } from '../i18n/I18n';
import { LANGUAGES, type Language } from '../i18n/languages';
import { el } from './dom';

const LANGUAGE_NAMES: Readonly<Record<Language, string>> = {
  cs: 'Čeština',
  de: 'Deutsch',
  en: 'English',
};

/** Page header: title, optional "demo data" badge and the language switch. */
export class HeaderView {
  private readonly title = el('h1', { class: 'header__title' });
  private readonly badge = el('span', { class: 'demo-badge', role: 'note' });
  private readonly languageLabel = el('label', { class: 'visually-hidden', for: 'language-select' });
  private readonly languageSelect = el('select', { id: 'language-select', class: 'header__language' });

  /**
   * @param root - Element the header renders into.
   * @param i18n - Translations.
   * @param showDemoBadge - True when the data are the synthetic fixture.
   * @param onLanguage - Called with the language the user picked.
   */
  constructor(
    root: HTMLElement,
    private readonly i18n: I18n,
    private readonly showDemoBadge: boolean,
    onLanguage: (language: Language) => void,
  ) {
    for (const language of LANGUAGES) {
      this.languageSelect.append(el('option', { value: language, lang: language }, [LANGUAGE_NAMES[language]]));
    }
    this.languageSelect.addEventListener('change', () => {
      onLanguage(this.languageSelect.value as Language);
    });
    root.append(
      this.title,
      ...(showDemoBadge ? [this.badge] : []),
      el('div', { class: 'header__spacer' }),
      this.languageLabel,
      this.languageSelect,
    );
    this.render();
  }

  render(): void {
    this.title.textContent = this.i18n.t('appTitle');
    this.badge.textContent = this.i18n.t('demoBadge');
    this.badge.title = this.i18n.t('demoBadgeTitle');
    this.languageLabel.textContent = this.i18n.t('language');
    this.languageSelect.value = this.i18n.language;
    document.title = this.i18n.t('appTitle');
    document.documentElement.lang = this.i18n.language;
    if (this.showDemoBadge) {
      document.body.classList.add('is-demo');
    }
  }
}
