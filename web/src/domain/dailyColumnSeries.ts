import type { DailyFile, DailyValueColumn } from '../contract';
import { TimeSeries } from './TimeSeries';
import type { TimeZone } from './TimeZone';

/** Local hour at which a daily value is drawn: noon, the centre of the day (like hourly means). */
export const DAILY_STAMP_HOUR = 12;

/**
 * One column of `daily.json` as a {@link TimeSeries} drawn at local noon of each day (the bin
 * centre, matching the centred hourly means), keeping only days that start within
 * `[startT, endT)`.
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
      t.push(zone.toUtc({ ...zone.toLocal(dayStartT), hour: DAILY_STAMP_HOUR }));
      values.push(daily[column][i] ?? null);
    }
  });
  return TimeSeries.of(t, values);
}
