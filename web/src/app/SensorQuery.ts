import type { SensorInfo } from './SensorCatalog';

const COMBINING_MARKS = /\p{M}/gu;
const WHITESPACE = /\s+/;

/**
 * Text for diacritics- and case-insensitive matching: decomposed (NFD), combining marks removed,
 * lower case. `"Šlechtitelská Ž"` → `"slechtitelska z"`.
 */
export function foldText(text: string): string {
  return text.normalize('NFD').replace(COMBINING_MARKS, '').toLowerCase();
}

/**
 * A search in the sensor picker. A sensor matches when every word of the query occurs in its id,
 * label, municipality, track or variety, ignoring case and diacritics ("ryzl mik" finds
 * "Ryzlink rýnský" in "Mikulov"). An empty query matches every sensor.
 */
export class SensorQuery {
  private constructor(
    readonly text: string,
    private readonly words: readonly string[],
  ) {}

  static parse(text: string): SensorQuery {
    return new SensorQuery(text, foldText(text).split(WHITESPACE).filter((word) => word.length > 0));
  }

  static readonly EMPTY = SensorQuery.parse('');

  get isEmpty(): boolean {
    return this.words.length === 0;
  }

  matches(sensor: SensorInfo): boolean {
    if (this.isEmpty) {
      return true;
    }
    const haystack = foldText(
      [sensor.id, sensor.label, sensor.municipality, sensor.track, sensor.variety]
        .filter((part): part is string => part !== null)
        .join(' '),
    );
    return this.words.every((word) => haystack.includes(word));
  }
}
