/**
 * Immutable series of one variable: times in Unix seconds UTC (strictly increasing) and values
 * where `null` means "no valid value".
 */
export class TimeSeries {
  private constructor(
    readonly t: readonly number[],
    readonly values: readonly (number | null)[],
  ) {}

  static readonly EMPTY = new TimeSeries(Object.freeze([]), Object.freeze([]));

  /**
   * @param t - Unix seconds UTC, strictly increasing.
   * @param values - One value or `null` per time.
   * @throws RangeError if lengths differ or times are not strictly increasing.
   */
  static of(t: readonly number[], values: readonly (number | null)[]): TimeSeries {
    if (t.length !== values.length) {
      throw new RangeError(`TimeSeries needs equal lengths, got ${t.length} times and ${values.length} values`);
    }
    for (let i = 1; i < t.length; i++) {
      if ((t[i] ?? 0) <= (t[i - 1] ?? 0)) {
        throw new RangeError(`TimeSeries times must strictly increase (index ${i})`);
      }
    }
    return new TimeSeries(Object.freeze([...t]), Object.freeze([...values]));
  }

  get length(): number {
    return this.t.length;
  }

  /** Number of non-null values. */
  get validCount(): number {
    return this.values.filter((value) => value !== null).length;
  }

  /**
   * Insert a `null` between consecutive samples farther apart than `maxStepS`, so that charts
   * draw a gap instead of a line across missing data.
   *
   * @param maxStepS - Largest step (seconds) still drawn as a continuous line.
   */
  withGapBreaks(maxStepS: number): TimeSeries {
    const t: number[] = [];
    const values: (number | null)[] = [];
    this.t.forEach((time, i) => {
      const previous = this.t[i - 1];
      if (previous !== undefined && time - previous > maxStepS) {
        t.push(Math.round((previous + time) / 2));
        values.push(null);
      }
      t.push(time);
      values.push(this.values[i] ?? null);
    });
    return TimeSeries.of(t, values);
  }
}
