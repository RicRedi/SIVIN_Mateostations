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

Set `to` of the last placement and `status: "retired"`. **Do not delete the feature** and do
not delete its data: its placement history is needed to interpret the data it recorded, its
off-site log entries must still name a registered sensor (otherwise the log is invalid and QC
stops), and its stored data and derived entries (events, indices of past seasons) stay
published. A retired sensor is still quality-controlled from its stored data; only the
download stops. Derived entries are pruned only for a sensor that is in neither the registry
nor the store ([storage.md](storage.md#derived-data-wp-17)). Delete a feature only if it was
added by mistake.

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
`sivin.registry.offsite` (do not edit it by hand). The committed file has a header comment that
explains the format, the first real entry (sensor 77799986, owner decision Q10: off site for the
whole real export, 30 Jul 2025 – 1 Mar 2026) and a commented-out example under the same
`entries:` key. The example uses dates in the year 2000, so even uncommented as is it excludes
nothing.

### Format

All periods are list items (`- sensor: ...`) under **one** `entries:` key:

```yaml
entries:
  - sensor: "77799986"          # 8-digit serial; any known spelling of the name is accepted
    from: "2025-12-17 12:00"    # start, inclusive
    to:   "2026-03-15 09:00"    # end, exclusive; open = still off site
    reason: office              # office | service | transport | storage | other
    note: "winter storage in the office"   # optional
```

| Key | Required | Meaning |
|---|---|---|
| `sensor` | yes | The sensor, in any spelling of [Sensor names that are recognised](#sensor-names-that-are-recognised) (serial, portal name, GPX name, a unique legacy short name). It must be in `sensors/sensors.geojson`. Write it in quotes; an unquoted serial is accepted as written. |
| `from` | yes | Start of the period, **inclusive**. |
| `to` | yes | End of the period, **exclusive**. Write **`to: open`** while the sensor is still off site (`to: null` means the same). A `to:` with nothing after it is an **error**, so a half-filled entry never silently excludes everything from `from` on. |
| `reason` | yes | `office`, `service`, `transport`, `storage` or `other` (lower case). |
| `note` | no | Free text in quotes. The web shows `"<reason>: <note>"` in the band's tooltip. |

The file is read strictly: **a key written twice is an error** (YAML itself would silently keep
the last one). That covers a second `entries:` line, e.g. from pasting a whole example file, and
two `from:` lines in one entry.

**Times.** Write local wall-clock time of the vineyards, `YYYY-MM-DD HH:MM` (seconds optional,
`T` instead of the space also accepted), in quotes. The zone is Europe/Prague (configurable,
`OffSiteLogSettings.timezone`). Alternatively give an absolute instant in ISO 8601 with an
explicit offset or `Z`: `"2025-12-17T12:00+01:00"`, `"2025-12-17T11:00Z"`. Everything is stored
and compared in UTC; messages show local time with UTC in brackets. Twice a year a local time is
not unique:

* in the night of the **last Sunday of October** the clock goes back from 03:00 to 02:00, so
  `02:00`–`02:59` happen twice; such a local time is rejected as *ambiguous*. Write it with the
  offset you mean: `+02:00` for the first pass (summer time, CEST), `+01:00` for the second
  (winter time, CET); the message suggests both;
* in the night of the **last Sunday of March** the clock jumps from 02:00 to 03:00, so
  `02:00`–`02:59` do not exist; such a local time is rejected as *nonexistent*. Use a time from
  03:00 on, or the time the clock showed before the change with the winter offset `+01:00`
  (the message suggests exactly that one).

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
car ride as its own period if you want it separate (further items under the same `entries:`):

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
    to: open
    reason: storage
    note: "waiting for a new mast"
```

When it goes back to the vineyard, replace `open` with the time it was put up.

A time in the repeated hour of 25 October 2026:

```yaml
    from: "2026-10-25T02:30+01:00"   # the second 02:30, already winter time
```

The advisory deployment detector suggests periods it suspects are missing in this form: its
warning names the period in local time and gives `from:` / `to:` values with offset, ready to
paste ([quality-control.md](quality-control.md#deployment-detection)).

### Validation

`OffSiteLogStore.load(path, registry, timezone)` reads the file on every pipeline run (and in
the tests); an invalid log **stops the run** — no update is better than wrongly flagged data.
Every message names the entry as **`entry #N`** — the N-th `- sensor:` item, counted from 1 —
with the line number of the entry or of the field, and says how to fix it. All problems are
reported at once. Examples (shortened):

| Message | Cause |
|---|---|
| `line 31: the key 'entries' appears a second time (first on line 25); keep only one - YAML would silently use the last (put all entries as '- sensor: ...' items under one 'entries:')` | A second `entries:` (or any key twice in one entry). |
| `entry #2, 'sensor' (line 31): the off-site log names sensor '12345678', which is not in the sensor registry sensors/sensors.geojson (known sensors: 77678271, …); check the serial, or add the sensor to the registry. A sensor that left service stays in the registry with status 'retired' instead of being deleted` | Unknown sensor: a typo in the serial, or a sensor deleted from the registry (restore it with `status: "retired"`). |
| `entry #1, 'sensor' (line 2): Legacy short name '9986' is ambiguous … Use the full 8-digit serial.` | A 4-digit short name that fits several sensors. |
| `entry #2, 'to' (line 33): is empty - write a date/time, or 'open' if the sensor is still off site` | `to:` with nothing after it. |
| `entry #2 (line 31): the key 'to' is missing - add a line like to: "2026-03-05 16:00"   (or  to: open  if the sensor is still off site)` | A required key is missing (each key has its own example). |
| `entry #2, 'form' (line 32): unknown key 'form' - allowed keys are sensor, from, to, reason, note (check the spelling)` | Misspelt key. |
| `entry #2, 'from' (line 32): local time '2026-10-25 02:30' is ambiguous in Europe/Prague …; give an explicit offset: '2026-10-25T02:30+02:00' for the first one (summer time) or '2026-10-25T02:30+01:00' for the second one (winter time)` | Local time in the repeated hour. |
| `entry #2, 'to' (line 33): local time '2026-03-29 02:30' does not exist in Europe/Prague …; write a time after the change, or the time on the clock before the change with its offset: '2026-03-29T02:30+01:00'` | Local time in the skipped hour. |
| `entry #2, 'from' (line 32): time '17.12.2025 12:00' must be local 'YYYY-MM-DD HH:MM' or ISO 8601 with an offset, e.g. …` | Wrong format (also `'2025-12-17' has no time of day` for a bare date). |
| `entry #2 (line 31): 'from' (2026-05-01 08:00 CEST (06:00 UTC)) must be before 'to' (…); swap or correct the times` | `from` equals or follows `to`. |
| `entry #2, 'reason' (line 34): Input should be 'office', 'service', 'transport', 'storage' or 'other' (lower case, exactly one of these)` | Unknown reason. |
| `entry #3 (line 37), 'from': the period of sensor 77799986 starting 2026-01-05 00:00 CET (2026-01-04 23:00 UTC) overlaps entry #2 (line 31) (…); periods of one sensor must not overlap - correct the times or merge the two entries` | Two periods of one sensor overlap. |
| `entry #1 (line 25), 'to': sensor 77799986 has an open period ('to: open') that is not its last one (entry #2 (line 31) starts …); write the end time into entry #1 (line 25) or remove the later entry` | An open period followed by a later one. |
| `unknown top-level key(s) 'entires' (line 1); the file must contain one key 'entries:' …` / `the file must contain one key 'entries:' with a list of entries …; write 'entries: []' when there are no periods` | File structure (misspelt or missing `entries:`, empty file). |
| `not valid YAML (indent with spaces, not tabs; put times and notes in quotes): …` | YAML syntax. |

Check the file locally with:

```bash
.venv/bin/python -c "from pathlib import Path; from sivin.registry.geojson import GeoJsonRegistryStore; from sivin.registry.offsite import OffSiteLogStore; r = GeoJsonRegistryStore().load(Path('sensors/sensors.geojson')); print(OffSiteLogStore().load(Path('sensors/offsite_log.yaml'), r))"
```

The JSON Schema checks the structure of every entry (keys, reason, time pattern or `open`).
Duplicate keys, blank values, the checks that need the registry or several entries (known
sensor, overlaps, open period last) and the daylight-saving checks are done by the Python
loader only.

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
