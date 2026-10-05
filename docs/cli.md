# Command line: `sivin`

One command runs the whole pipeline locally and in GitHub Actions (WP-4.1): download from the
portal → parse and validate → store → quality control with the off-site log → climate indices.
The site export (`sivin build-site`) is WP-3.2.

```
sivin [--config FILE] [--log-level LEVEL] COMMAND [OPTIONS]
```

The commands are thin (`src/sivin/cli/`): they parse options, call an application service
(`src/sivin/app/`, see [architecture.md](architecture.md#application-services-and-cli-wp-17))
and print its report. Logging is set up only here and goes to standard error; summaries go to
standard output, failures to standard error.

## Global options

| Option | Default | Meaning |
|---|---|---|
| `--config FILE` | `config/sivin.yaml` of the project | Configuration file ([configuration.md](configuration.md)). Without the file, the defaults apply. |
| `--log-level LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` (case-insensitive). |
| `--version` | | Print the version and exit. |
| `--help` | | Help of `sivin` or of any command. |

The project root is the nearest directory upwards from the working directory that contains
`pyproject.toml`; all configured paths are relative to it. When `--config` points into a
project, that project is used even from outside it.

**Secrets.** Every command first reads `<project root>/.env` (template `.env.example`) with
python-dotenv. Variables that are already set in the environment are **never** overridden, so
GitHub Actions secrets and exported shell variables win over the file. The portal credentials
are `SIVIN_USER` and `SIVIN_PASSWORD`; they are never printed or logged.

## Exit codes

| Code | Name (`sivin.app.outcome.Outcome`) | When |
|---|---|---|
| 0 | `OK` | Everything succeeded. |
| 1 | `PARTIAL_FAILURE` | The command ran but something failed: a file was rejected, a device was not downloaded, a sensor or an index failed, the portal login failed during `sivin run`; `sivin sensors check` found invalid files. |
| 2 | `USAGE_ERROR` | Invalid usage: unknown option, invalid `--sensor` name, unknown `--index`, invalid `--from`/`--to`, invalid `--log-level`. |
| 3 | `SETUP_ERROR` | Nothing could be done: not inside a project, invalid configuration, invalid sensor registry or off-site log (MIGRATION_PLAN §2.8: an invalid log stops the run), missing credentials or failed login in `sivin fetch`. |

`sivin run` exits with the most severe code of its steps; a failed portal step is code 1
because the run continues with the stored data.

## `sivin config show`

Prints the **resolved** configuration as YAML: the file merged with the defaults, the
`time` values copied into the subsystems, and the complete settings of every enabled quality
check and every index ([configuration.md](configuration.md#resolution)). Outside a project and
without `--config` it prints the defaults. Exit code 3 for an invalid file; the message names
every offending key path.

```console
$ sivin config show
$ sivin --config /tmp/try.yaml config show
```

## `sivin config schema [--markdown]`

Prints the JSON schema of `config/sivin.yaml`, including the settings models of all registered
quality checks, alignment strategies and indices. With `--markdown` it prints the key
reference tables that are part of [configuration.md](configuration.md#reference).

## `sivin sensors check`

Validates the sensor registry (`paths.sensors_file`, checks in `registry`) and then the
off-site log (`offsite_log.file`), which must name registry sensors. Prints the number of
sensors and periods; on a problem it prints the file and every problem (entry number, line,
field, how to fix it) to standard error and exits with **1**.

```console
$ sivin sensors check
Sensor registry: 4 sensor(s), 4 active.
Off-site log: 1 period(s).
```

## `sivin fetch [--sensor ID ...] [--headed] [--download-dir DIR]`

Logs in to the portal and downloads one export per device into `ingest.portal.download_dir`
(`data/downloads`), with the settings of `ingest.portal` (see [ingest.md](ingest.md)).

| Option | Meaning |
|---|---|
| `--sensor`, `-s ID` | Only this sensor (any spelling: `77678271`, `8615620 77678271`, `77678271 (VUT)`); repeat for several. Default: every device the portal lists. A requested sensor the portal does not list is a failure. |
| `--headed` | Show the browser window (default headless). |
| `--download-dir DIR` | Save the exports here instead. |

Prints `DOWNLOADED <path>` per file and `FAILED fetch <device>: <reason>` per failed device.
Exit code 1 if a device failed, 3 if the credentials are missing, the browser cannot start, the
login fails or the device list cannot be read. Late files of timed-out attempts stay in the
download directory (see [ingest.md](ingest.md)).

## `sivin ingest [FILE ...] [--from-dir DIR] [--dry-run]`

Parses and validates each export file (`ingest.parsers`, `ingest.validation`, see
[data-format.md](data-format.md)), then:

- **rejected** (a validation error, an unknown format, or a sensor that is not in the
  registry, rule `sensor-registered`): copied (`ingest.quarantine_mode: copy`, default) or
  moved (`move`) to `paths.quarantine_dir` (`data/quarantine/`), with
  `<file name>.report.json` next to it (file, every finding with rule, severity, message, row,
  table). Nothing of the file reaches the store; the next file is processed.
- **accepted**: every series is appended to the store (`data/raw/<id>/<YYYY>.csv`); the store
  keeps the short export identifier as `source` ([storage.md](storage.md#source-identifiers-wp-17)).

Files: the given `FILE`s, plus the exports of `--from-dir` (`ingest.file_patterns`, default
`*.csv`, `*.xlsx`; hidden and `.crdownload` files never match). Without files and without
`--from-dir`, the download directory is ingested. Unless `--dry-run`, one run record is appended
to `data/runs/<YYYY-MM-DD>.jsonl` (UTC date): full file names, validation counts per
`<severity>:<rule>`, append counts per sensor, failures, recorded conflicts. Ingesting the same
file again changes nothing (identical rows are skipped).

Prints `IMPORTED <file>: <sensor> <n> rows (<sensor> +<new> new, <filled> filled, <conflicts>
conflicting)` with the file's warnings, or `REJECTED <file> -> <quarantine path>`, and
`FAILED <file>: <reason>`. Exit code 1 if a file was rejected or could not be appended.

`--dry-run` parses and validates only (`VALID <file>: ...`): no store, no quarantine, no run
record.

```console
$ sivin ingest                                  # everything in data/downloads
$ sivin ingest "MeteoData_8615620 77799986 (VUT)_20260301_223842.csv"
$ sivin ingest --from-dir ~/exports --dry-run
```

## `sivin qc [--sensor ID ...] [--from WHEN] [--to WHEN] [--dry-run]`

Reads each sensor from the store (default: every stored sensor) and runs the quality pipeline
(`quality`, [quality-control.md](quality-control.md)) with the off-site log and the registry
placements as known deployments. Stored data carry no flags, so QC always runs on them before
anything else uses them. Writes `data/derived/events/<sensor_id>.json`
([storage.md](storage.md#derived-data-wp-17)) unless `--dry-run`.

| Option | Meaning |
|---|---|
| `--from WHEN`, `--to WHEN` | ISO 8601. A date or a time without offset is local time of `time.display_timezone`; a date as `--to` includes the whole day; `2026-06-01T10:00Z` is an explicit instant. Default: the whole record. |

Prints one line per sensor: samples, flag counts, events (warnings), values set aside, and the
events file; `<id>: no stored data` for a sensor without data in the range. Exit code 1 if a
sensor failed (e.g. a malformed store file), 3 if the registry, the off-site log or the
configuration is invalid.

## `sivin indices --season YEAR [--index ID ...] [--sensor ID ...] [--dry-run]`

Computes the climate indices of a season year for every stored sensor: QC over the whole
record first (the same flags as `sivin qc`), then the series is cut to the **season window**
(January 1 of the previous year to December 31 of the season year, local days, so
`winter_freeze` gets the previous autumn), `DailyWeather` is built with `time` and
`analytics`, and the `IndexContext` takes latitude and elevation from the registry placement in
force at the last sample. Index parameters come from `analytics.indices`.

| Option | Meaning |
|---|---|
| `--season YEAR` | Required, e.g. `2026`. |
| `--index`, `-i ID` | Only this index; repeat for several. Default: every registered index ([indices](indices/)). Unknown id: exit code 2. |

Writes `data/derived/indices/<season>.json` ([storage.md](storage.md#derived-data-wp-17))
unless `--dry-run`, and prints one line per sensor and index (value, unit, coverage,
complete). Exit code 1 if a sensor or an index failed.

## `sivin run [--season YEAR] [--sensor ID ...] [--skip-fetch] [--headed] [--dry-run]`

The whole pipeline, as the scheduled workflow (WP-4.1) runs it: `fetch` → `ingest` of the
downloaded files → `qc` of every stored sensor (events written) → `indices` of the season from
those QC results → one run record. It goes on past a failed device, file, sensor or index,
and past a failed login or missing credentials (recorded as `fetch: ...`; the stored data are
kept and still checked). `--season` defaults to the current year in `time.display_timezone`.
`--skip-fetch` does not use the portal and ingests the files already in the download
directory. `--sensor` restricts fetch, QC and indices (not the ingest of `--skip-fetch`).
Exit code 0 or 1 (see above); 3 only if the configuration, registry or off-site log is invalid.

```console
$ sivin run                       # daily job
$ sivin run --skip-fetch --dry-run --season 2026
```

## Typical local session

```console
$ cp .env.example .env            # fill in SIVIN_USER and SIVIN_PASSWORD
$ sivin sensors check
$ sivin fetch --headed            # watch the browser once
$ sivin ingest
$ sivin qc
$ sivin indices --season 2026
$ cat data/derived/indices/2026.json
```
