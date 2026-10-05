import type { TimeSeries } from './TimeSeries';

/**
 * Several series on one shared, strictly increasing time axis (the union of all times), the
 * layout uPlot expects. In each column `null` is a gap that charts must not bridge and
 * `undefined` means "this series has no sample at this time", which charts skip over.
 */
export interface AlignedColumns {
  readonly t: readonly number[];
  readonly columns: readonly (readonly (number | null | undefined)[])[];
}

/** Align `series` on the union of their times. */
export function alignSeries(series: readonly TimeSeries[]): AlignedColumns {
  const times = [...new Set(series.flatMap((s) => s.t))].sort((a, b) => a - b);
  const position = new Map(times.map((t, i) => [t, i]));
  const columns = series.map((s) => {
    const column = new Array<number | null | undefined>(times.length).fill(undefined);
    s.t.forEach((t, i) => {
      const index = position.get(t);
      if (index !== undefined) {
        column[index] = s.values[i] ?? null;
      }
    });
    return column;
  });
  return { t: times, columns };
}
