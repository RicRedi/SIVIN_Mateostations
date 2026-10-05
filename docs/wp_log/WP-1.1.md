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

**Round 2** addressed the review (round 1). Every §2.4 key is now required in the file, in the
models and in the schema. `portal_name` is always a non-empty string, and `GpxImporter`
requires `portal_prefix`. File timestamps must be ISO 8601 UTC with `Z`, enforced by a schema
`pattern` and by the loader. Legacy-suffix lookup normalises paths the way `SensorId.parse`
does. Moving an `inactive` sensor to an open placement makes it `active`, and moving a
`retired` sensor is refused. The per-finding details are in the *Status* column of the review
table.

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
UTC_TIMESTAMP_PATTERN: str                      # file form of from/to (schema "pattern")
UtcTimestamp                                    # Annotated[AwareDatetime, ...] with that pattern
# All fields of Placement and Sensor are required (nullable ones take None), as in the file.
class Placement(BaseModel):                     # frozen, extra="forbid"; file keys from/to/lon/lat
    from_utc: datetime; to_utc: datetime | None; lon_deg: float; lat_deg: float
    elevation_m: float | None; note: str | None
    is_open; contains(instant) -> bool          # [from, to)
    closed_at(end_utc) -> Placement
class Sensor(BaseModel):                        # frozen, extra="forbid"
    id: SensorId; portal_name: str; label: str; site: str | None; variety: str | None
    status: SensorStatus; placements: tuple[Placement, ...]; notes: str | None
    is_active; current_placement -> Placement | None; last_placement -> Placement
    deployed_since -> datetime; placement_at(instant) -> Placement | None
    moved_to(placement) -> Sensor   # inactive + open placement -> active; retired -> ValueError
    replaced(**changes) -> Sensor

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
    def __init__(self, portal_prefix: str)
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

Round 2:

- `make lint` → `All checks passed!`, `46 files already formatted`.
- `make type` → `Success: no issues found in 27 source files`.
- `make test` → `326 passed` (145 of them in `tests/registry`).
- `make cov` → every `src/sivin/registry/*.py` at 100 % (statements and branches);
  `TOTAL 1238 0 250 0 100%`.
- `sensors/sensors.schema.json` was regenerated. `sensors/sensors.geojson` is unchanged, and the
  generation command gives the same bytes.
- Independent schema check: `jsonschema` (Draft 2020-12) was installed in a throwaway venv in
  the session scratchpad, not in the repo. The schema itself is valid, and the committed file
  has 0 errors. The schema rejects `portal_name: null`, a missing `portal_name`, `site`, `to`
  or `note`, `from: "+01:00"` and `from: "yesterday"`. It accepts `"…00.5Z"`.
- WP-3.1's `validateSensors.ts` was read, not run. Every value the schema or the loader accepts
  is also accepted by it: required strings stay strings, nullable fields are `null` or a
  string/number, and coordinates are exactly two numbers. The web parser is more lenient, since
  it tolerates missing `site`/`variety`/`notes`/`elevation_m`/`note`.

Round 1:

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
- `jsonschema` is not a project dependency, so no repository test validates the file against
  the schema with an external validator. That check was run by hand in round 2 (see above).
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
8. **Canonical form.** Since round 2, file timestamps must already be UTC with `Z`; Python
   code may pass any aware datetime, which is stored as UTC. Integers in coordinates are
   written as floats (`16` → `16.0`), and every array element goes on its own line, so `coordinates` is not inline as in the §2.4 example. The byte-identical
   round trip holds for files in canonical form, which is what `save` writes. Elevations keep
   the full GPX precision (`183.939606`); the §2.4 example shows `183.9`.
9. **All keys are required** (round 2, replaces "`to` may be omitted"). Python construction
   must pass every field as well, so the models and the file cannot drift apart.
10. **No re-exports** in `sivin/registry/__init__.py`, the same as `sivin.core`. Import from the
    submodules.
11. **Moving an inactive sensor** (round 2): `moved_to` sets `active` when the new placement is
    open. A move to a closed placement keeps `inactive`, and a `retired` sensor cannot be moved
    (`ValueError`).

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
  Is the automatic `inactive → active` on a move to an open placement (decision 11) acceptable?

## Review

Verdict: CHANGES_REQUESTED (round 1)

