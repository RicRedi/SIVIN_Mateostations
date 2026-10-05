import { FieldReader } from './FieldReader';
import { ContractError } from './ContractError';
import {
  MARKED_INTERVAL_EVENT_TYPES,
  OFF_SITE_EVENT_TYPE,
  POINT_EVENT_TYPES,
  SENSOR_EVENT_TYPES,
  SUPPORTED_SCHEMA_VERSION,
  type EventsFile,
  type IndexValue,
  type IndicesFile,
  type LatestFile,
  type LocalizedLabel,
  type Manifest,
  type ManifestSensor,
  type SensorEvent,
  type SensorEventType,
} from './types';

const MONTH_KEY_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

/** Receives non-fatal contract findings (tolerantly ignored fields). */
export type ContractWarning = (message: string) => void;

const warnOnConsole: ContractWarning = (message) => {
  console.warn(message);
};

/**
 * An optional field read by `read`: absent (`undefined`) gives `undefined`; a malformed value is
 * reported to `warn` and also gives `undefined` (tolerant reading of optional fields, plan §0.5).
 */
function optionalField<T>(value: unknown, read: (value: unknown) => T, warn: ContractWarning): T | undefined {
  if (value === undefined) {
    return undefined;
  }
  try {
    return read(value);
  } catch (error) {
    if (!(error instanceof ContractError)) {
      throw error;
    }
    warn(`${error.message}; optional field ignored`);
    return undefined;
  }
}

function readLabel(reader: FieldReader, value: unknown, path: string): LocalizedLabel {
  return reader.record(value, path, reader.stringItem);
}

function readManifestSensor(reader: FieldReader, value: unknown, path: string, warn: ContractWarning): ManifestSensor {
  const sensor = reader.object(value, path);
  const optionalText = (name: string): Record<string, string> => {
    const text = optionalField(sensor[name], (item) => reader.string(item, `${path}.${name}`), warn);
    return text === undefined ? {} : { [name]: text };
  };
  return {
    ...optionalText('status'),
    ...optionalText('data_status'),
    ...optionalText('last_built_at'),
    first_t: reader.integer(sensor.first_t, `${path}.first_t`),
    last_t: reader.integer(sensor.last_t, `${path}.last_t`),
    raw_months: reader.list(sensor.raw_months, `${path}.raw_months`, (item, itemPath) => {
      const key = reader.string(item, itemPath);
      if (!MONTH_KEY_PATTERN.test(key)) {
        reader.fail(itemPath, `must be a month YYYY-MM, got "${key}"`);
      }
      return key;
    }),
  };
}

/**
 * Validate `manifest.json`, the entry point of the contract.
 *
 * @param warn - Receives warnings about ignored malformed optional fields; default `console.warn`.
 * @throws ContractError if the file does not match `schema_version: 1`.
 */
export function parseManifest(value: unknown, file = 'manifest.json', warn: ContractWarning = warnOnConsole): Manifest {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  reader.literal(root.schema_version, [SUPPORTED_SCHEMA_VERSION], '$.schema_version');
  const staleAfterS = optionalField(root.stale_after_s, (item) => reader.number(item, '$.stale_after_s'), warn);
  return {
    schema_version: SUPPORTED_SCHEMA_VERSION,
    generated_at: reader.string(root.generated_at, '$.generated_at'),
    display_timezone: reader.string(root.display_timezone, '$.display_timezone'),
    ...(staleAfterS === undefined ? {} : { stale_after_s: staleAfterS }),
    variables: reader.list(root.variables, '$.variables', (item, path) => {
      const variable = reader.object(item, path);
      return {
        id: reader.string(variable.id, `${path}.id`),
        unit: reader.string(variable.unit, `${path}.unit`),
        label: readLabel(reader, variable.label, `${path}.label`),
      };
    }),
    sensors: reader.record(root.sensors, '$.sensors', (item, path) =>
      readManifestSensor(reader, item, path, warn),
    ),
    seasons: reader.list(root.seasons, '$.seasons', reader.integerItem),
    indices: reader.list(root.indices, '$.indices', (item, path) => {
      const index = reader.object(item, path);
      return {
        id: reader.string(index.id, `${path}.id`),
        unit: reader.string(index.unit, `${path}.unit`),
        doc: reader.string(index.doc, `${path}.doc`),
        label: readLabel(reader, index.label, `${path}.label`),
      };
    }),
  };
}

/** Validate `latest.json`. @throws ContractError on mismatch. */
export function parseLatestFile(value: unknown, file = 'latest.json'): LatestFile {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  return {
    generated_at: reader.string(root.generated_at, '$.generated_at'),
    sensors: reader.record(root.sensors, '$.sensors', (item, path) => {
      const sample = reader.object(item, path);
      return {
        t: reader.integer(sample.t, `${path}.t`),
        temp_c: reader.nullableNumber(sample.temp_c, `${path}.temp_c`),
        rh_pct: reader.nullableNumber(sample.rh_pct, `${path}.rh_pct`),
        qc: reader.integer(sample.qc, `${path}.qc`),
        stale: reader.boolean(sample.stale, `${path}.stale`),
      };
    }),
  };
}

