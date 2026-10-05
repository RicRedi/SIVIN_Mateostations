import type { DailyFile, DailyValueColumn } from '../contract';
import { TimeSeries } from './TimeSeries';
import type { TimeZone } from './TimeZone';

/**
 * One column of `daily.json` as a {@link TimeSeries} placed at local midnight of each day,
 * keeping only days that start within `[startT, endT)`.
 *
 * @param daily - Validated daily file.
 * @param column - Column to extract, e.g. `temp_mean`.
 * @param zone - Display time zone the `date` column refers to.
 * @param startT - Window start, Unix seconds UTC.
 * @param endT - Window end (exclusive), Unix seconds UTC.
 */
export function dailyColumnSeries(
  daily: DailyFile,
  column: DailyValueColumn,
  zone: TimeZone,
  startT: number,
  endT: number,
): TimeSeries {
  const t: number[] = [];
  const values: (number | null)[] = [];
  daily.date.forEach((date, i) => {
    const dayStartT = zone.startOfDate(date);
    if (dayStartT >= startT && dayStartT < endT) {
      t.push(dayStartT);
      values.push(daily[column][i] ?? null);
    }
  });
  return TimeSeries.of(t, values);
}