Reviewer: independent review agent. Everything below was run or read by the reviewer in
`/home/user/wt/wp-1.1` at `7d46f3b`. Throwaway scripts live in `/tmp/claude-0/review-1.1/`.

### Gates observed

- `make lint`: `All checks passed!`, `46 files already formatted`.
- `make type`: `Success: no issues found in 27 source files`.
- `make test`: `299 passed`.
- `make cov`: every `src/sivin/registry/*.py` at 100 % (statements and branches), `TOTAL 1224 0 248 0 100%`.
- Scope: `git diff bcde7d9...HEAD --name-only` touches only `sensors/**`, `src/sivin/registry/**`,
  `tests/registry/**`, `docs/sensors.md` and `docs/wp_log/WP-1.1.md`. No shared file was changed.

### Independent checks

- **Byte-identical round trip.** load → save of the committed `sensors.geojson` gives the same bytes.
  A registry after `with_moved` also round-trips (save → load → save gives the same bytes). A `from`
  written as `+01:00` is normalised back to the committed bytes.
- **JSON Schema vs committed file.** `jsonschema` 4.x (Draft 2020-12, in a throwaway venv outside
  the repo) reports a valid schema and 0 errors on the committed file. It rejects an extra property,
  `id: "8271"`, an unknown status, empty `placements`, `lat: 95` and three coordinates. It **accepts**
  `portal_name: null`, a missing `portal_name` and a missing `to` (see M1). It also accepts
  `from: "yesterday"` (see m2).
- **§2.4 format.** Key order and nesting match §2.4 exactly: Feature → `type, geometry, properties`;
  properties → `id, portal_name, label, site, variety, status, placements, notes`; placement →
  `from, to, lon, lat, elevation_m, note`. `coordinates` is `[lon, lat]`. The differences from the
  §2.4 example are layout only (multi-line arrays) and the full GPX precision of the elevation
  (`183.939606` instead of `183.9`). Both are acceptable.
- **WP-3.1 TypeScript contract** (`/home/user/wt/wp-3.1/web/src/contract/types.ts`,
  `validateSensors.ts`, checked by reading the code). The committed file satisfies it.
  The mismatches are listed in M1.
- **Placement history.** A move closes the open placement at the new `from`, and `placement_at` is
  half-open (`12:00:00Z` belongs to the new placement, `11:59:59Z` to the old one). An instant
  given in `+01:00` resolves correctly. The geometry follows the last placement. The following are
  all rejected with `ValidationError`: a move that starts before the current `from`; a move of an
  `active` sensor to an already-closed placement; a move of a `retired` sensor; and a move of an
  `inactive` sensor to a time before its closing `to`. A retired sensor has
  `current_placement is None`, `placement_at(after retirement) is None`, and it is excluded from
  `active()`.
- **Name resolution.** With `11118271` and `22228271` both registered: `"8271"` and `" 8271 "`
  raise `AmbiguousSensorNameError`, which names both candidates. The serial, the portal name, the
  export file name and a Windows path all resolve. `"1111"` and `"99999999"` raise
  `SensorLookupError`. After `without(11118271)`, `"8271"` resolves to `22228271`.
