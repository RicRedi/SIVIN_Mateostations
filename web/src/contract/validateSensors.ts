import { FieldReader } from './FieldReader';
import type { Placement, SensorFeature, SensorsGeoJSON } from './types';

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

function readFeature(reader: FieldReader, value: unknown, path: string): SensorFeature {
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
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [lon, lat] },
    properties: {
      id: reader.string(p.id, `${propertiesPath}.id`),
      portal_name: reader.string(p.portal_name, `${propertiesPath}.portal_name`),
      label: reader.string(p.label, `${propertiesPath}.label`),
      site: reader.nullableString(p.site ?? null, `${propertiesPath}.site`),
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
 * Validate `sensors.geojson`, the copy of the sensor registry (§2.4).
 *
 * @throws ContractError if the file is not a FeatureCollection of sensor points.
 */
export function parseSensorsGeoJSON(value: unknown, file = 'sensors.geojson'): SensorsGeoJSON {
  const reader = new FieldReader(file);
  const root = reader.object(value, '$');
  reader.literal(root.type, ['FeatureCollection'], '$.type');
  return {
    type: 'FeatureCollection',
    features: reader.list(root.features, '$.features', (item, path) =>
      readFeature(reader, item, path),
    ),
  };
}
