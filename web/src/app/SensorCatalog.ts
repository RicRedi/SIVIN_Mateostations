import type { LatestFile, LatestSample, Manifest, SensorsGeoJSON } from '../contract';

/** Everything the UI shows about one sensor, joined from registry, manifest and latest values. */
export interface SensorInfo {
  readonly id: string;
  readonly label: string;
  readonly lat: number;
  readonly lon: number;
  readonly elevation_m: number | null;
  /** `from` of the current placement (ISO 8601), i.e. when the sensor was deployed there. */
  readonly placedSince: string | null;
  readonly site: string | null;
  readonly variety: string | null;
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

  /** Join the registry copy with manifest availability and `latest.json`. */
  static build(registry: SensorsGeoJSON, manifest: Manifest, latest: LatestFile): SensorCatalog {
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
        site: p.site,
        variety: p.variety,
        latest: latest.sensors[p.id] ?? null,
        hasData: p.id in manifest.sensors,
      };
    });
    return new SensorCatalog(sensors);
  }

  get(sensorId: string): SensorInfo | undefined {
    return this.byId.get(sensorId);
  }

  /** Keep only ids of known sensors, preserving order. */
  knownIds(sensorIds: readonly string[]): readonly string[] {
    return sensorIds.filter((id) => this.byId.has(id));
  }
}