- **Czech Republic bounding box.** Rounding outward from the extreme points (S ≈ 48°33′ Vyšší Brod
  area, N ≈ 51°03′ Lobendava, W ≈ 12°05′ Krásná, E ≈ 18°51′ Bukovec) gives
  48.55 / 51.06 / 12.09 / 18.86. This matches the reviewer's knowledge, but the reviewer did not
  check it against a source, so `[to be verified]` is the correct label. The eastern margin is
  only about 0.0006° (about 45 m), which does not matter for a plausibility check in South Moravia.

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | src/sivin/registry/model.py:126-130, 247-253; sensors/sensors.schema.json (`required`); docs/sensors.md:52,104 | The registry contract is looser than the §2.4 example and the WP-3.1 consumer. `portal_name` may be `null` or missing, and a placement's `to` may be omitted. The web's `parseSensorsGeoJSON` throws on both. | fixed (round 2, orchestrator's option (a)): all §2.4 keys are required in the models, the loader and the schema (`required` lists every property; tests assert this). `portal_name: str`, `min_length=1`. `GpxImporter(portal_prefix)` is required. Nullable: site, variety, notes, note, elevation_m, to. Tests in `test_model.py`, `test_geojson.py::TestInvalidFiles`, `test_schema.py`; checked by hand with jsonschema. |
| minor | sensors/sensors.schema.json (`from`/`to`) | `format: "date-time"` is only an annotation in Draft 2020-12, so a schema-only validator (WP-3.3) accepts `"from": "yesterday"` or a naive time. | fixed: `UtcTimestamp` adds `pattern` `UTC_TIMESTAMP_PATTERN` (ISO 8601 UTC with `Z`) next to `format`, and the loader enforces the same pattern on text input. Tests: `test_file_timestamps_must_be_utc_with_z`, `test_offset_other_than_z_rejected`, `test_schema_uses_file_keys`. |
| minor | src/sivin/registry/registry.py:144-148 | The legacy-suffix check runs on `key.strip()`, but `SensorId.parse` uses the base name of the path. `get("x/8271")` therefore fails with the message "looks like a legacy 4-digit short sensor name … resolve it through the sensor registry", even though it was the registry that was asked. | fixed: `get` takes the base name the same way `SensorId.parse` does (`PureWindowsPath(...).name`) before the legacy-suffix check, so `exports/8271` and `C:\exports\8271` resolve and `x/8271` gives the ambiguity error. A public helper in `sivin.core.ids` is still proposed (Out of scope). |
| nit | src/sivin/registry/model.py:362-386 | `moved_to`/`with_moved` keeps the status. Moving an `inactive` sensor whose placement is closed gives an `inactive` sensor with an open placement. Docs (lines 153-155) tell the user to set `active` by hand, which is easy to forget in the WP-3.3 flow. | fixed: an inactive sensor moved to an open placement becomes active, and a move to a closed placement stays inactive. Moving a retired sensor raises `ValueError` with a clear message. Documented in `docs/sensors.md` and in the docstring. Tests in `TestMovedTo`. |

**M1 (major): mismatch between the registry contract and the web contract.**

- *Input:* `GpxImporter()` without `portal_prefix` (allowed by the brief) followed by `save`. Or a
  hand-edited placement without the `to` key: the Python loader accepts it (default `null`), the
  schema accepts it, and `docs/sensors.md:52` marks `portal_name` as "string or null, not required".
- *Wrong behaviour:* `site/data/sensors.geojson` is a copy of the registry (§2.6). WP-3.1 types
  `SensorProperties.portal_name` as `string` and reads it with `reader.string(p.portal_name)`, so
  `null` or a missing value throws `ContractError`. It reads `to` with
  `reader.nullableString(placement.to)`, so a missing key (`undefined`) throws too. Either case
  makes the portal's whole sensor layer fail to load. `docs/sensors.md:104` says WP-3.3 validates
  against this schema before it commits, so the schema would approve files that the web rejects.
- *Suggested fix* (needs one owner/orchestrator decision, the worker followed the brief):
  1. Make every key of §2.4 required in the file. Remove the defaults of `to_utc`, `elevation_m`,
     `note`, `site`, `variety` and `notes` on the file models, or emit the schema with
     `json_schema_serialization_defaults_required=True` and enforce presence on load. The schema's
     `required` list then matches what `save` writes, and a test should assert this.
  2. For `portal_name`, choose one: (a) non-null string in the registry. The importer then requires
     `portal_prefix`, or the registry refuses `null` on save. (b) Nullable in §2.4, and WP-3.1's
     `SensorProperties.portal_name` becomes `string | null`. Option (a) matches §2.4 and the
     already-built web without touching WP-3.1.

**m2:** add a `pattern` (for example
`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$`) to `from`/`to` through
`WithJsonSchema`/`json_schema_extra`, or state in `docs/sensors.md` that WP-3.3 must enable format
assertion (e.g. ajv-formats).

**m3:** apply the same base-name normalisation before the legacy-suffix check (ideally through a
public helper in `sivin.core.ids`, as the worker already proposes), or reword the message.

### Deviations assessment

1. Combined note: acceptable.
2. Geometry = last placement and `current_placement` = open placement: correct per §2.4 ("poslední placement").
3. Status rule (active ⇒ last placement open, retired ⇒ last placement closed, inactive either way):
   sound and consistent with the placement semantics and the docs. The reviewer recommends that the
   owner accept it. See the nit on `moved_to`.
4. No separate portal-name uniqueness check: the reasoning is correct. Equal portal names parse to
   equal ids, which the registry already rejects.
5. Configurable Czech Republic area check: good. It meets the plan's "souřadnice v rozsahu ČR".
6. Extra modules: each has one responsibility. Acceptable.
7. `with_sensor` adds or replaces: acceptable and documented.
8. Canonical form: acceptable. The output is JSON-equivalent to §2.4, and the round trip holds
   for canonical files.
9. `to` may be omitted on input: **not acceptable as is** (see M1). The key should be required.
10. No re-exports: consistent with `sivin.core`.

### Round 2

Verdict: APPROVE (round 2)

Reviewer: independent review agent. The reviewer checked fix commit `615600b`, re-ran the gates
in `/home/user/wt/wp-1.1`, and used throwaway scripts in `/tmp/claude-0/review-1.1/`.

**Gates observed:**

- `make lint`: `All checks passed!`, `46 files already formatted`.
- `make type`: `Success: no issues found in 27 source files`.
- `make test`: `326 passed`.
- `make cov`: every `src/sivin/registry/*.py` at 100 % (statements and branches), `TOTAL 1238 0 250 0 100%`.
- Scope: unchanged, only WP-1.1 files.

**Verification:**

- **M1.** The `required` lists of `Placement` and `Sensor` in the regenerated schema now hold every
  §2.4 key.
  - `jsonschema` (Draft 2020-12, throwaway venv) reports 0 errors on the committed file. It
    rejects `portal_name: null`, and a missing `portal_name`, `site`, `notes`, `to`,
    `elevation_m` or `note`. The Python loader rejects all of these as well.
  - The re-read WP-3.1 parser (`validateSensors.ts`, `types.ts`) has not changed for sensors: it
    still requires `portal_name: string` and the key `to`. The reviewer ran it under Node 22 with
    `--experimental-transform-types` on a copy outside both repos. It accepts the committed file
    and a registry saved after `with_moved`. It rejects the `portal_name: null` and missing-`to`
    variants, which Python and the schema now reject too.
  - Every file that Python and the schema accept is therefore also accepted by the web. The web
    is more lenient only for the optional nullable keys.
  - `GpxImporter()` without a prefix raises `TypeError`. Regenerating from `sensor_location.gpx`
    with the documented command reproduces the committed file byte for byte.
- **m2.** The schema and the loader reject `from: "yesterday"`, a naive time, `+01:00` and a
  lowercase `z`. They accept `...00.5Z`.
- **m3.** `x/8271` and `C:\exports\8271` now raise `AmbiguousSensorNameError` when two serials
  end in 8271. `exports/0065` resolves to its unique sensor, and full names and paths still
  resolve.
- **Nit.** `moved_to` behaves as follows:
  - an inactive sensor with a closed placement, moved to an open placement, becomes `active`;
  - an inactive sensor moved to a closed placement stays `inactive`;
  - an inactive sensor with an open placement, moved to an open one, closes the old placement
    and becomes `active`;
  - a retired sensor raises `ValueError`, from the model and from `with_moved`;
  - an active sensor moved to a closed placement is still rejected.
- **Round trip.** The committed file round-trips byte for byte, and Python callers can still pass
  any aware datetime (stored as UTC).

| Severity | File:line | Finding | Status |
|---|---|---|---|
| major | (M1, round 1) | Registry contract looser than §2.4 and the WP-3.1 parser. | verified fixed |
| minor | (m2, round 1) | Schema timestamps not enforced. | verified fixed |
| minor | (m3, round 1) | Legacy suffix in a path gave a misleading error. | verified fixed |
| nit | (round 1) | `moved_to` kept `inactive`. | verified fixed |
| nit | sensors/sensors.schema.json (`from`/`to` `pattern`) | The pattern checks the shape only: `2025-13-01T00:00:00Z` passes the schema, and the Python loader rejects it. WP-3.3 should also enable format assertion (e.g. ajv-formats) or rely on the pipeline re-check. | open (for WP-3.3) |
| nit | docs/wp_log/WP-1.1.md (decision 8) | One over-long, un-rewrapped line after the round-2 edit. | open |

**Deviations assessment, round 2:**

- Decision 9 (all keys required) resolves the round-1 objection.
- Decision 11 (automatic `inactive → active` on a move to an open placement) is consistent with
  the status rule. The reviewer recommends that the owner accept it.
