import type { SensorInfo } from './SensorCatalog';

const COMBINING_MARKS = /\p{M}/gu;
/** Anything that is not a letter or a digit separates words ("Trať 4", "77678271 (VUT)"). */
const WORD_SEPARATORS = /[^\p{L}\p{N}]+/u;

/**
 * Text for diacritics- and case-insensitive matching: decomposed (NFD), combining marks removed,
 * lower case. `"Šlechtitelská Ž"` → `"slechtitelska z"`.
 */
export function foldText(text: string): string {
  return text.normalize('NFD').replace(COMBINING_MARKS, '').toLowerCase();
}

/** The folded words of a text: `"Obec B – Trať 4"` → `["obec", "b", "trat", "4"]`. */
export function foldedWords(text: string): readonly string[] {
  return foldText(text).split(WORD_SEPARATORS).filter((word) => word.length > 0);
}

/**
 * A search in the sensor picker. A sensor matches when every word of the query is the **start of
 * a word** of its id, label, municipality, track or variety, ignoring case and diacritics:
 * "ryzl mik" finds "Ryzlink rýnský" in "Mikulov", "obec b trat 4" finds Obec B / Trať 4 only
 * ("b" does not match inside "obec", "4" not inside an id "90000401"). An empty query matches
 * every sensor.
 */
export class SensorQuery {
  private constructor(
    readonly text: string,
    private readonly words: readonly string[],
  ) {}

  static parse(text: string): SensorQuery {
    return new SensorQuery(text, foldedWords(text));
  }

  static readonly EMPTY = SensorQuery.parse('');

  get isEmpty(): boolean {
    return this.words.length === 0;
  }

  matches(sensor: SensorInfo): boolean {
    if (this.isEmpty) {
      return true;
    }
    const fields = [sensor.id, sensor.label, sensor.municipality, sensor.track, sensor.variety];
    const words = foldedWords(fields.filter((part): part is string => part !== null).join(' '));
    return this.words.every((query) => words.some((word) => word.startsWith(query)));
  }
}
