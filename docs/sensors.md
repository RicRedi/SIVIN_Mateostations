# Sensor registry

`sensors/sensors.geojson` is the single source of truth for the sensors (MIGRATION_PLAN §2.4).
It replaces the sensor lists that were duplicated in the legacy YAML files and in
`sensor_location.gpx`. Its structure is described by `sensors/sensors.schema.json`, which is
generated from the Python models in `sivin.registry` and must not be edited by hand.

## File format

The file is a GeoJSON `FeatureCollection` with one `Point` feature per sensor:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [16.673002, 48.880215] },
      "properties": {
        "id": "77678271",
        "portal_name": "8615620 77678271",
        "label": "77678271 (VUT)",
        "site": null,
        "variety": null,
        "status": "active",
        "placements": [
          { "from": "2025-12-01T00:00:00Z", "to": null,
            "lon": 16.673002, "lat": 48.880215, "elevation_m": 183.939606,
            "note": "imported from sensor_location.gpx; placeholder deployment date — owner to confirm (MIGRATION_PLAN Q3)" }
        ],
        "notes": null
      }
    }
  ]
}
```

(The writer puts every array element on its own line; the example is compacted for reading.)

### `geometry`

| Key | Type | Unit | Meaning |
|---|---|---|---|
| `type` | `"Point"` | — | GeoJSON geometry type. |
| `coordinates` | `[lon, lat]` | degrees (WGS 84) | Position of the **last** placement. It is derived data: it must equal `lon`/`lat` of the last entry of `placements`, otherwise loading fails. |

### `properties` (one sensor)

| Key | Type | Required | Meaning |
|---|---|---|---|
| `id` | string, 8 digits | yes | Canonical id: the device serial number, e.g. `"77678271"`. Only the canonical form is accepted here. |
| `portal_name` | string | yes | Device name in the provider's portal, e.g. `"8615620 77678271"`. Never `null` (the web portal relies on it). It must contain the sensor's own serial. |
| `label` | string | yes | Human-readable name, e.g. the GPX waypoint name `"77678271 (VUT)"`. |
| `site` | string or `null` | yes | Vineyard or site name (owner question Q4). |
| `variety` | string or `null` | yes | Grape variety at the sensor (owner question Q4). |
| `status` | `"active"`, `"inactive"`, `"retired"` | yes | Life-cycle state, see below. |
| `placements` | array of placements, ≥ 1 | yes | Placement history in time order. |
| `notes` | string or `null` | yes | Free text. |

**Every key is required**, including the nullable ones: write `null`, do not leave the key
out. Strings must not be empty (use `null` instead where `null` is allowed).

### Placement

| Key | Type | Unit | Meaning |
|---|---|---|---|
| `from` | ISO 8601 in UTC with `Z`, e.g. `2025-12-01T00:00:00Z` | UTC instant | **Deployment instant.** The ground truth for the deployment detector (WP-1.5). Other offsets (`+01:00`, `+00:00`) and times without seconds are rejected; up to 6 fractional digits are allowed. |
| `to` | as `from`, or `null` | UTC instant | End of the placement, exclusive. `null` while the sensor still stands there. The key must be present. |
| `lon` | number | degrees east (WGS 84) | Longitude, −180 … 180. |
| `lat` | number | degrees north (WGS 84) | Latitude, −90 … 90. |
| `elevation_m` | number or `null` | metres above sea level | Elevation, if known. |
| `note` | string or `null` | — | Where the placement data came from, why the sensor moved, … |

A placement covers the half-open interval `[from, to)`: at the instant `to` of one placement
the sensor already belongs to the next one.

### Status

| Status | Meaning | Rule |
|---|---|---|
| `active` | Deployed and measuring. | The last placement must be open (`to: null`). |
| `inactive` | Temporarily out, e.g. in service. | The last placement may be open or closed. |
| `retired` | Permanently out of use. | No placement may be open. |

## Validation rules

Loading the file (`GeoJsonRegistryStore.load`) checks, and reports the key path of every
problem (e.g. `features.0.properties.placements.1.lat`):

1. Structure and types as in `sensors.schema.json`; unknown keys are rejected (typo safety).
2. Every key of a sensor and of a placement is present; `portal_name` is a non-empty string.
3. `from` and `to` are ISO 8601 UTC texts with `Z` (pattern
   `^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$`); `from < to`.
4. Coordinates are within the WGS 84 ranges and, by default, inside the Czech Republic
   (bounding box 48.55–51.06° N, 12.09–18.86° E, rounded outward from the country's extreme
   points; *to be verified*). This catches swapped latitude and longitude. The box is the
   `allowed_area` registry setting and can be disabled with `null`.
5. Placements are sorted by `from`, do not overlap (`to` of one ≤ `from` of the next; gaps are
   allowed), and only the last placement may be open.
6. `status` agrees with the last placement (table above).
7. `portal_name` contains the sensor's own serial.
8. Sensor ids are unique. Portal names are therefore unique as well.
9. `geometry` equals the last placement.

The JSON Schema covers rules 1–3 fully (structure, types, required keys, timestamp
`pattern` in addition to `format: date-time`, which Draft 2020-12 treats as an annotation
only) and rule 4 for the global WGS 84 ranges. Rules that relate several values (4 for the
allowed area, 5–9) are enforced by the Python loader. Everything the schema and the loader
accept is also accepted by the web portal's parser (`web/src/contract/validateSensors.ts`,
WP-3.1), which is more lenient (it tolerates missing optional keys). The web admin mode
(WP-3.3) validates against the schema before it commits and the pipeline re-checks on load.

## Sensor names that are recognised

`SensorRegistry.get(name)` accepts any of:

| Spelling | Example |
|---|---|
| canonical serial | `77678271` |
| portal device name | `8615620 77678271` |
| GPX waypoint name | `77678271 (VUT)` |
| export file name or path | `MeteoData_8615620 77678271  (VUT)_20260301_223857.csv` |
| legacy 4-digit short name | `8271` — **only if exactly one sensor of the registry ends with these digits**; otherwise the lookup fails with `AmbiguousSensorNameError` and the full serial must be used. Like every other spelling it may be the last component of a path (`exports/8271`). |

## Changing the registry

Until the web admin mode (WP-3.3) exists, edit `sensors/sensors.geojson` in a text editor and
check it with:

```bash
.venv/bin/python -c "from pathlib import Path; from sivin.registry.geojson import GeoJsonRegistryStore as S; s = S(); p = Path('sensors/sensors.geojson'); s.save(s.load(p), p)"
git diff sensors/sensors.geojson
```

The command fails with a message if a rule is broken, and otherwise rewrites the file in its
canonical form (the diff then shows only formatting normalisation, if any). In Python, the
same changes are `SensorRegistry.with_sensor`, `.with_moved` and `.without`, followed by
`GeoJsonRegistryStore.save`.

### Add a sensor

Append a feature with a new `id`, its `portal_name`, a `label`, `site`/`variety`/`notes`
(`null` if unknown), `status: "active"` and one placement with `to: null` whose `from` is the
instant the sensor was put up in the vineyard (UTC, `Z`). Set `geometry.coordinates` to
`[lon, lat]` of that placement.

### Move a sensor

Never edit the coordinates of an existing placement (that would move the old data too).
Instead:

1. set `to` of the current placement to the instant the sensor was taken down,
2. append a new placement with `from` = the instant it was put up at the new place (equal to
   or later than the previous `to`) and `to: null`,
3. set `geometry.coordinates` to the new `[lon, lat]`.

`SensorRegistry.with_moved(id, placement)` does steps 1–3 with `to` = the new `from`. If the
sensor was `inactive` and the new placement is open, it becomes `active` automatically (it is
back in the field); an active sensor stays active, and an inactive one moved to a closed
placement stays inactive. A `retired` sensor cannot be moved (`ValueError`); change its status
first if it really returns to use.

### Take a sensor out for service

Set `to` of the current placement and `status: "inactive"`. When it comes back, add a new
placement as in *Move a sensor* (same coordinates if it returns to the same spot) and set
`status: "active"` (`with_moved` does that for you).

### Retire a sensor

Set `to` of the last placement and `status: "retired"`. Keep the feature: its placement
history is needed to interpret the data it recorded. Delete a feature only if it was added by
mistake.

## How the initial file was created

`sensors/sensors.geojson` was generated from `sensor_location.gpx` (four waypoints, coordinates
and elevations as exported from mapy.com) with:

```bash
.venv/bin/python -c "
from datetime import UTC, datetime
from pathlib import Path
from sivin.registry.geojson import GeoJsonRegistryStore
from sivin.registry.gpx import GpxImporter
from sivin.registry.registry import SensorRegistry
sensors = GpxImporter(portal_prefix='8615620').read(
    Path('sensor_location.gpx'), datetime(2025, 12, 1, tzinfo=UTC),
    note_suffix='placeholder deployment date — owner to confirm (MIGRATION_PLAN Q3)')
GeoJsonRegistryStore().save(SensorRegistry(sensors), Path('sensors/sensors.geojson'))
"
```

The deployment instant `2025-12-01T00:00:00Z` is a **placeholder** until the owner supplies the
real dates (MIGRATION_PLAN Q3); `site` and `variety` are `null` until Q4 is answered.

The JSON Schema is regenerated with:

```bash
.venv/bin/python -c "from pathlib import Path; from sivin.registry.schema import render_json_schema; Path('sensors/sensors.schema.json').write_text(render_json_schema(), encoding='utf-8')"
```

A test fails whenever the committed schema differs from the generated one.
