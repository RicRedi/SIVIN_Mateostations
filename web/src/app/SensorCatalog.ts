import type { LatestFile, LatestSample, Manifest, SensorsGeoJSON } from '../contract';

const MS_PER_SECOND = 1000;

/** `sample` with `stale` also set when it is older than `staleAfterS` at `nowS`. */
export function withStaleness(
  sample: LatestSample | null,
  staleAfterS: number | undefined,
  nowS: number,
): LatestSample | null {
  if (sample === null || sample.stale || staleAfterS === undefined || nowS - sample.t <= staleAfterS) {
    return sample;
  }
  return { ...sample, stale: true };
}

/** Everything the UI shows about one sensor, joined from registry, manifest and latest values. */
export interface SensorInfo {
  readonly id: string;
  readonly label: string;
  readonly lat: number;
  readonly lon: number;
  readonly elevation_m: number | null;
  /** `from` of the current placement (ISO 8601), i.e. when the sensor was deployed there. */
  readonly placedSince: string | null;
  /** Municipality (obec); the first grouping level of the sensor picker. */
  readonly municipality: string | null;
  /** Vineyard track (viniční trať) within the municipality; the second grouping level. */
  readonly track: string | null;
  readonly variety: string | null;
  /** Registry life-cycle state: `active`, `inactive` or `retired`. */
  readonly status: string;
  readonly latest: LatestSample | null;
  /** True when the manifest lists data for the sensor. */
  readonly hasData: boolean;
}

/** Read-only collection of {@link SensorInfo}, in registry order. */
export class SensorCatalog {
  private readonly byId: ReadonlyMap<string, SensorInfo>;

  private constructor(readonly sensors: readonly SensorInfo[]) {
    this.byId = new Map(sensors.map((sensor) => [sensor.id, sensor]));
  }

  /**
   * Join the registry copy with manifest availability and `latest.json`.
   *
   * A latest sample is stale if the pipeline said so (`stale`, judged at `generated_at`) or if it
   * is older than the manifest's `stale_after_s` at `nowS`, so the map greys sensors out even when
   * the pipeline has stopped publishing (WP-3.2).
   *
   * @param nowS - Current time in Unix seconds; the system clock by default.
   */
  static build(
    registry: SensorsGeoJSON,
    manifest: Manifest,
    latest: LatestFile,
    nowS: number = Date.now() / MS_PER_SECOND,
  ): SensorCatalog {
    const sensors = registry.features.map((feature): SensorInfo => {
      const p = feature.properties;
      const current = p.placements.find((placement) => placement.to === null) ?? p.placements.at(-1);
      const [lon, lat] = feature.geometry.coordinates;
      return {
        id: p.id,
        label: p.label,
        lat,
        lon,
        elevation_m: current?.elevation_m ?? null,
        placedSince: current?.from ?? null,
        municipality: p.municipality,
        track: p.track,
        variety: p.variety,
        status: p.status,
        latest: withStaleness(latest.sensors[p.id] ?? null, manifest.stale_after_s, nowS),
        hasData: p.id in manifest.sensors,
      };
    });
    return new SensorCatalog(sensors);
  }

  /** Number of sensors. */
  get size(): number {
    return this.sensors.length;
  }

  get(sensorId: string): SensorInfo | undefined {
    return this.byId.get(sensorId);
  }

  /** Keep only ids of known sensors, preserving order. */
  knownIds(sensorIds: readonly string[]): readonly string[] {
    return sensorIds.filter((id) => this.byId.has(id));
  }
}
