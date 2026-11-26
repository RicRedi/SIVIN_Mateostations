import type { RawMonthFile } from '../contract';
import { QcMask } from './QcFlags';
import { TimeSeries } from './TimeSeries';

/** Measured raw variables of `raw/<YYYY-MM>.json`: temperature and humidity. */
export type RawVariable = 'temp_c' | 'rh_pct';

/**
 * Optional auxiliary raw variables (WP-1.9): precipitation since the previous sample (mm) and
 * battery voltage (V). A file without such a column reads as `null` for each of its samples.
 */
export type AuxiliaryVariable = 'precip_mm' | 'battery_v';

/** Every column of a raw series that holds values. */
export type RawColumn = RawVariable | AuxiliaryVariable;

interface RawRow {
  readonly t: number;
  readonly temp_c: number | null;
  readonly rh_pct: number | null;
  readonly precip_mm: number | null;
  readonly battery_v: number | null;
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
    readonly precip_mm: readonly (number | null)[],
    readonly battery_v: readonly (number | null)[],
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
          precip_mm: file.precip_mm?.[i] ?? null,
          battery_v: file.battery_v?.[i] ?? null,
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
      Object.freeze(rows.map((row) => row.precip_mm)),
      Object.freeze(rows.map((row) => row.battery_v)),
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
    return new RawSeries(
      this.sensorId,
      pick(this.t),
      pick(this.temp_c),
      pick(this.rh_pct),
      pick(this.precip_mm),
      pick(this.battery_v),
      pick(this.qc),
    );
  }

  /** One variable as a {@link TimeSeries}; values whose QC flags `mask` excludes become `null`. */
  variable(variable: RawColumn, mask: QcMask): TimeSeries {
    const column = this[variable];
    const values = column.map((value, i) => (mask.excludes(this.qc[i] ?? 0) ? null : value));
    return TimeSeries.of(this.t, values);
  }
}
