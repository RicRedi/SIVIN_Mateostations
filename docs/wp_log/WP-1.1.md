# WP-1.1 — Sensor registry

## Summary

The package `sivin.registry` makes `sensors/sensors.geojson` the single source of truth for
sensors (MIGRATION_PLAN §2.4). `Placement` and `Sensor` are frozen pydantic models. They
validate the placement history (sorted, non-overlapping, only the last one open), the status
and the portal name. `SensorRegistry` is an immutable collection: it rejects duplicate ids,
optionally checks an allowed area, and resolves every name variant through `SensorId.parse`
and the legacy 4-digit suffix (only when that suffix is unique). It returns new registries
from `with_sensor`, `without` and `with_moved`. `GeoJsonRegistryStore` reads and writes the
FeatureCollection in a canonical text form, so a load/save round trip gives the same bytes.
`GpxImporter` reads GPX waypoints with `xml.etree.ElementTree`. `sensors.schema.json` is
generated from the models, and a test keeps it in sync. The committed
`sensors/sensors.geojson` holds the four sensors of `sensor_location.gpx`. Their deployment
date is a placeholder.

## Changed files

- Package: `src/sivin/registry/{model,registry,geojson,gpx,schema,settings,errors}.py`
  (`__init__.py` unchanged).
- Data: `sensors/sensors.geojson`, `sensors/sensors.schema.json`.
- Tests: `tests/registry/{conftest,test_model,test_registry,test_geojson,test_gpx,test_schema,test_settings}.py`.
- Docs: `docs/sensors.md`, `docs/wp_log/WP-1.1.md`.

## Public API

```python
# sivin.registry.model
SensorStatus = Literal["active", "inactive", "retired"]
SensorIdField                                   # Annotated[SensorId, ...] -> "77678271" in JSON
def format_utc(instant: datetime) -> str        # "2025-12-01T00:00:00Z"
class Placement(BaseModel):                     # frozen, extra="forbid"; file keys from/to/lon/lat
    from_utc: datetime; to_utc: datetime | None; lon_deg: float; lat_deg: float
    elevation_m: float | None; note: str | None
    is_open; contains(instant) -> bool          # [from, to)
    closed_at(end_utc) -> Placement
class Sensor(BaseModel):                        # frozen, extra="forbid"
    id: SensorId; portal_name: str | None; label: str; site: str | None; variety: str | None
    status: SensorStatus; placements: tuple[Placement, ...]; notes: str | None
    is_active; current_placement -> Placement | None; last_placement -> Placement
    deployed_since -> datetime; placement_at(instant) -> Placement | None
    moved_to(placement) -> Sensor; replaced(**changes) -> Sensor

# sivin.registry.registry
class SensorRegistry:
    def __init__(self, sensors: Iterable[Sensor] = (), *, area: GeoBounds | None = None)
    get(key: SensorId | str) -> Sensor          # SensorLookupError / AmbiguousSensorNameError
    __iter__, __len__, __contains__, __eq__, ids(), active() -> tuple[Sensor, ...], area
    with_sensor(sensor), without(sensor_id), with_moved(sensor_id, placement) -> SensorRegistry

# sivin.registry.geojson
class GeoJsonRegistryStore:
    def __init__(self, settings: RegistrySettings | None = None)
    load(path) -> SensorRegistry; save(registry, path) -> None; dumps(registry) -> str
SensorCollection, SensorFeature, PointGeometry  # file document models (schema source)
def render_json(document) -> str                # canonical JSON text

# sivin.registry.gpx
class GpxImporter:
    def __init__(self, portal_prefix: str | None = None)
    read(path, deployed_from, *, note_suffix=None) -> tuple[Sensor, ...]
    waypoints(path) -> tuple[GpxWaypoint, ...]

# sivin.registry.schema
build_json_schema() -> dict[str, Any]; render_json_schema() -> str

# sivin.registry.settings
class GeoBounds(BaseModel): min_lat_deg, max_lat_deg, min_lon_deg, max_lon_deg; contains(lat, lon)
CZECH_REPUBLIC: GeoBounds
class RegistrySettings(BaseModel): allowed_area: GeoBounds | None = CZECH_REPUBLIC

# sivin.registry.errors
RegistryError(ValueError), RegistryFormatError(ValueError), GpxFormatError(ValueError),
SensorLookupError(LookupError), AmbiguousSensorNameError(SensorLookupError)
```

## How it was verified

All commands were run in `/home/user/wt/wp-1.1` with a venv created by
`uv venv --python 3.12 .venv && uv pip install -e ".[dev,ingest,viz]"` (pydantic 2.13.5,
ruff 0.16.10, mypy 2.4.0).

- `make lint` → `All checks passed!`, `46 files already formatted`.
- `make type` → `Success: no issues found in 27 source files`.
- `make test` → `299 passed` (118 of them in `tests/registry`).
- `make cov` → every `src/sivin/registry/*.py` at 100 % (statements and branches);
  `TOTAL 1224 0 248 0 100%`.
- Acceptance criteria, each covered by tests:
  - the committed registry holds the 4 GPX sensors with coordinates and elevations (the
    expected values were copied by hand from `sensor_location.gpx`):
    `test_geojson.py::TestCommittedRegistry`;
  - load/save round trip is byte-identical for the committed file and for a hand-written
    synthetic file: `TestRoundTrip`;
  - duplicate ids, overlapping placements and an open placement that is not last are rejected,
    both in the models and when loading a file: `test_model.py`, `TestInvalidFiles`;
  - `get` resolves the serial, `SensorId`, portal name, GPX name, export file name and path, and
    a unique legacy suffix. It refuses `8271` when `11118271` and `22228271` are both
    registered: `TestGet`;
  - `placement_at` across a move made with `with_moved`, and across a service gap:
    `test_with_moved_and_placement_at_across_the_move`, `TestPlacementHistory`;
  - the committed schema equals the generated schema: `test_schema.py`.
