import type { MessageKey } from '../i18n/cs';
import type { I18n } from '../i18n/I18n';
import { RESOLUTIONS, type Resolution, type TimeWindow } from '../domain/TimeWindow';
import type { TimeZone } from '../domain/TimeZone';
import { MS_PER_SECOND } from '../domain/units';
import type { ResolutionChoice, WindowKind, WindowSpec } from '../domain/WindowSpec';
import { el } from './dom';

/** A change requested by the user; absent fields stay as they are. */
export interface WindowChange {
  readonly window?: WindowSpec;
  readonly resolution?: ResolutionChoice;
}

/** What the control displays. */
export interface WindowControlState {
  readonly spec: WindowSpec;
  readonly resolution: ResolutionChoice;
  /** The concrete window currently shown (gives the automatic resolution and custom defaults). */
  readonly window: TimeWindow;
}

const KIND_LABELS: Readonly<Record<WindowKind, MessageKey>> = {
  '24h': 'preset24h',
  '7d': 'preset7d',
  '30d': 'preset30d',
  season: 'presetSeason',
  custom: 'presetCustom',
};

const RESOLUTION_LABELS: Readonly<Record<Resolution, MessageKey>> = {
  raw: 'resolutionRaw',
  hourly: 'resolutionHourly',
  daily: 'resolutionDaily',
};

/**
 * Time-window controls: presets 24 h / 7 d / 30 d / season / custom from–to, and a resolution
 * selector whose "automatic" entry names the resolution it currently picks.
 */
export class TimeWindowControl {
  private readonly legend = el('legend', { class: 'panel__heading' });
  private readonly presetButtons = new Map<WindowKind, HTMLButtonElement>();
  private readonly seasonRow = el('div', { class: 'window-control__row' });
  private readonly seasonLabel = el('label', { for: 'season-year' });
  private readonly seasonSelect = el('select', { id: 'season-year' });
  private readonly customRow = el('form', { class: 'window-control__row' });
  private readonly fromLabel = el('label', { for: 'custom-from' });
  private readonly fromInput = el('input', { type: 'date', id: 'custom-from', required: true });
  private readonly toLabel = el('label', { for: 'custom-to' });
  private readonly toInput = el('input', { type: 'date', id: 'custom-to', required: true });
  private readonly applyButton = el('button', { type: 'submit' });
  private readonly resolutionLabel = el('label', { for: 'resolution-select' });
  private readonly resolutionSelect = el('select', { id: 'resolution-select' });
  private readonly shown = el('p', { class: 'window-control__shown', 'aria-live': 'polite' });
  private current: WindowControlState | null = null;

  /**
   * @param root - Container element.
   * @param i18n - Translations.
   * @param zone - Display time zone for custom dates.
   * @param seasons - Season years offered (from the manifest), ascending.
   * @param onChange - Called when the user changes window or resolution.
   */
  constructor(
    root: HTMLElement,
    private readonly i18n: I18n,
    private readonly zone: TimeZone,
    private readonly seasons: readonly number[],
    private readonly onChange: (change: WindowChange) => void,
  ) {
    const presets = el('div', { class: 'window-control__presets', role: 'group' });
    for (const kind of Object.keys(KIND_LABELS) as WindowKind[]) {
      const button = el('button', { type: 'button', 'data-kind': kind, 'aria-pressed': 'false' });
      button.addEventListener('click', () => {
        this.selectKind(kind);
      });
      this.presetButtons.set(kind, button);
      presets.append(button);
    }
    for (const year of seasons) {
      this.seasonSelect.append(el('option', { value: year }, [String(year)]));
    }
    this.seasonSelect.addEventListener('change', () => {
      this.onChange({ window: { kind: 'season', year: Number(this.seasonSelect.value) } });
    });
    this.customRow.addEventListener('submit', (event) => {
      event.preventDefault();
      this.applyCustom();
    });
    this.resolutionSelect.addEventListener('change', () => {
      this.onChange({ resolution: this.resolutionSelect.value as ResolutionChoice });
    });
    this.seasonRow.append(this.seasonLabel, this.seasonSelect);
    this.customRow.append(this.fromLabel, this.fromInput, this.toLabel, this.toInput, this.applyButton);
    const resolutionRow = el('div', { class: 'window-control__row' }, [this.resolutionLabel, this.resolutionSelect]);
    root.append(
      el('fieldset', { class: 'window-control' }, [
        this.legend,
        presets,
        this.seasonRow,
        this.customRow,
        resolutionRow,
        this.shown,
      ]),
    );
  }

