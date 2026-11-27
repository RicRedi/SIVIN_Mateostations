import type { DailyFile, IndexValue } from '../contract';

/** The data client calls the analytics need. */
export interface AnalyticsSource {
  getIndices(season: number): Promise<{ readonly sensors: Readonly<Record<string, Readonly<Record<string, IndexValue>>>> }>;
  getDaily(sensorId: string): Promise<DailyFile>;
}

/**
 * Analytics input of one sensor: its index entries of the season (`null` if the indices file
 * has none for it, e.g. no data in the season) and its daily file (`null` if it failed, with
 * `dailyError`).
 */
export interface SensorAnalytics {
  readonly sensorId: string;
  readonly indices: Readonly<Record<string, IndexValue>> | null;
  readonly daily: DailyFile | null;
  readonly dailyError: string | null;
}

/** Analytics input of the selected sensors for one season. */
export interface AnalyticsData {
  readonly season: number;
  /** Set when `indices/<season>.json` could not be loaded; the records still work. */
  readonly indicesError: string | null;
  readonly sensors: readonly SensorAnalytics[];
}

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

/**
 * Loads `indices/<season>.json` once and `series/<id>/daily.json` per sensor, in parallel. A
 * failing file degrades only its part: without the indices file the cards and strips show the
 * error and the records still show, a failing daily file affects only its sensor's records.
 */
export class AnalyticsLoader {
  constructor(private readonly source: AnalyticsSource) {}

  async load(season: number, sensorIds: readonly string[]): Promise<AnalyticsData> {
    const [[indices], dailies] = await Promise.all([
      Promise.allSettled([this.source.getIndices(season)]),
      Promise.allSettled(sensorIds.map((id) => this.source.getDaily(id))),
    ]);
    const indexFile = indices.status === 'fulfilled' ? indices.value : null;
    return {
      season,
      indicesError: indices.status === 'rejected' ? message(indices.reason) : null,
      sensors: sensorIds.map((sensorId, i) => {
        const daily = dailies[i];
        return {
          sensorId,
          indices: indexFile?.sensors[sensorId] ?? null,
          daily: daily?.status === 'fulfilled' ? daily.value : null,
          dailyError: daily?.status === 'rejected' ? message(daily.reason) : null,
        };
      }),
    };
  }
}