- The generation commands in `docs/sensors.md` (GPX → GeoJSON, schema, check/normalise) were
  re-run on the committed files. `git status` showed no change afterwards.

## What did not work / what was not verified

- **The deployment dates are placeholders.** Every placement starts at
  `2025-12-01T00:00:00Z`, with a note asking the owner to confirm the date (Q3). `site` and
  `variety` are `null` (Q4).
- **The Czech Republic bounding box** (48.55–51.06° N, 12.09–18.86° E) comes from memory. It is
  the country's extreme points rounded outward, with no checked source, so it is marked
  *[to be verified]*. It is only a plausibility check, and the setting can be changed or
  disabled.
- **The JSON Schema was not checked with an independent validator.** `jsonschema` is not a
  dependency, so the committed GeoJSON was not validated against the schema with an external
  tool. Only pydantic was used. WP-3.3 will use the schema in the browser.
- The schema text depends on the pydantic version. A pydantic upgrade can change it, and then
  `test_committed_schema_is_in_sync` fails. That failure is intended: regenerate the schema
  with the command in `docs/sensors.md`.
- `xml.etree.ElementTree` is not hardened against malicious XML. GPX files come from the owner,
  not from untrusted users.

## Decisions and deviations from the brief

1. **Placement note of the initial file.** The brief asks for both the importer's note
   `"imported from <file>"` and the note `"placeholder deployment date — owner to confirm
   (MIGRATION_PLAN Q3)"`. `GpxImporter.read` takes `note_suffix`, so the committed note is
   `"imported from sensor_location.gpx; placeholder deployment date — owner to confirm
   (MIGRATION_PLAN Q3)"`.
2. **`current_placement` vs geometry.** `current_placement` is the open placement, or `None`.
   A retired sensor has no open placement but still needs a point, so the geometry uses
   `last_placement` (plan §2.4: "poslední placement").
3. **Status rule (added).** `active` requires the last placement to be open, and `retired`
   requires it to be closed. `inactive` allows both. This keeps the map and the deployment
   detector consistent. The brief did not define this rule.
4. **Portal-name uniqueness.** A `Sensor` requires its `portal_name` to contain its own serial
   (`SensorId.parse(portal_name) == id`). Two sensors with the same portal name would therefore
   have the same id, which the registry already rejects. A separate portal-name check would be
   unreachable code, so there is none; the docstring explains why.
5. **Area check.** Plan WP-1.1 asks for "souřadnice v rozsahu ČR"; the brief only asks for
   lat/lon ranges. `Placement` checks the WGS 84 ranges. `SensorRegistry(area=...)` checks a
   configurable bounding box, defaulting to the Czech Republic through
   `RegistrySettings.allowed_area`, which the store applies on load.
6. **Extra modules.** Besides `model.py`, `registry.py` and `gpx.py` (plan §2.2) the package has
   `geojson.py` (store and file document models), `schema.py`, `settings.py` and `errors.py`.
   Each one has a single responsibility.
7. **`with_sensor` adds or replaces.** If the sensor's id is already registered, it replaces
   that sensor in place and keeps the file order. Otherwise it appends. The WP-3.3 edit flow
   needs the replace case.
8. **Canonical form.** Any time-zone offset is accepted on input and written as UTC `Z`.
   Integers in coordinates are written as floats (`16` → `16.0`), and every array element goes
   on its own line, so `coordinates` is not inline as in the §2.4 example. The byte-identical
   round trip holds for files in canonical form, which is what `save` writes. Elevations keep
   the full GPX precision (`183.939606`); the §2.4 example shows `183.9`.
9. **`to` may be omitted** in a placement on input (it defaults to `null`) but is always written.
10. **No re-exports** in `sivin/registry/__init__.py`, the same as `sivin.core`. Import from the
    submodules.

## Proposed integration (WP-1.7 / WP-3.2)

- Config: a section `registry: RegistrySettings` in `SivinConfig`, e.g.
  `registry: {allowed_area: {min_lat_deg: 48.55, max_lat_deg: 51.06, min_lon_deg: 12.09,
  max_lon_deg: 18.86}}`. The file location is already `paths.sensors_file`.
- The portal device prefix `8615620` belongs in the portal/ingest configuration (WP-1.3/1.7),
  not in the registry.
- CLI: `sivin sensors check` (load, then report or rewrite in canonical form),
  `sivin sensors list`, `sivin sensors import-gpx FILE --portal-prefix 8615620 --from ISO`,
  `sivin sensors schema` (regenerate `sensors.schema.json`).

## Out of scope

- `src/sivin/core/ids.py`: `_LEGACY_SUFFIX_PATTERN` is private, so `registry.py` builds its own
  pattern from the public `LEGACY_SUFFIX_DIGITS`. Proposal: make the pattern public, or add
  `SensorId.is_legacy_suffix(text)`.
- `.gitignore`: `save` writes a temporary `.<name>.tmp` next to the target and renames it. If
  the process is killed between the two steps, the temporary file is left behind. Consider
  ignoring `sensors/.*.tmp`.

## Open questions for the owner

- Q3 (existing): real deployment instants, and any moves or service trips, for the four
  sensors, so the placeholder `from` values can be replaced.
- Q4 (existing): site and grape variety per sensor.
- Is the status rule in decision 3 acceptable (active ⇒ open placement, retired ⇒ none open)?

## Review

Verdict: _pending_

| Severity | File:line | Finding | Status |
|---|---|---|---|
