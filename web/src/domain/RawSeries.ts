import type { RawMonthFile } from '../contract';
import { QcMask } from './QcFlags';
import { TimeSeries } from './TimeSeries';

/** Raw variables available in `raw/<YYYY-MM>.json`. */
export type RawVariable = 'temp_c' | 'rh_pct';

interface RawRow {
  readonly t: number;
  readonly temp_c: number | null;
  readonly rh_pct: number | null;
  readonly qc: number;
}

/**
 * Raw samples of one sensor in columnar form, sorted by `t` without duplicates; the merge of
 * one or more monthly contract files.
 */
export class RawSeries {
  private constructor(
    readonly sensorId: string,
    readonly t: readonly number[],
    readonly temp_c: readonly (number | null)[],
    readonly rh_pct: readonly (number | null)[],
    readonly qc: readonly number[],
  ) {}

  /**
   * Merge monthly files into one series sorted by `t`. A time present in several files is kept
   * once, from the file listed last.
   */
  static merge(sensorId: string, files: readonly RawMonthFile[]): RawSeries {
    const rowsByTime = new Map<number, RawRow>();
    for (const file of files) {
      file.t.forEach((t, i) => {
        rowsByTime.set(t, {
          t,
          temp_c: file.temp_c[i] ?? null,
          rh_pct: file.rh_pct[i] ?? null,
          qc: file.qc[i] ?? 0,
        });
      });
    }
    const rows = [...rowsByTime.values()].sort((a, b) => a.t - b.t);
    return RawSeries.fromRows(sensorId, rows);
  }

  private static fromRows(sensorId: string, rows: readonly RawRow[]): RawSeries {
    return new RawSeries(
      sensorId,
      Object.freeze(rows.map((row) => row.t)),
      Object.freeze(rows.map((row) => row.temp_c)),
      Object.freeze(rows.map((row) => row.rh_pct)),
      Object.freeze(rows.map((row) => row.qc)),
    );
  }

  get length(): number {
    return this.t.length;
  }

  /** Samples with `startT <= t < endT` (Unix seconds). */
  between(startT: number, endT: number): RawSeries {
    const keep = this.t.map((t) => t >= startT && t < endT);
    const pick = <T>(column: readonly T[]): readonly T[] =>
      Object.freeze(column.filter((_, i) => keep[i]));
    return new RawSeries(this.sensorId, pick(this.t), pick(this.temp_c), pick(this.rh_pct), pick(this.qc));
  }

  /** One variable as a {@link TimeSeries}; values whose QC flags `mask` excludes become `null`. */
  variable(variable: RawVariable, mask: QcMask): TimeSeries {
    const column = this[variable];
    const values = column.map((value, i) => (mask.excludes(this.qc[i] ?? 0) ? null : value));
    return TimeSeries.of(this.t, values);
  }
}