  render(state: WindowControlState): void {
    this.current = state;
    this.legend.textContent = this.i18n.t('windowHeading');
    for (const [kind, button] of this.presetButtons) {
      button.textContent = this.i18n.t(KIND_LABELS[kind]);
      button.setAttribute('aria-pressed', String(kind === state.spec.kind));
    }
    this.seasonLabel.textContent = this.i18n.t('seasonYear');
    this.seasonRow.hidden = state.spec.kind !== 'season';
    if (state.spec.kind === 'season') {
      this.seasonSelect.value = String(state.spec.year);
    }
    this.fromLabel.textContent = this.i18n.t('dateFrom');
    this.toLabel.textContent = this.i18n.t('dateTo');
    this.applyButton.textContent = this.i18n.t('apply');
    this.customRow.hidden = state.spec.kind !== 'custom';
    if (state.spec.kind === 'custom') {
      this.fromInput.value = state.spec.from;
      this.toInput.value = state.spec.to;
    }
    this.renderResolutions(state);
    this.renderShownWindow(state.window);
  }

  /** The concrete window actually shown (relative presets end at the end of the data). */
  private renderShownWindow(window: TimeWindow): void {
    const range = this.i18n.t('windowShown', {
      from: this.i18n.formatDateTime(window.startT, this.zone.name),
      to: this.i18n.formatDateTime(window.endT, this.zone.name),
    });
    this.shown.textContent = `${range} · ${this.i18n.t(RESOLUTION_LABELS[window.resolution])}`;
  }

  private renderResolutions(state: WindowControlState): void {
    this.resolutionLabel.textContent = this.i18n.t('resolution');
    const automatic = `${this.i18n.t('resolutionAuto')} (${this.i18n.t(RESOLUTION_LABELS[state.window.resolution])})`;
    const options = [el('option', { value: 'auto' }, [automatic])];
    for (const resolution of RESOLUTIONS) {
      options.push(el('option', { value: resolution }, [this.i18n.t(RESOLUTION_LABELS[resolution])]));
    }
    this.resolutionSelect.replaceChildren(...options);
    this.resolutionSelect.value = state.resolution;
  }

  private selectKind(kind: WindowKind): void {
    if (kind === 'season') {
      this.onChange({ window: { kind, year: this.defaultSeasonYear() } });
    } else if (kind === 'custom') {
      this.onChange({ window: this.customFromCurrentWindow() });
    } else {
      this.onChange({ window: { kind } });
    }
  }

  private defaultSeasonYear(): number {
    const window = this.current?.window;
    const fallbackYear = window ? this.zone.toLocal(window.endT - 1).year : new Date().getFullYear();
    return this.seasons.at(-1) ?? fallbackYear;
  }

  private customFromCurrentWindow(): WindowSpec {
    const window = this.current?.window;
    if (window === undefined) {
      const today = this.zone.isoDate(Date.now() / MS_PER_SECOND);
      return { kind: 'custom', from: today, to: today };
    }
    return { kind: 'custom', from: this.zone.isoDate(window.startT), to: this.zone.isoDate(window.endT - 1) };
  }

  private applyCustom(): void {
    const from = this.fromInput.value;
    const to = this.toInput.value;
    if (from !== '' && to !== '') {
      this.onChange({ window: { kind: 'custom', from, to } });
    }
  }
}
