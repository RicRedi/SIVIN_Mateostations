import {
  parseDailyFile,
  parseEventsFile,
  parseIndicesFile,
  parseLatestFile,
  parseManifest,
  parseRawMonthFile,
  parseSensorsGeoJSON,
  type DailyFile,
  type EventsFile,
  type IndicesFile,
  type LatestFile,
  type Manifest,
  type RawMonthFile,
  type SensorsGeoJSON,
} from '../contract';
import { RawSeries } from '../domain/RawSeries';
import { DataLoadError } from './DataLoadError';
import { utcMonthKeys } from './monthKeys';

/** The subset of the Fetch API response that {@link DataClient} needs. */
export interface JsonResponse {
  readonly ok: boolean;
  readonly status: number;
  json(): Promise<unknown>;
}

/** Fetches a URL; `window.fetch` satisfies this, tests pass a mock. */
export type JsonFetcher = (url: string) => Promise<JsonResponse>;

type Parser<T> = (value: unknown, file: string) => T;

/**
 * Loads and caches the files of the static site data contract (MIGRATION_PLAN.md §2.6).
 *
 * Every file is fetched at most once per instance; each result is validated against the
 * contract before it is returned.
 */
export class DataClient {
  private readonly cache = new Map<string, Promise<unknown>>();

  /**
   * @param baseUrl - URL of the `data/` directory, ending with `/`.
   * @param fetcher - Function used for HTTP requests.
   */
  constructor(
    private readonly baseUrl: string,
    private readonly fetcher: JsonFetcher,
  ) {}

  getManifest(): Promise<Manifest> {
    return this.load('manifest.json', parseManifest);
  }

  getSensors(): Promise<SensorsGeoJSON> {
    return this.load('sensors.geojson', parseSensorsGeoJSON);
  }

  getLatest(): Promise<LatestFile> {
    return this.load('latest.json', parseLatestFile);
  }

  getDaily(sensorId: string): Promise<DailyFile> {
    return this.load(`series/${encodeURIComponent(sensorId)}/daily.json`, parseDailyFile);
  }

  getEvents(sensorId: string): Promise<EventsFile> {
    return this.load(`events/${encodeURIComponent(sensorId)}.json`, parseEventsFile);
  }

  getIndices(season: number): Promise<IndicesFile> {
    return this.load(`indices/${season}.json`, parseIndicesFile);
  }

  /**
   * Raw samples of one sensor with `startT <= t < endT`.
   *
   * Fetches, in parallel, exactly the `raw/<YYYY-MM>.json` files of the UTC months that overlap
   * the window and that the manifest lists for the sensor; months not in the manifest are
   * skipped. A listed month whose file cannot be loaded fails the whole call.
   *
   * @param sensorId - Canonical 8-digit sensor id.
   * @param startT - Window start, Unix seconds UTC.
   * @param endT - Window end (exclusive), Unix seconds UTC.
   * @throws Error if the manifest does not know the sensor.
   * @throws DataLoadError or ContractError if a listed month cannot be loaded.
   */
  async getRawRange(sensorId: string, startT: number, endT: number): Promise<RawSeries> {
    const months = await this.rawMonthsFor(sensorId, startT, endT);
    const files = await Promise.all(months.map((month) => this.getRawMonth(sensorId, month)));
    return RawSeries.merge(sensorId, files).between(startT, endT);
  }

  /** The `YYYY-MM` keys that {@link getRawRange} would fetch for this window. */
  async rawMonthsFor(sensorId: string, startT: number, endT: number): Promise<readonly string[]> {
    const manifest = await this.getManifest();
    const entry = manifest.sensors[sensorId];
    if (entry === undefined) {
      throw new Error(`Sensor ${sensorId} is not listed in manifest.json`);
    }
    const available = new Set(entry.raw_months);
    return utcMonthKeys(startT, endT).filter((month) => available.has(month));
  }

  private getRawMonth(sensorId: string, month: string): Promise<RawMonthFile> {
    return this.load(`series/${encodeURIComponent(sensorId)}/raw/${month}.json`, (value, file) => {
      const parsed = parseRawMonthFile(value, file);
      if (parsed.sensor_id !== sensorId) {
        throw new DataLoadError(file, `contains sensor ${parsed.sensor_id}, expected ${sensorId}`);
      }
      return parsed;
    });
  }

  private load<T>(path: string, parse: Parser<T>): Promise<T> {
    const cached = this.cache.get(path);
    if (cached !== undefined) {
      return cached as Promise<T>;
    }
    const pending = this.fetchJson(path).then((json) => parse(json, path));
    this.cache.set(path, pending);
    pending.catch(() => this.cache.delete(path));
    return pending;
  }

  private async fetchJson(path: string): Promise<unknown> {
    const url = `${this.baseUrl}${path}`;
    let response: JsonResponse;
    try {
      response = await this.fetcher(url);
    } catch (error) {
      throw new DataLoadError(url, error instanceof Error ? error.message : String(error));
    }
    if (!response.ok) {
      throw new DataLoadError(url, `HTTP ${response.status}`);
    }
    try {
      return await response.json();
    } catch {
      throw new DataLoadError(url, 'response is not valid JSON');
    }
  }
}
