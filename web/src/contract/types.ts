/**
 * TypeScript mirror of the static site data contract, MIGRATION_PLAN.md §2.6 (`schema_version: 1`)
 * and of the sensor registry properties, §2.4.
 *
 * Times are Unix seconds UTC, missing values are `null`, series are columnar.
 */

/** The only contract version this frontend understands. */
export const SUPPORTED_SCHEMA_VERSION = 1;

/** Language code → label, e.g. `{ cs: "Teplota", de: "Temperatur", en: "Temperature" }`. */
export type LocalizedLabel = Readonly<Record<string, string>>;

/** A measured variable listed in the manifest (`temp_c`, `rh_pct`, ...). */
export interface VariableSpec {
  readonly id: string;
  readonly unit: string;
  readonly label: LocalizedLabel;
}

/** Per-sensor availability in the manifest. `raw_months` are `YYYY-MM` keys (UTC months). */
export interface ManifestSensor {
  readonly first_t: number;
  readonly last_t: number;
  readonly raw_months: readonly string[];
}

/** A climate index advertised by the manifest. */
export interface IndexSpec {
  readonly id: string;
  readonly unit: string;
  readonly doc: string;
  readonly label: LocalizedLabel;
}

/** `manifest.json`. */
export interface Manifest {
  readonly schema_version: typeof SUPPORTED_SCHEMA_VERSION;
  readonly generated_at: string;
  readonly display_timezone: string;
  readonly variables: readonly VariableSpec[];
  readonly sensors: Readonly<Record<string, ManifestSensor>>;
  readonly seasons: readonly number[];
  readonly indices: readonly IndexSpec[];
}

/** One sensor's most recent sample in `latest.json`. */
export interface LatestSample {
  readonly t: number;
  readonly temp_c: number | null;
  readonly rh_pct: number | null;
  readonly qc: number;
  readonly stale: boolean;
}

/** `latest.json`. */
export interface LatestFile {
  readonly generated_at: string;
  readonly sensors: Readonly<Record<string, LatestSample>>;
}

/**
 * `series/<sensor_id>/raw/<YYYY-MM>.json`: all columns have the length of `t`.
 *
 * `precip_mm` (precipitation since the previous sample, mm) and `battery_v` (battery voltage, V)
 * are optional (WP-1.9): files written before them, or for devices without them, omit the
 * fields. They are read when present and not displayed yet (WP-3.4).
 */
export interface RawMonthFile {
  readonly sensor_id: string;
  readonly t: readonly number[];
  readonly temp_c: readonly (number | null)[];
  readonly rh_pct: readonly (number | null)[];
  readonly precip_mm?: readonly (number | null)[];
  readonly battery_v?: readonly (number | null)[];
  readonly qc: readonly number[];
}

/**
 * `series/<sensor_id>/daily.json`; `date` is the local calendar day in the display time zone.
 *
 * `precip_sum_mm` (daily precipitation sum, mm) and `battery_min_v` (daily minimum battery
 * voltage, V) are optional (WP-1.9); `null` where a day has no such value.
 */
export interface DailyFile {
  readonly sensor_id: string;
  readonly date: readonly string[];
  readonly temp_min: readonly (number | null)[];
  readonly temp_mean: readonly (number | null)[];
  readonly temp_max: readonly (number | null)[];
  readonly rh_min: readonly (number | null)[];
  readonly rh_mean: readonly (number | null)[];
  readonly rh_max: readonly (number | null)[];
  readonly precip_sum_mm?: readonly (number | null)[];
  readonly battery_min_v?: readonly (number | null)[];
  readonly coverage: readonly number[];
}

/** Numeric daily columns of {@link DailyFile}. */
export const DAILY_VALUE_COLUMNS = [
  'temp_min',
  'temp_mean',
  'temp_max',
  'rh_min',
  'rh_mean',
  'rh_max',
] as const;
export type DailyValueColumn = (typeof DAILY_VALUE_COLUMNS)[number];

/** Event types produced by the deployment detector (§2.7). */
export const SENSOR_EVENT_TYPES = ['deployment', 'retrieval', 'step'] as const;
export type SensorEventType = (typeof SENSOR_EVENT_TYPES)[number];

/** One entry of `events/<sensor_id>.json`. */
export interface SensorEvent {
  readonly type: SensorEventType;
  readonly t: number;
  readonly source: string;
  readonly confidence: number | null;
  readonly detail: string | null;
}

/** `events/<sensor_id>.json`. */
export interface EventsFile {
  readonly sensor_id: string;
  readonly events: readonly SensorEvent[];
}

/** One index result in `indices/<season>.json`. */
export interface IndexValue {
  readonly value: number | null;
  readonly unit: string;
  readonly coverage: number;
  readonly complete: boolean;
  readonly class: string | null;
}

/** `indices/<season>.json`: sensor id → index id → result. */
export interface IndicesFile {
  readonly season: number;
  readonly computed_at: string;
  readonly sensors: Readonly<Record<string, Readonly<Record<string, IndexValue>>>>;
}

/** One entry of a sensor's placement history (§2.4). `from` is the deployment instant. */
export interface Placement {
  readonly from: string;
  readonly to: string | null;
  readonly lon: number;
  readonly lat: number;
  readonly elevation_m: number | null;
  readonly note: string | null;
}

/** Registry properties of one sensor (§2.4). */
export interface SensorProperties {
  readonly id: string;
  readonly portal_name: string;
  readonly label: string;
  readonly site: string | null;
  readonly variety: string | null;
  readonly status: string;
  readonly placements: readonly Placement[];
  readonly notes: string | null;
}

/** A GeoJSON point feature of the registry; coordinates are `[lon, lat]` (WGS 84). */
export interface SensorFeature {
  readonly type: 'Feature';
  readonly geometry: { readonly type: 'Point'; readonly coordinates: readonly [number, number] };
  readonly properties: SensorProperties;
}

/** `sensors.geojson`, a copy of the registry. */
export interface SensorsGeoJSON {
  readonly type: 'FeatureCollection';
  readonly features: readonly SensorFeature[];
}
