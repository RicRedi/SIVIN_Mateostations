import { RESOLUTIONS, type Resolution } from '../domain/TimeWindow';
import { RELATIVE_PRESETS, type RelativePreset, type ResolutionChoice, type WindowSpec } from '../domain/WindowSpec';
import { isLanguage } from '../i18n/languages';
import type { AppState } from './AppState';

const SENSOR_ID_PATTERN = /^[A-Za-z0-9_-]+$/;
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const YEAR_PATTERN = /^\d{4}$/;
const ISO_DATE_LENGTH = 'YYYY-MM-DD'.length;
const YEAR_PATTERN_LENGTH = 4;

/** Years accepted from a URL; anything else is ignored (protects against absurd windows). */
export const MIN_URL_YEAR = 2000;
export const MAX_URL_YEAR = 2100;

function isSaneYear(year: number): boolean {
  return year >= MIN_URL_YEAR && year <= MAX_URL_YEAR;
}

/** True for a real calendar date `YYYY-MM-DD` (it round-trips through `Date`) in a sane year. */
function isValidIsoDate(text: string): boolean {
  if (!ISO_DATE_PATTERN.test(text)) {
    return false;
  }
  const time = Date.parse(`${text}T00:00:00Z`);
  return (
    !Number.isNaN(time) &&
    new Date(time).toISOString().slice(0, ISO_DATE_LENGTH) === text &&
    isSaneYear(Number(text.slice(0, YEAR_PATTERN_LENGTH)))
  );
}

const AUTO: ResolutionChoice = 'auto';

/**
 * Converts the shareable part of {@link AppState} to and from the URL hash, e.g.
 * `#s=77678271,77680921&w=7d&r=hourly&lang=cs`, `#w=season&y=2026` or
 * `#w=custom&from=2026-06-01&to=2026-06-15`. `r` is omitted for automatic resolution.
 * Dates must be real calendar dates and years must lie in {@link MIN_URL_YEAR}–{@link MAX_URL_YEAR}.
 */
export class HashStateCodec {
  encode(state: AppState): string {
    const parts: string[] = [];
    if (state.selectedSensorIds.length > 0) {
      parts.push(`s=${state.selectedSensorIds.map(encodeURIComponent).join(',')}`);
    }
    parts.push(...this.encodeWindow(state.window));
    if (state.resolution !== AUTO) {
      parts.push(`r=${state.resolution}`);
    }
    parts.push(`lang=${state.language}`);
    return `#${parts.join('&')}`;
  }

  /**
   * Read state fields from a hash. Missing or invalid fields are left out, so the caller can
   * merge the result over defaults. Repeated sensor ids are kept once, at their first position.
   */
  decode(hash: string): Partial<AppState> {
    const params = new URLSearchParams(hash.replace(/^#/, ''));
    const result: { -readonly [K in keyof AppState]?: AppState[K] } = {};
    const sensors = params.get('s');
    if (sensors !== null) {
      const ids = sensors.split(',').filter((id) => SENSOR_ID_PATTERN.test(id));
      result.selectedSensorIds = [...new Set(ids)];
    }
    const window = this.decodeWindow(params);
    if (window !== null) {
      result.window = window;
    }
    const resolution = params.get('r');
    if (resolution === AUTO || RESOLUTIONS.includes(resolution as Resolution)) {
      result.resolution = resolution as ResolutionChoice;
    }
    const language = params.get('lang');
    if (isLanguage(language)) {
      result.language = language;
    }
    return result;
  }

  private encodeWindow(window: WindowSpec): readonly string[] {
    switch (window.kind) {
      case 'season':
        return ['w=season', `y=${window.year}`];
      case 'custom':
        return ['w=custom', `from=${window.from}`, `to=${window.to}`];
      default:
        return [`w=${window.kind}`];
    }
  }

  private decodeWindow(params: URLSearchParams): WindowSpec | null {
    const kind = params.get('w');
    if (RELATIVE_PRESETS.includes(kind as RelativePreset)) {
      return { kind: kind as RelativePreset };
    }
    if (kind === 'season') {
      const year = params.get('y') ?? '';
      return YEAR_PATTERN.test(year) && isSaneYear(Number(year)) ? { kind: 'season', year: Number(year) } : null;
    }
    if (kind === 'custom') {
      const from = params.get('from') ?? '';
      const to = params.get('to') ?? '';
      return isValidIsoDate(from) && isValidIsoDate(to)
        ? { kind: 'custom', from, to }
        : null;
    }
    return null;
  }
}