const KNOWN_EVENT_TYPES: readonly string[] = SENSOR_EVENT_TYPES;
const POINT_TYPES: readonly string[] = POINT_EVENT_TYPES;
const MARKED_INTERVAL_TYPES: readonly string[] = MARKED_INTERVAL_EVENT_TYPES;

/** One event; `null` (with a warning) for an event type this frontend does not know. */
function readEvent(reader: FieldReader, value: unknown, path: string, warn: ContractWarning, file: string): SensorEvent | null {
  const event = reader.object(value, path);
  const typeName = reader.string(event.type, `${path}.type`);
  if (!KNOWN_EVENT_TYPES.includes(typeName)) {
    warn(`${file}: ${path} skipped: unknown event type "${typeName}"`);
    return null;
  }
  const type = typeName as SensorEventType;
  const t = reader.integer(event.t, `${path}.t`);
  const common = {
    t,
    source: reader.string(event.source, `${path}.source`),
    confidence: reader.nullableNumber(event.confidence ?? null, `${path}.confidence`),
    detail: reader.nullableString(event.detail ?? null, `${path}.detail`),
  };
  if (POINT_TYPES.includes(type)) {
    if ('t_end' in event) {
      warn(`${file}: ${path}.t_end ignored: only interval events have an end, not "${type}"`);
    }
    return { type: type as (typeof POINT_EVENT_TYPES)[number], ...common };
  }
  if (MARKED_INTERVAL_TYPES.includes(type)) {
    const tEnd = reader.integer(event.t_end, `${path}.t_end`);
    if (tEnd < t) {
      reader.fail(`${path}.t_end`, `must not be before t (${t}), got ${tEnd}`);
    }
    return { type: type as (typeof MARKED_INTERVAL_EVENT_TYPES)[number], ...common, t_end: tEnd };
  }
  if (!('t_end' in event)) {
    reader.fail(`${path}.t_end`, `is required for "${OFF_SITE_EVENT_TYPE}" (a number, or null while still off site)`);
  }
  const tEnd = event.t_end === null ? null : reader.integer(event.t_end, `${path}.t_end`);
  if (tEnd !== null && tEnd <= t) {
    reader.fail(`${path}.t_end`, `must be greater than t (${t}), got ${tEnd}`);
  }
  return { type: OFF_SITE_EVENT_TYPE, ...common, t_end: tEnd };
}

/**
 * Validate `events/<sensor_id>.json`. An event of an unknown type is skipped and a `t_end` on a
 * point event is ignored, both with a warning (tolerant reading, plan §0.5 and WP-3.2), so a
 * pipeline that publishes a new event kind never breaks the chart. `off_site` and the marked
 * intervals (`low_battery`, `unlogged_off_site`) require `t_end`.
 *
 * @param warn - Receives the warnings; default `console.warn`.
 * @throws ContractError on mismatch.
 */
export function parseEventsFile(value: unknown, file: string, warn: ContractWarning = warnOnConsole): EventsFile {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  return {
    sensor_id: reader.string(root.sensor_id, '$.sensor_id'),
    events: reader
      .list(root.events, '$.events', (item, path) => readEvent(reader, item, path, warn, file))
      .filter((event): event is SensorEvent => event !== null),
  };
}

function readIndexValue(reader: FieldReader, value: unknown, path: string, warn: ContractWarning): IndexValue {
  const result = reader.object(value, path);
  const estimated = optionalField(result.estimated, (item) => reader.boolean(item, `${path}.estimated`), warn);
  const status = optionalField(result.status, (item) => reader.string(item, `${path}.status`), warn);
  const detail = optionalField(result.detail, (item) => reader.string(item, `${path}.detail`), warn);
  return {
    ...(estimated === undefined ? {} : { estimated }),
    ...(status === undefined ? {} : { status }),
    ...(detail === undefined ? {} : { detail }),
    value: reader.nullableNumber(result.value, `${path}.value`),
    unit: reader.string(result.unit, `${path}.unit`),
    coverage: reader.number(result.coverage, `${path}.coverage`),
    complete: reader.boolean(result.complete, `${path}.complete`),
    class: reader.nullableString(result.class ?? null, `${path}.class`),
  };
}

/**
 * Validate `indices/<season>.json`.
 *
 * @param warn - Receives warnings about ignored malformed optional fields; default `console.warn`.
 * @throws ContractError on mismatch.
 */
export function parseIndicesFile(value: unknown, file: string, warn: ContractWarning = warnOnConsole): IndicesFile {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  return {
    season: reader.integer(root.season, '$.season'),
    computed_at: reader.string(root.computed_at, '$.computed_at'),
    sensors: reader.record(root.sensors, '$.sensors', (sensor, sensorPath) =>
      reader.record(sensor, sensorPath, (item, path) => readIndexValue(reader, item, path, warn)),
    ),
  };
}
