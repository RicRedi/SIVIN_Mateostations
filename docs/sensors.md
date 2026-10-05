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
`status: "active"` (`with_moved` does that for you). If the sensor keeps recording while it is
away, also add the period to the [off-site log](#off-site-log): only the log keeps those
samples out of the indices.

### Retire a sensor

Set `to` of the last placement and `status: "retired"`. Keep the feature: its placement
history is needed to interpret the data it recorded. Delete a feature only if it was added by
mistake.

## Off-site log

`sensors/offsite_log.yaml` (MIGRATION_PLAN §2.8) lists the periods when a sensor was **not**
measuring in the vineyard: in the office, at the service, in transport or in storage. By default
every sensor is assumed to measure in the vineyard; the log is the only source of truth for the
exceptions (owner decision of 2026-10-05; automatic detection only warns, see
[quality-control.md](quality-control.md#deployment-detection)). Samples recorded inside a logged
period get the flag `PRE_DEPLOYMENT`, are left out of every climate index, and are shown on the
web as a grey band without a line ([web.md](web.md#off-site-periods)).

The file is edited by hand (directly on GitHub; later in the web admin mode, WP-3.3). Its
structure is described by `sensors/offsite_log.schema.json`, generated from
`sivin.registry.offsite` (do not edit it by hand). The committed file has `entries: []`, a
header comment that explains the format, and a commented-out example.

### Format

```yaml
entries:
  - sensor: "77799986"          # 8-digit serial; any known spelling of the name is accepted
    from: "2025-12-17 12:00"    # start, inclusive
    to:   "2026-03-15 09:00"    # end, exclusive; null = still off site
    reason: office              # office | service | transport | storage | other
    note: "winter storage in the office"   # optional
```

| Key | Required | Meaning |
|---|---|---|
| `sensor` | yes | The sensor, in any spelling of [Sensor names that are recognised](#sensor-names-that-are-recognised) (serial, portal name, GPX name, a unique legacy short name). It must be in `sensors/sensors.geojson`. |
| `from` | yes | Start of the period, **inclusive**. |
| `to` | yes | End of the period, **exclusive**; `null` while the sensor is still off site. The key must be written even then, so an open end is never an accident. |
| `reason` | yes | `office`, `service`, `transport`, `storage` or `other`. |
| `note` | no | Free text. The web shows `"<reason>: <note>"` in the band's tooltip. |

**Times.** Write local wall-clock time of the vineyards, `YYYY-MM-DD HH:MM` (seconds optional,
`T` instead of the space also accepted), in quotes. The zone is Europe/Prague (configurable,
`OffSiteLogSettings.timezone`). Alternatively give an absolute instant in ISO 8601 with an
explicit offset or `Z`: `"2025-12-17T12:00+01:00"`, `"2025-12-17T11:00Z"`. Everything is stored
and compared in UTC. Twice a year a local time is not unique:

* in the night of the **last Sunday of October** the clock goes back from 03:00 to 02:00, so
  `02:00`–`02:59` happen twice; such a local time is rejected as *ambiguous*,
* in the night of the **last Sunday of March** the clock jumps from 02:00 to 03:00, so
  `02:00`–`02:59` do not exist; such a local time is rejected as *nonexistent*.

In both cases write the time with an explicit offset: `+02:00` is summer time (CEST), `+01:00`
winter time (CET). The error message suggests both spellings.

### Examples

A sensor kept in the office over the winter:

```yaml
entries:
  - sensor: "77799986"
    from: "2025-12-17 12:00"
    to: "2026-03-15 09:00"
    reason: office
    note: "winter storage in the office"
```

A service visit (taken down Monday morning, back in the vineyard Wednesday afternoon), plus the
car ride as its own period if you want it separate:

```yaml
  - sensor: "8615620 77678271"
    from: "2026-06-01 07:30"
    to: "2026-06-01 08:15"
    reason: transport
  - sensor: "8615620 77678271"
    from: "2026-06-01 08:15"
    to: "2026-06-03 14:00"
    reason: service
    note: "battery replacement"
```

Periods of one sensor may touch (one ends exactly when the next starts) but not overlap.

A sensor that is still off site (only its last period may be open):

```yaml
  - sensor: "77680921 (VUT)"
    from: "2026-10-01 10:00"
    to: null
    reason: storage
    note: "waiting for a new mast"
```

When it goes back to the vineyard, replace `null` with the time it was put up.

A time in the repeated hour of 25 October 2026:

```yaml
    from: "2026-10-25T02:30+01:00"   # the second 02:30, already winter time
```

### Validation

`OffSiteLogStore.load(path, registry, timezone)` reads the file on every pipeline run (and in
the tests); an invalid log **stops the run** — no update is better than wrongly flagged data.
Every message names the entry by its index (0-based, in file order) and the field:

| Message (shortened) | Cause | Fix |
|---|---|---|
| `entries.2.sensor: Sensor 12345678 (from '12345678') is not in the registry.` | Unknown sensor, typo in the serial. | Correct the name or add the sensor to `sensors.geojson` first. |
| `entries.0.sensor: Legacy short name '9986' is ambiguous …` | A 4-digit short name that fits several sensors. | Use the 8-digit serial. |
| `entries.1.from: … local time '2026-10-25 02:30' is ambiguous (clocks fall back …) …; give an explicit offset, e.g. '2026-10-25T02:30+02:00' or '2026-10-25T02:30+01:00'` | Local time in the repeated hour. | Write it with the offset you mean. |
| `entries.1.to: … local time '2026-03-29 02:30' does not exist (clocks spring forward …) …` | Local time in the skipped hour. | Use 03:00 or an explicit offset. |
| `entries.3.from: … time '17.12.2025 12:00' must be local 'YYYY-MM-DD HH:MM' or ISO 8601 with an offset …` | Wrong format. | Use `YYYY-MM-DD HH:MM`. |
| `entries.3.from: … '2025-12-17' has no time of day …` | Unquoted date without time. | Add the time and quotes. |
| `entries.4: … 'from' (2026-05-01T06:00:00Z) must be before 'to' (…), both in UTC` | `from` equals or follows `to`. | Swap or correct the times. |
| `entries.5.reason: Input should be 'office', 'service', 'transport', 'storage' or 'other'` | Unknown reason. | Pick one of the five (use `other` and a note otherwise). |
| `entries.6.to: Field required` | `to` missing. | Write `to: null` for a sensor that is still off site. |
| `entries[3].from: period of sensor 77799986 starting … overlaps entries[1] (… - …, UTC)` | Two periods of one sensor overlap. | Merge them or correct the times. |
| `entries[0].to: sensor 77799986 has an open period (to: null) that is not its last one …` | An open period followed by a later one. | Close the open period. |
| `the file must be a mapping with a list 'entries' …` | Empty file or missing `entries:`. | Keep `entries: []` when there are no periods. |

Pydantic messages carry a `Value error,` prefix; the rule checks across entries use the
`entries[i]` form. Check the file locally with:

```bash
.venv/bin/python -c "from pathlib import Path; from sivin.registry.geojson import GeoJsonRegistryStore; from sivin.registry.offsite import OffSiteLogStore; r = GeoJsonRegistryStore().load(Path('sensors/sensors.geojson')); print(OffSiteLogStore().load(Path('sensors/offsite_log.yaml'), r))"
```

The JSON Schema checks the structure of every entry (keys, reason, time pattern). The checks
that need the registry or several entries (known sensor, overlaps, open period last) and the
daylight-saving checks are done by the Python loader only.

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
