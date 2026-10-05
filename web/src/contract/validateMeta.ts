import { FieldReader } from './FieldReader';
import {
  OFF_SITE_EVENT_TYPE,
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
} from './types';

const MONTH_KEY_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

function readLabel(reader: FieldReader, value: unknown, path: string): LocalizedLabel {
  return reader.record(value, path, reader.stringItem);
}

function readManifestSensor(reader: FieldReader, value: unknown, path: string): ManifestSensor {
  const sensor = reader.object(value, path);
  return {
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
 * @throws ContractError if the file does not match `schema_version: 1`.
 */
export function parseManifest(value: unknown, file = 'manifest.json'): Manifest {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  reader.literal(root.schema_version, [SUPPORTED_SCHEMA_VERSION], '$.schema_version');
  return {
    schema_version: SUPPORTED_SCHEMA_VERSION,
    generated_at: reader.string(root.generated_at, '$.generated_at'),
    display_timezone: reader.string(root.display_timezone, '$.display_timezone'),
    variables: reader.list(root.variables, '$.variables', (item, path) => {
      const variable = reader.object(item, path);
      return {
        id: reader.string(variable.id, `${path}.id`),
        unit: reader.string(variable.unit, `${path}.unit`),
        label: readLabel(reader, variable.label, `${path}.label`),
      };
    }),
    sensors: reader.record(root.sensors, '$.sensors', (item, path) =>
      readManifestSensor(reader, item, path),
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

function readEvent(reader: FieldReader, value: unknown, path: string): SensorEvent {
  const event = reader.object(value, path);
  const type = reader.literal(event.type, SENSOR_EVENT_TYPES, `${path}.type`);
  const t = reader.integer(event.t, `${path}.t`);
  const common = {
    t,
    source: reader.string(event.source, `${path}.source`),
    confidence: reader.nullableNumber(event.confidence ?? null, `${path}.confidence`),
    detail: reader.nullableString(event.detail ?? null, `${path}.detail`),
  };
  if (type !== OFF_SITE_EVENT_TYPE) {
    if ('t_end' in event) {
      reader.fail(`${path}.t_end`, `is only allowed for "${OFF_SITE_EVENT_TYPE}" events, not "${type}"`);
    }
    return { type, ...common };
  }
  if (!('t_end' in event)) {
    reader.fail(`${path}.t_end`, `is required for "${OFF_SITE_EVENT_TYPE}" (a number, or null while still off site)`);
  }
  const tEnd = event.t_end === null ? null : reader.integer(event.t_end, `${path}.t_end`);
  if (tEnd !== null && tEnd <= t) {
    reader.fail(`${path}.t_end`, `must be greater than t (${t}), got ${tEnd}`);
  }
  return { type, ...common, t_end: tEnd };
}

/** Validate `events/<sensor_id>.json`. @throws ContractError on mismatch. */
export function parseEventsFile(value: unknown, file: string): EventsFile {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  return {
    sensor_id: reader.string(root.sensor_id, '$.sensor_id'),
    events: reader.list(root.events, '$.events', (item, path) => readEvent(reader, item, path)),
  };
}

function readIndexValue(reader: FieldReader, value: unknown, path: string): IndexValue {
  const result = reader.object(value, path);
  return {
    value: reader.nullableNumber(result.value, `${path}.value`),
    unit: reader.string(result.unit, `${path}.unit`),
    coverage: reader.number(result.coverage, `${path}.coverage`),
    complete: reader.boolean(result.complete, `${path}.complete`),
    class: reader.nullableString(result.class ?? null, `${path}.class`),
  };
}

/** Validate `indices/<season>.json`. @throws ContractError on mismatch. */
export function parseIndicesFile(value: unknown, file: string): IndicesFile {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  return {
    season: reader.integer(root.season, '$.season'),
    computed_at: reader.string(root.computed_at, '$.computed_at'),
    sensors: reader.record(root.sensors, '$.sensors', (sensor, sensorPath) =>
      reader.record(sensor, sensorPath, (item, path) => readIndexValue(reader, item, path)),
    ),
  };
}
