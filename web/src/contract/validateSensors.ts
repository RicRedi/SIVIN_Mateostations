import { FieldReader } from './FieldReader';
import type { Placement, SensorFeature, SensorsGeoJSON } from './types';
import type { ContractWarning } from './validateMeta';

/**
 * Registry key of the site name before 2026-10-05, replaced by `municipality` and `track`. A file
 * that still has it is read with a warning; the value is ignored (the Python loader maps it to
 * `track`, the web does not guess).
 */
const DEPRECATED_SITE_KEY = 'site';

const warnOnConsole: ContractWarning = (message) => {
  console.warn(message);
};

function readPlacement(reader: FieldReader, value: unknown, path: string): Placement {
  const placement = reader.object(value, path);
  return {
    from: reader.string(placement.from, `${path}.from`),
    to: reader.nullableString(placement.to, `${path}.to`),
    lon: reader.number(placement.lon, `${path}.lon`),
    lat: reader.number(placement.lat, `${path}.lat`),
    elevation_m: reader.nullableNumber(placement.elevation_m ?? null, `${path}.elevation_m`),
    note: reader.nullableString(placement.note ?? null, `${path}.note`),
  };
}

function readFeature(reader: FieldReader, value: unknown, path: string, warn: ContractWarning, file: string): SensorFeature {
  const feature = reader.object(value, path);
  reader.literal(feature.type, ['Feature'], `${path}.type`);
  const geometry = reader.object(feature.geometry, `${path}.geometry`);
  reader.literal(geometry.type, ['Point'], `${path}.geometry.type`);
  const coordinates = reader.list(
    geometry.coordinates,
    `${path}.geometry.coordinates`,
    reader.numberItem,
  );
  const [lon, lat] = coordinates;
  if (lon === undefined || lat === undefined) {
    reader.fail(`${path}.geometry.coordinates`, 'must be [lon, lat]');
  }
  const p = reader.object(feature.properties, `${path}.properties`);
  const propertiesPath = `${path}.properties`;
  if (DEPRECATED_SITE_KEY in p) {
    warn(
      `${file}: ${propertiesPath}.${DEPRECATED_SITE_KEY} is deprecated (replaced by municipality and track); ignored`,
    );
  }
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [lon, lat] },
    properties: {
      id: reader.string(p.id, `${propertiesPath}.id`),
      portal_name: reader.string(p.portal_name, `${propertiesPath}.portal_name`),
      label: reader.string(p.label, `${propertiesPath}.label`),
      municipality: reader.nullableString(p.municipality ?? null, `${propertiesPath}.municipality`),
      track: reader.nullableString(p.track ?? null, `${propertiesPath}.track`),
      variety: reader.nullableString(p.variety ?? null, `${propertiesPath}.variety`),
      status: reader.string(p.status, `${propertiesPath}.status`),
      placements: reader.list(p.placements, `${propertiesPath}.placements`, (item, itemPath) =>
        readPlacement(reader, item, itemPath),
      ),
      notes: reader.nullableString(p.notes ?? null, `${propertiesPath}.notes`),
    },
  };
}

/**
 * Validate `sensors.geojson`, the public projection of the sensor registry (§2.4). Missing
 * nullable keys (`municipality`, `track`, `variety`, `notes`, …) are read as `null`; an old
 * `site` key is ignored with a warning.
 *
 * @param warn - Receives warnings about ignored deprecated keys; default `console.warn`.
 * @throws ContractError if the file is not a FeatureCollection of sensor points.
 */
export function parseSensorsGeoJSON(
  value: unknown,
  file = 'sensors.geojson',
  warn: ContractWarning = warnOnConsole,
): SensorsGeoJSON {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  reader.literal(root.type, ['FeatureCollection'], '$.type');
  return {
    type: 'FeatureCollection',
    features: reader.list(root.features, '$.features', (item, path) =>
      readFeature(reader, item, path, warn, file),
    ),
  };
}
