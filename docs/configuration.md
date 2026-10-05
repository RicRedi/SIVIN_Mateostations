# Configuration: `config/sivin.yaml`

One file configures the whole pipeline (MIGRATION_PLAN §1.3). It is read by every `sivin`
command ([cli.md](cli.md)); `--config FILE` uses another file. Without the file the defaults
apply.

- Every section is a **frozen pydantic model that rejects unknown keys**. A typo fails at
  start-up with its key path, e.g.
  `Invalid configuration config/sivin.yaml:` / `  analytics.indices.huglin.k_overide: Extra inputs are not permitted`
  (exit code 3).
- Keys that are not in the file take their defaults. The committed `config/sivin.yaml` lists
  the main keys with their default values; `sivin config show` prints **every** resolved
  value, `sivin config schema` the JSON schema.
- Paths are relative to the project root (the directory with `pyproject.toml`), resolved by
  `ProjectPaths`. No absolute user path is ever committed.
- Secrets never go here: the portal credentials are the environment variables `SIVIN_USER`
  and `SIVIN_PASSWORD`, locally from `.env` (see [cli.md](cli.md#global-options)).
- Every field has a description with its unit and the origin of its default (the reference
  below is generated from them).

## Sections

| Section | Model (module) | Content |
|---|---|---|
| `paths` | `PathsConfig` (`sivin.config.sections`) | store, derived data, quarantine, site, registry file, outputs |
| `time` | `TimeConfig` (`sivin.config.sections`) | source and display time zone, nominal sampling interval — **shared** (below) |
| `registry` | `RegistrySettings` (`sivin.registry.settings`) | area every sensor placement must lie in |
| `offsite_log` | `OffSiteLogSettings` (`sivin.registry.offsite`) | the off-site log file and the zone of its local times |
| `ingest.portal` | `PortalSettings` (`sivin.ingest.portal`) | portal URL, names, selectors, timeouts, browser, download directory ([ingest.md](ingest.md)) |
| `ingest.parsers` | `ParserSettings` (`sivin.ingest.parsers.columns`) | column aliases and units, order detection, plausible times ([data-format.md](data-format.md)) |
| `ingest.validation` | `ValidationSettings` (`sivin.ingest.validation`) | thresholds of the input validation |
| `ingest.quarantine_mode`, `ingest.file_patterns` | `IngestConfig` (`sivin.config.sections`) | move (default) or copy rejected files; files of `sivin ingest --from-dir` |
| `storage` | `StorageConfig` (`sivin.storage`) | conflict policy, partitioning, recorded conflicts ([storage.md](storage.md)) |
| `quality` | `QualityPipelineSettings` (`sivin.quality`) | enabled checks, `check_settings` per check, deployment detector ([quality-control.md](quality-control.md)) |
| `alignment` | `AlignmentConfig` (`sivin.alignment`) | strategy, its `params`, grid step, span ([alignment.md](alignment.md)) |
| `analytics` | `AnalyticsConfig` (`sivin.config.sections`) | coverage thresholds, exclusion masks, `indices` parameters per index ([indices](indices/)) |

The models of the subsystems live in their packages; `SivinConfig` (`sivin.config.model`)
composes them. `sivin.config` imports the subsystems, so importing it loads pandas; the CLI
imports it only when a command runs.

## Resolution

Every way of building a `SivinConfig` — the YAML file, `SivinConfig()`, `model_validate` —
first **resolves** the raw data (`ConfigResolver`, a pydantic `model_validator(mode="before")`).
Resolving a resolved configuration changes nothing.

### Values shared through `time`

Several subsystems have their own field for a project-wide value. They are set **once**, in
`time`, and copied into every field of the same name in every section (`SharedValues`, found by
field name, so a new subsystem with such a field is covered automatically):

| `time` key | Copied into every field named | Today |
|---|---|---|
| `expected_interval_s` (1830 s) | `expected_interval_s`, `nominal_interval_s` | `ingest.parsers.expected_interval_s`, `quality.check_settings.sampling.expected_interval_s`, `alignment.params.expected_interval_s` (nearest strategy), `analytics.indices.<id>.sampling.nominal_interval_s` (`botrytis_broome`, `dew_point`, `frost`, `heat_hours`, `powdery_mildew_gt`, `vpd`); `DailyWeather` coverage uses `time.expected_interval_s` directly |
| `source_timezone` | `source_timezone` | `ingest.parsers.source_timezone` |
| `display_timezone` | `display_timezone` | `quality.deployment.display_timezone`; local days of `DailyWeather` and of the indices |

Writing one of these fields elsewhere **with a different value** is an error:
`  quality.check_settings.sampling.expected_interval_s: is set by time.expected_interval_s (1830.0); remove it here or change time.expected_interval_s`.
The same value is accepted. The reference below shows such fields as `= time.<key>`.

Defaults that are **multiples of the interval** follow it too (owner decision, WP-1.7
round 2; `sivin.config.derived`) unless they are set explicitly:

| Key | Default |
|---|---|
| `quality.check_settings.spike.min_interval_s` | 1 × `time.expected_interval_s` |
| `quality.check_settings.spike.max_interval_s`, `quality.check_settings.step.max_interval_s` | 3 × |
| `quality.check_settings.precip_counter.max_interval_s` | 1.5 × |
| `alignment.params.max_gap_s` (linear interpolation) | 1.5 × |
| `analytics.indices.<id>.sampling.max_sample_duration_s` | 2.5 × |

The reference below shows them as `= <factor> x time.expected_interval_s`. A validation error
that names one of these fields (e.g. an explicit duration cap below the nominal interval) adds
the value of `time.expected_interval_s` and the rule, so the message explains the relation.

`offsite_log.timezone` is not shared: it is the zone of the times the owner writes into the
log.

### Registry-backed settings

Three mappings name registered classes, so their keys are known only through the registries.
They are validated **when the configuration is loaded**, with the settings model of each class,
and completed with every default (`sivin.config.registered`):

| Mapping | Keys | Model |
|---|---|---|
| `quality.check_settings` | every enabled check (`screening_checks`, `deployed_checks`) | the check's `settings_model`; settings of an unknown check or of a check that is not enabled are an error at `quality.check_settings.<name>` |
| `alignment.params` | — | `params_model` of `alignment.strategy` |
| `analytics.indices` | every registered index (an unknown id is an error) | the index's `params_model` |

An unknown key reports its full path, e.g. `quality.check_settings.range.temp_mx`.
`analytics.indices.gsr` accepts `preset: <cultivar>` instead of `targets`; the preset is
replaced by the sugar targets of `GSR_CULTIVAR_PRESETS` (today `sauvignon_blanc`, 2820 °C·d to
200 g/L, Parker et al. 2020 as verified in WP-L.1); giving both is an error.

## Examples

```yaml
time:
  expected_interval_s: 1800          # every subsystem follows

quality:
  check_settings:
    range: { temp_climate_min_c: -28.0 }
    battery: { low_battery_v: 3.4 }
  deployment:
    mode: enforce                    # detector flags PRE_DEPLOYMENT (WP-1.5 behaviour)

analytics:
  min_daily_coverage: 0.8
  indices:
    huglin: { k_override: 1.05 }     # legacy value instead of the latitude lookup
    gsr: { preset: sauvignon_blanc }

alignment:
  strategy: linear_interpolation
  params: { max_gap_s: 3000 }
```

## Reference

Generated by `ConfigReference().markdown(heading_level=4)` (the same tables as
`sivin config schema --markdown`); a test keeps this section
equal to the generated text. `= time.<key>` marks a value set from the `time` section.

<!-- BEGIN GENERATED REFERENCE -->

#### `paths`

| Key | Default | Description |
|---|---|---|
| `paths.data_dir` | `"data"` | Measurement store directory (path, relative to the root). |
| `paths.derived_dir` | `"data/derived"` | Derived data written by sivin qc and sivin indices: events/<sensor_id>.json and indices/<season>.json (path, relative to the root; MIGRATION_PLAN §2.5). |
| `paths.quarantine_dir` | `"data/quarantine"` | Rejected export files with their validation report as JSON (path, relative to the root; MIGRATION_PLAN §2.7). |
| `paths.site_dir` | `"site"` | Generated static site data directory (path, relative). |
| `paths.sensors_file` | `"sensors/sensors.geojson"` | Sensor registry, GeoJSON FeatureCollection (path, relative to the root). |
| `paths.output_dir` | `"vystupy"` | Plots and other outputs for people (path, relative). |

#### `time`

| Key | Default | Description |
|---|---|---|
| `time.source_timezone` | `"Europe/Prague"` | IANA zone of the wall-clock timestamps in the provider's exports; the portal exports local time (owner decision Q2, 2026-10-05). Also sets ingest.parsers.source_timezone. |
| `time.display_timezone` | `"Europe/Prague"` | IANA zone for display and for local calendar days of daily aggregates. Also sets quality.deployment.display_timezone. |
| `time.expected_interval_s` | `1830.0` | Nominal sampling interval in seconds; 1830 s is the median step of the first real export (sensor 77799986, 2025-07-30 to 2026-03-01, MIGRATION_PLAN §0.6.1), the legacy configs estimated 1825 s. Used for daily coverage and set into every subsystem with its own interval field (ingest.parsers, the sampling check, the aligner, the sample durations of the indices). |

#### `registry`

| Key | Default | Description |
|---|---|---|
| `registry.allowed_area.min_lat_deg` | `48.55` | Southern edge (degrees north). |
| `registry.allowed_area.max_lat_deg` | `51.06` | Northern edge (degrees north). |
| `registry.allowed_area.min_lon_deg` | `12.09` | Western edge (degrees east). |
| `registry.allowed_area.max_lon_deg` | `18.86` | Eastern edge (degrees east). |

#### `offsite_log`

| Key | Default | Description |
|---|---|---|
| `offsite_log.file` | `"sensors/offsite_log.yaml"` | The off-site log (path, relative to the project root). |
| `offsite_log.timezone` | `"Europe/Prague"` | IANA zone of local times in the log (no unit); the vineyards' zone (MIGRATION_PLAN §2.8). |

#### `ingest`

| Key | Default | Description |
|---|---|---|
| `ingest.portal.portal_url` | `"https://lemon.e-service.cz/"` | Start URL of the data provider's portal; it redirects to the login (URL). |
| `ingest.portal.folder_name` | `"SIVIN VUT"` | Text of the folder link that lists our devices (text). |
| `ingest.portal.meteo_tab_name` | `"Meteorologická data"` | Text of the device tab with the meteorological data and the export (text). |
| `ingest.portal.export_section_name` | `"Historie meteorologických dat"` | Heading text of the tab section whose Excel button is clicked (text). |
| `ingest.portal.attempts_per_device` | `2` | How often a device is tried before it is recorded as failed (count); the client returns to the device list before each retry. |
| `ingest.portal.min_export_size_bytes` | `1` | Smallest accepted export file (bytes); smaller files are incomplete. |
| `ingest.portal.selectors.username_id` | `"username"` | HTML id of the user name input (id). |
| `ingest.portal.selectors.password_id` | `"password"` | HTML id of the password input (id). |
| `ingest.portal.selectors.submit_css` | `"input[type='submit']"` | CSS selector of the login submit button (CSS). |
| `ingest.portal.selectors.spinner_id` | `"UpdateProgress"` | HTML id of the DotVVM progress spinner; waited for to disappear (id). |
| `ingest.portal.selectors.viewmodel_id` | `"__dot_viewmodel_root"` | HTML id of the hidden input holding the DotVVM viewmodel JSON (id). |
| `ingest.portal.selectors.link_xpath_template` | `"//a[contains(., {text})]"` | XPath of a link whose text contains {text}; used for the folder and the device links (XPath template). |
| `ingest.portal.selectors.tab_xpath_template` | `"//a[contains(text(), {text})]"` | XPath of the tab link whose own text contains {text} (XPath template). |
| `ingest.portal.selectors.excel_button_xpath` | `"//button[.//i[contains(@class, 'mdi-file-excel')]]"` | XPath of all Excel export buttons; the first visible one is the fallback when no button is found inside the export section (XPath). |
| `ingest.portal.selectors.section_button_xpath_template` | `"//*[contains(normalize-space(text()), {text})]/ancestor::*[.//button[.//i[contains(@class, 'mdi-file-excel')]]][1]//button[.//i[contains(@class, 'mdi-file-excel')]]"` | XPath of the Excel buttons inside the section whose heading contains {text} (export_section_name): the nearest ancestor of the heading that holds an Excel button, then its buttons. A visible match also proves that the meteorological tab is shown. Structure assumed from the legacy comments, [to be verified] (XPath template). |
| `ingest.portal.timeouts.element_wait_s` | `15.0` | Maximum wait for an element or the spinner (s); legacy value 15 s. |
| `ingest.portal.timeouts.download_wait_s` | `30.0` | Maximum wait for an export to appear in the download directory (s); legacy value 30 s. |
| `ingest.portal.timeouts.poll_interval_s` | `0.5` | Polling interval of explicit waits and of the download watcher (s). |
| `ingest.portal.timeouts.device_settle_s` | `3.0` | Fixed pause after clicking a device link (s), for DotVVM to render the device page; legacy value 3 s, [to be tuned] on the first real run. |
| `ingest.portal.timeouts.tab_settle_s` | `2.0` | Fixed pause after switching to the meteorological tab (s); legacy value 2 s, [to be tuned] on the first real run. |
| `ingest.portal.timeouts.list_check_s` | `5.0` | Maximum wait for the device list after going back from a device (s); when it does not appear, the client reloads the portal and opens the folder again. |
| `ingest.portal.headless` | `true` | Run the browser without a window (flag). |
| `ingest.portal.browser` | `"chrome"` | Key of the registered WebDriverFactory that starts the browser (name). |
| `ingest.portal.download_dir` | `"data/downloads"` | Directory the browser saves exports into (path, relative to the project root; resolved by the caller with resolved_against before use). |
| `ingest.portal.chrome_binary` | `null` | Chrome/Chromium executable (path). When unset, the CHROME_BINARY environment variable is used, otherwise the browser found by chromedriver. |
| `ingest.portal.chromedriver_path` | `null` | chromedriver executable (path). When unset: $CHROMEWEBDRIVER/chromedriver (set on GitHub-hosted runners), then chromedriver on PATH, then webdriver-manager downloads a matching one. |
| `ingest.portal.chrome_arguments` | `["--window-size=1920,1080"]` | Extra Chrome command-line arguments (list of flags). The window size keeps the export button inside the viewport in headless mode; add '--no-sandbox' only when running as root in a container. |
| `ingest.portal.partial_download_suffixes` | `[".crdownload", ".tmp"]` | File name endings of unfinished browser downloads, ignored (suffixes). |
| `ingest.portal.ignored_download_prefixes` | `["."]` | File name beginnings ignored by the download watcher (prefixes); Chrome on Linux writes hidden '.com.google.Chrome.*' temporary files. |
| `ingest.parsers.source_timezone` | = `time.source_timezone` | IANA zone of the wall-clock timestamps in the exports. The portal exports local time (owner decision Q2, 2026-10-05). |
| `ingest.parsers.aliases.timestamp` | `["Datum a čas", "Datum", "Čas", "Datum und Uhrzeit", "Datum/Uhrzeit", "Zeitstempel", "Zeit", "Date and time", "Date", "Time", "Datetime", "Timestamp"]` | Header names of the local timestamp column (Czech, German, English). 'Datum a čas' is the name used by the provider's exports (confirmed by the first real export, MIGRATION_PLAN §0.6.1). |
| `ingest.parsers.aliases.temp_c` | `["Teplota", "Teplota vzduchu", "Temperatur", "Lufttemperatur", "Temperature", "Air temperature", "Temp"]` | Header names of the air temperature column (values in °C). |
| `ingest.parsers.aliases.rh_pct` | `["Vlhkost", "Relativní vlhkost", "Vlhkost vzduchu", "Luftfeuchtigkeit", "Relative Luftfeuchtigkeit", "Luftfeuchte", "Feuchtigkeit", "Humidity", "Relative humidity", "RH"]` | Header names of the relative humidity column (values in %). |
| `ingest.parsers.aliases.temp_units` | `["°C", "C", "degC", "deg C", "℃"]` | Units accepted after a temperature header, e.g. 'Teplota (°C)'. |
| `ingest.parsers.aliases.rh_units` | `["%", "% RH", "%RH", "% rel.", "pct"]` | Units accepted after a relative humidity header, e.g. 'Vlhkost (%)'. |
| `ingest.parsers.aliases.timestamp_units` | `[]` | Qualifiers accepted after a timestamp header. Empty by default, so that a header such as 'Datum a čas (UTC)' is rejected instead of being read in source_timezone. |
| `ingest.parsers.aliases.precip_mm` | `["Srážky", "Srážka", "Srážky za interval", "Niederschlag", "Niederschlagsmenge", "Regen", "Precipitation", "Rain", "Rainfall"]` | Header names of the optional column of precipitation in the interval since the previous sample (values in mm). 'Srážky (mm)' is the name used by the provider's exports (confirmed by the first real export, MIGRATION_PLAN §0.6.1). |
| `ingest.parsers.aliases.precip_total_mm` | `["Celkové srážky", "Srážky celkem", "Kumulativní srážky", "Niederschlag gesamt", "Gesamtniederschlag", "Kumulierter Niederschlag", "Total precipitation", "Cumulative precipitation", "Precipitation total", "Total rain", "Rain total"]` | Header names of the optional column of the device's cumulative precipitation counter (values in mm). 'Celkové srážky (mm)' is the name used by the provider's exports (confirmed by the first real export). |
| `ingest.parsers.aliases.battery_v` | `["Nabití baterie", "Napětí baterie", "Baterie", "Batterie", "Batteriespannung", "Battery", "Battery voltage"]` | Header names of the optional battery voltage column (values in V). 'Nabití baterie (V)' is the name used by the provider's exports (confirmed by the first real export). |
| `ingest.parsers.aliases.precip_units` | `["mm", "l/m²", "l/m2"]` | Units accepted after a precipitation or cumulative precipitation header, e.g. 'Srážky (mm)'; 1 l/m² of water equals 1 mm of precipitation. |
| `ingest.parsers.aliases.battery_units` | `["V"]` | Units accepted after a battery header, e.g. 'Nabití baterie (V)'. |
| `ingest.parsers.header_search_rows` | `10` | Number of leading rows (count) searched for the header row, i.e. the first row with a timestamp column. The portal CSV has one title row ('Meteo Data;') before the header (confirmed by a real export); the XLSX layout is unverified (Q11). |
| `ingest.parsers.day_first` | `true` | Read numeric dates with '.' or '/' day first (5.1.2026 = 5 January 2026), as in the legacy sampl_freq_basic.py. ISO dates (2026-01-05) are always year first. |
| `ingest.parsers.newest_first_min_share` | `0.75` | Share (0-1, dimensionless) of the counted steps between consecutive timestamps that must go back in time for a table to be read as newest first and reversed. Steps inside the repeated hour of a fall-back transition are not counted. The first real export is newest first (MIGRATION_PLAN §0.6.1); the share is a project default [to be verified]. |
| `ingest.parsers.newest_first_min_steps` | `4` | Minimum number of counted non-zero steps (count) needed to decide that a table is newest first. A shorter table that steps back is read oldest first and reported. Project default [to be verified]. |
| `ingest.parsers.max_backward_step_s` | `7200.0` | Rows more than this many seconds earlier than the latest accepted row (clock reset; exact copies from overlapping exports are kept), or isolated rows this far ahead of their neighbours (glitched timestamp), are dropped and reported. At least 3600 s, the length of the repeated hour of a fall-back transition. Project default [to be verified]. |
| `ingest.parsers.earliest_timestamp` | `"2020-01-01T00:00:00"` | Earliest plausible local timestamp; earlier rows (e.g. after a device clock reset) are dropped and reported. The project started in 2025; project default [to be tuned]. |
| `ingest.parsers.latest_timestamp` | `null` | Latest plausible local timestamp. None: the run time plus 'max_future_s', in source_timezone. Set explicitly only for reproducible tests or re-imports. |
| `ingest.parsers.max_future_s` | `86400.0` | Seconds after the run time up to which a timestamp is still plausible (clock drift, time zone confusion). Project default [to be tuned]. |
| `ingest.parsers.expected_interval_s` | = `time.expected_interval_s` | Nominal sampling interval in seconds (1830 s, the median step of the first real export, MIGRATION_PLAN §0.6.1); used by the day/month swap guard. |
| `ingest.parsers.long_step_factor` | `48.0` | A step between consecutive timestamps longer than expected_interval_s times this factor (dimensionless; 48 x 1830 s = 24.4 h) counts as long for the day/month swap guard. Project default [to be verified]. |
| `ingest.parsers.csv_delimiter` | `";"` | Field delimiter of CSV exports. |
| `ingest.parsers.csv_encodings` | `["utf-8-sig", "cp1250"]` | Text encodings tried in order for CSV exports: UTF-8 (with or without BOM, used by the legacy reader), then Windows-1250 (Czech Windows) [to be verified]. |
| `ingest.parsers.legacy_sheet_sensors` | `{}` | Legacy workbook (data.xlsx): worksheet name -> 8-digit sensor serial, e.g. {'8271': '77678271'}. The 4-digit sheet names are ambiguous, so the caller resolves them (normally through the sensor registry). Empty: no legacy import. |
| `ingest.validation.min_data_rows` | `1` | Minimum number of data rows (count) below the header of every table; fewer means an empty or truncated export (ERROR). |
| `ingest.validation.max_unparseable_value_share` | `0.05` | Share of data rows (0-1, dimensionless) whose temperature or humidity cell is not empty but is not a number. Above it the file is rejected (ERROR); at or below it the values become missing (WARNING). Project default [to be verified]. |
| `ingest.validation.max_unparseable_timestamp_share` | `0.05` | Share of data rows (0-1, dimensionless) without a readable timestamp. Above it the file is rejected (ERROR); at or below it the rows are dropped (WARNING). Project default [to be verified]. |
| `ingest.validation.temp_min_c` | `-60.0` | Gross lower bound of air temperature in °C; only guards against unit or column mix-ups, the climatological range check is quality control (WP-1.5). Project default, deliberately generous [to be verified]. |
| `ingest.validation.temp_max_c` | `70.0` | Gross upper bound of air temperature in °C (catches °F and K exports). Project default, deliberately generous [to be verified]. |
| `ingest.validation.rh_min_pct` | `0.0` | Lower bound of relative humidity in % (physical limit). |
| `ingest.validation.rh_max_pct` | `100.0` | Upper bound of relative humidity in % (physical limit). |
| `ingest.validation.max_implausible_timestamp_share` | `0.05` | Share of data rows (0-1, dimensionless) with a timestamp outside the plausible range (ParserSettings.earliest_timestamp to the run time plus max_future_s), and also of rows out of sequence (rule out-of-sequence). Above it the file is rejected (ERROR); at or below it the rows are dropped (WARNING). Project default [to be verified]. |
| `ingest.validation.min_error_rows` | `3` | A share threshold turns a finding into an ERROR only when more than this many rows (count) are affected, or all of them; so one footer or comment row in a short file is a WARNING. Project default [to be verified]. |
| `ingest.validation.max_out_of_bounds_share` | `0.05` | Share of the present values of a variable (0-1, dimensionless) outside the gross bounds above which the file is rejected (ERROR); at or below it each such value is reported (WARNING) and left to quality control. Also the share of humidity values at or below 'rh_fraction_max_pct' that marks humidity given as a 0-1 fraction. Project default [to be verified]. |
| `ingest.validation.rh_fraction_max_pct` | `1.0` | Relative humidity in % at or below which a value looks like a 0-1 fraction instead of a percentage (unit mix-up). Project default [to be verified]. |
| `ingest.validation.precip_min_mm` | `0.0` | Lower bound of the precipitation of one sample interval in mm (physical limit: an amount of precipitation cannot be negative). Values below it are reported (WARNING) and read as missing. |
| `ingest.validation.precip_max_mm` | `500.0` | Gross upper bound of the precipitation of one sample interval in mm; only guards against unit mix-ups and garbage, the plausibility check per interval is quality control (check 'precip_range'). Project default, deliberately generous [to be verified]. |
| `ingest.validation.precip_total_min_mm` | `0.0` | Lower bound of the cumulative precipitation counter in mm (a sum of non-negative amounts cannot be negative). |
| `ingest.validation.precip_total_max_mm` | `100000.0` | Gross upper bound of the cumulative precipitation counter in mm; only catches garbage and unit mix-ups (the first real export reads 323.0-326.4 mm). Project default, deliberately generous [to be verified]. |
| `ingest.validation.battery_min_v` | `0.0` | Gross lower bound of the battery voltage in V (a voltage reading below 0 V). |
| `ingest.validation.battery_max_v` | `10.0` | Gross upper bound of the battery voltage in V; catches millivolts and column mix-ups (the first real export reads 3.0-3.7 V). Project default [to be verified against the device data sheet]. |
| `ingest.quarantine_mode` | `"move"` | 'move' (default: a rejected export leaves the download directory, so it is not rejected again on every run) or 'copy' (the original stays) a rejected export into paths.quarantine_dir (no unit). |
| `ingest.file_patterns` | `["*.csv", "*.xlsx"]` | Glob patterns (no unit) of the export files sivin ingest --from-dir picks up; browser leftovers (*.crdownload) never match. |

#### `storage`

| Key | Default | Description |
|---|---|---|
| `storage.conflict_policy` | `"prefer_newest"` | What to keep when an imported row has the timestamp of a stored row but different values (name, no unit): 'prefer_newest' (the last appended value wins, default per MIGRATION_PLAN WP-1.4), 'prefer_existing' (use for back-fills of older exports) or 'raise'. A missing value never conflicts with a present one. |
| `storage.max_recorded_conflicts` | `100` | Conflicts per append kept with both values in the append result and the run log and logged one by one per partition file (count); further ones are only counted. Project default. |
| `storage.partitioning` | `"year"` | How a sensor's rows are split into files (name, no unit): 'year' = one file per UTC calendar year (MIGRATION_PLAN §2.5). |

#### `quality`

| Key | Default | Description |
|---|---|---|
| `quality.screening_checks` | `["missing", "sampling", "range", "precip_range", "precip_counter", "battery"]` | Registry names of the checks run on the whole series, in this order. The precipitation and battery checks (WP-1.9) report events and set no flags. |
| `quality.deployed_checks` | `["spike", "step", "persistence"]` | Registry names of the checks run on every outdoor stretch after deployment detection, in this order. |
| `quality.check_settings.battery.low_battery_v` | `3.3` | Battery voltage in V below which a 'low battery' warning is reported. Project default [to be tuned]: the first real export reads 3.0-3.7 V; the voltage at which the device stops measuring is not known [to be verified against the device data sheet]. |
| `quality.check_settings.battery.recovery_margin_v` | `0.1` | Hysteresis in V: a low battery episode ends only at a reading of at least low_battery_v + recovery_margin_v (default 3.4 V). 0.1 V is one step of the export resolution, so a reading that merely returns to the threshold does not end the episode. Project default [to be tuned]; 0 disables the hysteresis. |
| `quality.check_settings.missing.variables` | `["temp_c", "rh_pct"]` | Variables whose NaN values count as missing (column names, no unit). |
| `quality.check_settings.missing.rule` | `"any"` | 'any': flag a row when one checked variable is NaN; 'all': only when every one is. Default 'any' by owner decision 2026-10-05 (MIGRATION_PLAN §0.5): if one variable is missing at a given time, the whole measurement is invalid. |
| `quality.check_settings.persistence.temp_tolerance_c` | `0.05` | Largest temperature range (max - min, °C) of a run that still counts as unchanged; half of an assumed 0.1 °C resolution. Project default [to be verified against the sensor resolution]. |
| `quality.check_settings.persistence.temp_min_duration_s` | `43200.0` | Shortest duration (s) of an unchanged temperature run that is flagged. Project default 12 h for 30-min data, longer than calm isothermal nights [to be tuned on real data]. |
| `quality.check_settings.persistence.rh_tolerance_pct` | `0.5` | Largest relative-humidity range (%) of a run that still counts as unchanged; half of an assumed 1 % resolution. Project default [to be verified]. |
| `quality.check_settings.persistence.rh_min_duration_s` | `43200.0` | Shortest duration (s) of an unchanged humidity run that is flagged. Project default 12 h [to be tuned on real data]. |
| `quality.check_settings.persistence.rh_saturation_pct` | `97.0` | Relative humidity (%) at or above which the air counts as saturated. A run (temperature or humidity) in which at least saturation_share of the samples are saturated is not flagged: in fog or an inversion both readings legitimately stay constant for many hours. Null disables the exemption. Project default [to be tuned on real data]. |
| `quality.check_settings.persistence.saturation_share` | `0.5` | Share (0-1, dimensionless) of saturated samples that exempts a run. Project default. |
| `quality.check_settings.precip_counter.tolerance_mm` | `0.15` | Largest difference in mm between the interval precipitation of a sample and the increase of the counter since the previous sample that still counts as agreement; also the largest counter decrease that is not a reset. Both columns are exported with 0.1 mm resolution and the first real export shows differences of 0.1 mm (MIGRATION_PLAN §0.6.1). Project default [to be tuned]. |
| `quality.check_settings.precip_counter.max_interval_s` | = `1.5 x time.expected_interval_s` | Longest time between two consecutive samples in s for which the interval precipitation is compared with the counter increase (1.5 x the nominal interval of 1830 s). After a longer gap the counter also contains the precipitation of samples that are missing. Project default [to be tuned]. |
| `quality.check_settings.precip_range.precip_min_mm` | `0.0` | Lowest plausible precipitation of one sample interval in mm (physical limit: an amount of precipitation cannot be negative). |
| `quality.check_settings.precip_range.precip_max_mm` | `50.0` | Highest plausible precipitation of one sample interval (nominal 1830 s, about 30 min) in mm. Project default [to be tuned]: far above the largest value of the first real export (0.9 mm) and meant to catch device or transfer errors, not heavy rain; not taken from literature. |
| `quality.check_settings.range.temp_physical_min_c` | `-50.0` | Lowest physically plausible air temperature in °C. Project default [to be verified against the sensor data sheet]. |
| `quality.check_settings.range.temp_physical_max_c` | `60.0` | Highest physically plausible air temperature in °C. Project default [to be verified against the sensor data sheet]. |
| `quality.check_settings.range.temp_climate_min_c` | `-30.0` | Lowest climatologically plausible air temperature in South Moravia in °C; null disables the climatological lower limit. Project default [to be verified against station records of the region]. |
| `quality.check_settings.range.temp_climate_max_c` | `42.0` | Highest climatologically plausible air temperature in South Moravia in °C; null disables the climatological upper limit. Project default [to be verified against station records of the region]. |
| `quality.check_settings.range.rh_min_pct` | `0.0` | Lowest possible relative humidity in % (physical limit). |
| `quality.check_settings.range.rh_max_pct` | `100.0` | Highest possible relative humidity in % (physical limit). |
| `quality.check_settings.sampling.expected_interval_s` | = `time.expected_interval_s` | Nominal sampling interval Δt0 in seconds. Set from time.expected_interval_s by the configuration (WP-1.7); default 1830 s, the median step of the first real export. |
| `quality.check_settings.sampling.gap_factor` | `3.0` | An interval longer than gap_factor x Δt0 (dimensionless factor k) is a gap. Project default [to be tuned on real data]. |
| `quality.check_settings.sampling.tolerance_fraction` | `0.25` | Allowed deviation ε of an interval from a whole multiple of Δt0, as a fraction of Δt0 (dimensionless). Project default chosen to tolerate clock drift [to be tuned]. |
| `quality.check_settings.spike.temp_max_rate_c_per_h` | `8.0` | Largest plausible temperature change rate in °C/h towards and away from a sample; about 4 °C per 30 min interval. Project default for 30-min data [to be tuned on real data]; methodology Zahumenský (2004). |
| `quality.check_settings.spike.rh_max_rate_pct_per_h` | `40.0` | Largest plausible relative-humidity change rate in %/h; about 20 % per 30 min interval. Project default [to be tuned on real data]; methodology Zahumenský (2004). |
| `quality.check_settings.spike.min_interval_s` | = `1 x time.expected_interval_s` | Intervals shorter than this (s) are scaled as if they were this long, so that closely spaced samples do not get tiny thresholds. Default: nominal interval 1830 s. |
| `quality.check_settings.spike.max_interval_s` | = `3 x time.expected_interval_s` | A neighbour farther away than this (s) cannot confirm a spike (the series may have changed during the gap). Project default: three nominal intervals. |
| `quality.check_settings.step.temp_min_jump_c` | `5.0` | Smallest temperature change between two consecutive samples (°C) that is examined as a step. Project default for 30-min data [to be tuned on real data]. |
| `quality.check_settings.step.rh_min_jump_pct` | `25.0` | Smallest relative-humidity change between two consecutive samples (%) that is examined as a step. Project default [to be tuned on real data]. |
| `quality.check_settings.step.window_s` | `10800.0` | Length (s) of the windows before and after a jump. Project default 3 h. |
| `quality.check_settings.step.min_window_samples` | `3` | Fewest valid samples (count) each window needs. Project default. |
| `quality.check_settings.step.persistence_fraction` | `0.5` | Share (0-1, dimensionless) of the jump that the median level after it must keep relative to the median level before it. Project default. |
| `quality.check_settings.step.max_adjacent_fraction` | `0.4` | Largest change (as a share 0-1 of the jump, dimensionless) allowed in each of the two neighbouring intervals: a sensor step happens within one interval, a weather front (e.g. -10 °C within 1 h) spreads over several. Project default. |
| `quality.check_settings.step.max_interval_s` | = `3 x time.expected_interval_s` | Jumps across a longer interval (s) are not examined (the level may have changed during the gap). Project default: three nominal intervals. |
| `quality.detect_deployment` | `true` | Run deployment detection (advisory by default, see deployment.mode); if false, only the off-site log decides which samples are off site. |
| `quality.deployment.mode` | `"advisory"` | 'advisory' (default, owner decision 2026-10-05): only warnings, no flags; the off-site log is the source of truth for PRE_DEPLOYMENT. 'enforce': detected indoor samples get PRE_DEPLOYMENT (behaviour of WP-1.5). No unit. |
| `quality.deployment.log_tolerance_s` | `21600.0` | Advisory mode: a detected indoor period counts as covered by the off-site log if a logged period (touching periods merged) contains it after widening by this many seconds on both sides. Project default 6 h, the same as known_tolerance_s [to be tuned on real data]. |
| `quality.deployment.display_timezone` | = `time.display_timezone` | IANA zone (no unit) of the times in owner-facing warnings; the zone of the off-site log, so a suggested period can be pasted into it. |
| `quality.deployment.change_points.min_segment_s` | `86400.0` | Shortest segment in seconds; also the shortest indoor stay (service) that can be detected, the minimum separation of change points and the refinement radius. Project default 1 day, so that every segment has a daily spread. |
| `quality.deployment.change_points.window_s` | `2592000.0` | Length (s) of the windows the search runs in; the result does not depend on the series length. Project default 30 days. |
| `quality.deployment.change_points.stride_s` | `1296000.0` | Spacing (s) of the window starts (epoch-anchored). Project default 15 days. |
| `quality.deployment.change_points.penalty_factor` | `1.0` | Factor c (dimensionless) of the BIC-like penalty c·(p+1)·ln n a split must gain (n = samples in the window). 1 = Schwarz/BIC weight. Project default. |
| `quality.deployment.change_points.max_change_points` | `30` | Largest number of change points (count) per window; with 1-day minimum segments a 30-day window cannot hold more. Project default. |
| `quality.deployment.change_points.temp_variance_floor_c2` | `0.01` | Variance floor of temperature in °C² (= (0.1 °C)²), so quantised indoor data do not have zero variance. Project default. |
| `quality.deployment.change_points.rh_variance_floor_pct2` | `0.25` | Variance floor of relative humidity in %² (= (0.5 %)²). Project default. |
| `quality.deployment.change_points.min_rh_fraction` | `0.5` | Humidity is used only if at least this share (0-1, dimensionless) of the usable temperature samples also has a humidity value. Project default. |
| `quality.deployment.regime.room_min_c` | `5.0` | Lowest median temperature (°C) of a room; covers unheated stores in winter. Project default [to be tuned on real data]. |
| `quality.deployment.regime.room_max_c` | `35.0` | Highest median temperature (°C) of a room; covers hot offices in summer. Project default [to be tuned on real data]. |
| `quality.deployment.regime.indoor_max_daily_spread_c` | `4.0` | Largest daily temperature spread s_max (P95 - P5 per 24 h, °C) of an indoor stretch; an office with day-time heating stays below it. Project default [to be tuned on real data]. |
| `quality.deployment.regime.indoor_max_rh_pct` | `75.0` | Largest median relative humidity h_max (%) of an indoor stretch; excludes fog and most overcast days. Project default [to be tuned on real data]. |
| `quality.deployment.regime.indoor_max_rh_spread_pct` | `8.0` | Largest daily relative-humidity spread r_max (P95 - P5 per 24 h, %) of an indoor stretch: indoor humidity is steady, outdoor humidity follows the daily temperature cycle even under overcast skies. Project default [to be tuned]. |
| `quality.deployment.regime.min_window_samples` | `12` | Fewest samples (count) a 24-h window needs to contribute a daily spread. Project default: about a quarter of a day at the nominal 1830 s interval. |
| `quality.deployment.contrast.min_spread_ratio` | `2.0` | Factor k_s (dimensionless) by which the outdoor daily temperature spread must exceed the indoor one. Project default. |
| `quality.deployment.contrast.spread_floor_c` | `0.5` | Floor s_0 (°C) of the indoor daily spread in the ratio. Project default. |
| `quality.deployment.contrast.min_level_difference_c` | `5.0` | Median temperature difference ΔT (°C) that counts as a vote. Project default. |
| `quality.deployment.contrast.min_rh_excess_pct` | `15.0` | Amount Δh (%) by which the outdoor median humidity must exceed the indoor one. Project default. |
| `quality.deployment.contrast.min_rh_spread_ratio` | `2.0` | Factor k_r (dimensionless) by which the outdoor daily humidity spread must exceed the indoor one. Project default. |
| `quality.deployment.contrast.rh_spread_floor_pct` | `2.0` | Floor r_0 (%) of the indoor daily humidity spread in the ratio. |
| `quality.deployment.contrast.min_votes` | `2` | Votes V (count) needed to confirm a transition; capped at the number of available votes (2 without humidity). Project default. |
| `quality.deployment.contrast.window_s` | `172800.0` | Length (s) of the local windows on each side of a boundary. Project default 2 days. |
| `quality.deployment.contrast.min_window_samples` | `24` | Fewest samples (count) each local window needs; fewer means not confirmable. Project default: about half a day at the nominal 1830 s. |
| `quality.deployment.transport.enabled` | `false` | Move transport transients to the indoor side. Off by default: a weather change within the outdoor reference day can make real vineyard samples look like a transient and exclude up to max_duration_s of them (review round 2). |
| `quality.deployment.transport.max_duration_s` | `10800.0` | Longest transport transient (s) moved to the indoor side; also the distance (s) indoor comparison windows keep from a boundary, whether trimming is enabled or not. Project default 3 h. |
| `quality.deployment.transport.margin_c` | `3.0` | Margin m (°C) around the indoor and outdoor reference ranges. Project default. |
| `quality.deployment.transport.reference_s` | `86400.0` | Length (s) of the outdoor reference stretch. Project default 1 day. |
| `quality.deployment.transport.min_reference_samples` | `12` | Fewest samples (count) of the reference stretch; fewer disables trimming. |
| `quality.deployment.known_tolerance_s` | `21600.0` | Largest distance in seconds between a detected and a known deployment that still counts as agreement. Project default 6 h [to be tuned with Q3]. |
| `quality.deployment.ignore_mask` | `259` | QcFlag bits (integer bit mask, dimensionless) of samples not used for detection. Default MISSING\|OUT_OF_RANGE\|MANUAL_EXCLUDE = 259. |

#### `alignment`

| Key | Default | Description |
|---|---|---|
| `alignment.strategy` | `"nearest_within_tolerance"` | Registered alignment strategy (identifier, no unit): 'nearest_within_tolerance' or 'linear_interpolation'. |
| `alignment.params (linear_interpolation).max_gap_s` | = `1.5 x time.expected_interval_s` | Largest distance in seconds (inclusive) between the two usable samples that enclose a grid point for it to be interpolated. Default 1.5 x 1830 s = 2745 s (neighbouring samples only); project choice, to be verified on real data. |
| `alignment.params (nearest_within_tolerance).tolerance_s` | `null` | Explicit override of the largest distance in seconds (inclusive) between a grid point and the sample assigned to it. Default (null): expected_interval_s / 2 + margin_s. |
| `alignment.params (nearest_within_tolerance).expected_interval_s` | = `time.expected_interval_s` | Nominal sampling interval of the sensors in seconds. Set from time.expected_interval_s by the configuration (WP-1.7); default 1830 s, the median step of the first real export. |
| `alignment.params (nearest_within_tolerance).margin_s` | `20.0` | Margin in seconds added to half the sampling interval for clock jitter; default 20 s, project choice [to be tuned on real data]. |
| `alignment.grid_step_s` | `1800.0` | Grid step in seconds (at least 1 s, whole nanoseconds); default 1800 s (30 min, MIGRATION_PLAN §2.7). |
| `alignment.span` | `"union"` | Span the grid covers (identifier, no unit): 'union' (any sensor has data) or 'overlap' (every sensor with data has data). |

#### `analytics`

| Key | Default | Description |
|---|---|---|
| `analytics.min_daily_coverage` | `0.9` | Share of a day (0-1, dimensionless) covered by valid samples for the day to count as complete. Project default, to be tuned on real data. |
| `analytics.min_season_coverage` | `0.9` | Share of complete days in an index period (0-1, dimensionless) for a complete index result. Project default, to be tuned on real data. |
| `analytics.exclude_mask` | `311` | QcFlag bits (integer bit mask, dimensionless) that exclude a sample from indices. Default: MISSING\|OUT_OF_RANGE\|SPIKE\|STUCK\|PRE_DEPLOYMENT\|MANUAL_EXCLUDE = 311. |
| `analytics.auxiliary_exclude_mask` | `288` | QcFlag bits (integer bit mask, dimensionless) that exclude a sample from the daily precipitation sum and minimum battery voltage (WP-1.9). Default PRE_DEPLOYMENT\|MANUAL_EXCLUDE = 288: only 'not a vineyard measurement'. |
| `analytics.indices.bedd.daily_mean` | `"minmax"` | Definition of the daily mean temperature (°C): 'minmax' = (T_max + T_min) / 2, the Winkler convention (Amerine and Winkler, 1944), or 'sample_mean' = mean of all valid samples of the local day. |
| `analytics.indices.bedd.base_temp_c` | `10.0` | Base temperature in °C. |
| `analytics.indices.bedd.cap_c_d` | `9.0` | Upper limit of the daily contribution in °C·d (19 °C mean - 10 °C base; Gladstones, 1992; secondary source). |
| `analytics.indices.bedd.dtr_lower_c` | `10.0` | Diurnal temperature range in °C below which the daily contribution is reduced (Gladstones, 1992; secondary source). |
| `analytics.indices.bedd.dtr_upper_c` | `13.0` | Diurnal temperature range in °C above which the daily contribution is increased (Gladstones, 1992; secondary source). |
| `analytics.indices.bedd.dtr_factor` | `0.25` | Adjustment in °C·d per °C of diurnal range outside the band; 0 disables it (Gladstones, 1992; secondary source). |
| `analytics.indices.bedd.day_length_coefficient` | `1.0` | Day-length (latitude) coefficient, dimensionless; 1 = no adjustment. Gladstones (1992) gives latitude-dependent values that are not shipped [to be verified]. |
| `analytics.indices.bedd.cap_order` | `"after_adjustment"` | 'after_adjustment': cap the adjusted daily contribution (default, form commonly quoted from Gladstones, 1992); 'before_adjustment': cap the mean excess, then adjust (Gladstones' monthly formulation as reported; not found in a source [to be verified]). |
| `analytics.indices.bedd.period` | `{"start": {"month": 4, "day": 1}, "end": {"month": 10, "day": 31}}` | Accumulation period, April 1 - October 31 (northern hemisphere). |
| `analytics.indices.botrytis_broome.wet_rh_threshold_pct` | `90.0` | Relative humidity (%) at or above which a sample counts as wet. Proxy for leaf wetness; project default [to be tuned], not from Broome et al. (1995). |
| `analytics.indices.botrytis_broome.max_dry_interruption_h` | `1.0` | Longest dry interruption (h) inside one wetness period; longer dry spells end it. Project default [to be tuned]. |
| `analytics.indices.botrytis_broome.min_event_duration_h` | `0.0` | Shortest wetness period (h) that is reported as an event. Project default (report all) [to be tuned]. |
| `analytics.indices.botrytis_broome.max_wetness_h` | `null` | Optional cap (h) on the wetness duration W used in the model; long estimated periods (W > 24 h) otherwise give Y close to 1. None (default): no cap. Project choice. |
| `analytics.indices.botrytis_broome.coefficients.intercept` | `-2.647866` | a (dimensionless), Broome et al. (1995). |
| `analytics.indices.botrytis_broome.coefficients.wetness_h` | `-0.374927` | b, per hour of wetness (1/h), Broome et al. (1995). |
| `analytics.indices.botrytis_broome.coefficients.wetness_temp` | `0.061601` | c, per hour and °C (1/(h·°C)), Broome et al. (1995). |
| `analytics.indices.botrytis_broome.coefficients.wetness_temp_sq` | `-0.001511` | d, per hour and °C squared (1/(h·°C²)), Broome et al. (1995). |
| `analytics.indices.botrytis_broome.risk_bands` | `[]` | Risk classes by season-maximum infection probability (0-1), ascending, the first starting at 0. Empty (default): no classification, because no class limits are taken from literature. |
| `analytics.indices.botrytis_broome.season.start_month` | `4` | Month of the first day (1-12). |
| `analytics.indices.botrytis_broome.season.start_day` | `1` | Day of month of the first day (1-31). |
| `analytics.indices.botrytis_broome.season.end_month` | `10` | Month of the last day (1-12). |
| `analytics.indices.botrytis_broome.season.end_day` | `31` | Day of month of the last day (1-31). |
| `analytics.indices.botrytis_broome.sampling.nominal_interval_s` | = `time.expected_interval_s` | Nominal sampling interval in seconds (s). Duration of the last sample of a series and of a sample followed by a data gap. Set from time.expected_interval_s by the configuration (WP-1.7); default 1830 s, the median step of the first real export (sivin.core.defaults.DEFAULT_SAMPLING_INTERVAL_S). |
| `analytics.indices.botrytis_broome.sampling.max_sample_duration_s` | = `2.5 x time.expected_interval_s` | Longest step to the next sample in seconds (s) that still counts as continuous data; a longer step is a data gap. Default 2.5 x 1830 s = 4575 s (project default: bridges one missing sample), to be tuned on real data. |
| `analytics.indices.budburst.daily_mean` | `"minmax"` | Definition of the daily mean temperature (°C): 'minmax' = (T_max + T_min) / 2, the Winkler convention (Amerine and Winkler, 1944), or 'sample_mean' = mean of all valid samples of the local day. |
| `analytics.indices.budburst.base_temp_c` | `5.0` | Base temperature in °C; project default [to be verified] (models compared by García de Cortázar-Atauri et al., 2009, use various bases). |
| `analytics.indices.budburst.period` | `{"start": {"month": 1, "day": 1}, "end": {"month": 6, "day": 30}}` | Prediction period (local dates); January 1 - June 30 is a project default. |
| `analytics.indices.budburst.max_missing_days_at_start` | `0` | Maximum number of incomplete days (d) at the start of the period before the first complete day; more means the accumulation start is not covered (e.g. late deployment) and no date is predicted. Project default 0, to be tuned. |
| `analytics.indices.budburst.f_star_c_d` | `null` | Critical thermal sum for budburst in °C·d; no default (needs local calibration). Without it the result is 'not configured'. |
| `analytics.indices.cool_night.period_start` | `"09-01"` | First day of the period (MM-DD); September 1 (Tonietto & Carbonneau 2004). |
| `analytics.indices.cool_night.period_end` | `"09-30"` | Last day of the period (MM-DD); September 30 (Tonietto & Carbonneau 2004). |
| `analytics.indices.dew_point.period_start` | `"04-01"` | First day of the period (MM-DD); April 1, growing season (Amerine & Winkler 1944). Project choice [to be tuned]. |
| `analytics.indices.dew_point.period_end` | `"10-31"` | Last day of the period (MM-DD); October 31, growing season (Amerine & Winkler 1944). Project choice [to be tuned]. |
| `analytics.indices.dew_point.magnus_a` | `17.625` | Magnus coefficient a (dimensionless); 17.625 (Alduchov & Eskridge 1996). |
| `analytics.indices.dew_point.magnus_b_c` | `243.04` | Magnus coefficient b in °C; 243.04 (Alduchov & Eskridge 1996). |
| `analytics.indices.dew_point.sampling.max_sample_duration_s` | = `2.5 x time.expected_interval_s` | Longest step to the next sample (s) that the sample represents in full; a longer step is a gap and the sample counts only nominal_interval_s. Project default 4575 s = 2.5 x 1830 s [to be tuned]. |
| `analytics.indices.dew_point.sampling.nominal_interval_s` | = `time.expected_interval_s` | Time (s) represented by a sample followed by a gap and by the last sample of a series. Set from time.expected_interval_s by the configuration (WP-1.7); default the nominal sampling interval of 1830 s (median step of the first real export). |
| `analytics.indices.dtr_ripening.period_start` | `"08-01"` | First day of the ripening window (MM-DD) when no start_date is given. Project default August 1 [to be tuned]. |
| `analytics.indices.dtr_ripening.period_end` | `"09-30"` | Last day of the ripening window (MM-DD). Project default September 30 [to be tuned]. |
| `analytics.indices.dtr_ripening.start_date` | `null` | Explicit first day of the window (date), e.g. the modelled véraison; overrides period_start and must lie in the computed season year, not after period_end. |
| `analytics.indices.frost.period_start` | `"04-01"` | First day of the period (MM-DD); April 1, growing season (Amerine & Winkler 1944). Project choice [to be tuned]. |
| `analytics.indices.frost.period_end` | `"10-31"` | Last day of the period (MM-DD); October 31, growing season (Amerine & Winkler 1944). Project choice [to be tuned]. |
| `analytics.indices.frost.frost_c` | `0.0` | Frost threshold in °C (T at or below it). Plan §3.2 default. |
| `analytics.indices.frost.hard_frost_c` | `-2.0` | Hard-frost threshold in °C (T at or below it). Project default (plan §3.2), not a literature value; stage-dependent critical temperatures: Poling (2008). |
| `analytics.indices.frost.after_date` | `null` | First day (date) from which frost is critical, e.g. the modelled budburst; must lie in the computed season year; None = no critical-frost figures. |
| `analytics.indices.frost.sampling.max_sample_duration_s` | = `2.5 x time.expected_interval_s` | Longest step to the next sample (s) that the sample represents in full; a longer step is a gap and the sample counts only nominal_interval_s. Project default 4575 s = 2.5 x 1830 s [to be tuned]. |
| `analytics.indices.frost.sampling.nominal_interval_s` | = `time.expected_interval_s` | Time (s) represented by a sample followed by a gap and by the last sample of a series. Set from time.expected_interval_s by the configuration (WP-1.7); default the nominal sampling interval of 1830 s (median step of the first real export). |
| `analytics.indices.gdd_winkler.daily_mean` | `"minmax"` | Definition of the daily mean temperature (°C): 'minmax' = (T_max + T_min) / 2, the Winkler convention (Amerine and Winkler, 1944), or 'sample_mean' = mean of all valid samples of the local day. |
| `analytics.indices.gdd_winkler.max_missing_days` | `0` | Maximum number of incomplete days (d) in the period for which the sum is still classified; incomplete days contribute nothing, so the sum is biased low. Project default 0, to be tuned on real data. |
| `analytics.indices.gdd_winkler.base_temp_c` | `10.0` | Base temperature in °C; 10 °C (50 °F) after Amerine and Winkler (1944). |
| `analytics.indices.gdd_winkler.period` | `{"start": {"month": 4, "day": 1}, "end": {"month": 10, "day": 31}}` | Accumulation period (month-day, local dates); April 1 - October 31 for the northern hemisphere (Amerine and Winkler, 1944). |
| `analytics.indices.gdd_winkler.regions.bounds` | `[{"label": "region_i", "upper": 1388.888888888889}, {"label": "region_ii", "upper": 1666.6666666666667}, {"label": "region_iii", "upper": 1944.4444444444446}, {"label": "region_iv", "upper": 2222.222222222222}]` | Classes with strictly increasing inclusive upper bounds. |
| `analytics.indices.gdd_winkler.regions.top_label` | `"region_v"` | Label of values above the last bound. |
| `analytics.indices.gfv.daily_mean` | `"minmax"` | Definition of the daily mean temperature (°C): 'minmax' = (T_max + T_min) / 2, the Winkler convention (Amerine and Winkler, 1944), or 'sample_mean' = mean of all valid samples of the local day. |
| `analytics.indices.gfv.base_temp_c` | `0.0` | Base temperature in °C (Parker et al., 2011). |
| `analytics.indices.gfv.period` | `{"start": {"month": 3, "day": 1}, "end": {"month": 10, "day": 31}}` | Prediction period; starts March 1 (day of year 60 in common years, Parker et al., 2011); the end, October 31, is a project default. |
| `analytics.indices.gfv.max_missing_days_at_start` | `0` | Maximum number of incomplete days (d) at the start of the period before the first complete day; more means the accumulation start is not covered (e.g. late deployment) and no date is predicted. Project default 0, to be tuned. |
| `analytics.indices.gfv.flowering_f_star_c_d` | `null` | Critical sum for flowering in °C·d; no default (general model: Parker et al., 2011; cultivars: Parker et al., 2013). Without it the result is 'not configured'. |
| `analytics.indices.gfv.veraison_f_star_c_d` | `null` | Critical sum for véraison in °C·d; no default (general model: Parker et al., 2011; cultivars: Parker et al., 2013). Without it the result is 'not configured'. |
| `analytics.indices.gsr.daily_mean` | `"minmax"` | Definition of the daily mean temperature (°C): 'minmax' = (T_max + T_min) / 2, the Winkler convention (Amerine and Winkler, 1944), or 'sample_mean' = mean of all valid samples of the local day. |
| `analytics.indices.gsr.base_temp_c` | `0.0` | Base temperature in °C (Parker et al., 2020). |
| `analytics.indices.gsr.period` | `{"start": {"month": 4, "day": 1}, "end": {"month": 10, "day": 31}}` | Prediction period; starts April 1 (Parker et al., 2020); the end, October 31, is a project default. |
| `analytics.indices.gsr.max_missing_days_at_start` | `0` | Maximum number of incomplete days (d) at the start of the period before the first complete day; more means the accumulation start is not covered (e.g. late deployment) and no date is predicted. Project default 0, to be tuned. |
| `analytics.indices.gsr.targets` | `[]` | Sugar targets as (label, F* in °C·d) for the cultivar of the sensor, e.g. label 'sugar_200_g_l', from Parker et al. (2020); none shipped. The value is the day of year of the last target. |
| `analytics.indices.gst.daily_mean` | `"minmax"` | Definition of the daily mean temperature (°C): 'minmax' = (T_max + T_min) / 2, the Winkler convention (Amerine and Winkler, 1944), or 'sample_mean' = mean of all valid samples of the local day. |
| `analytics.indices.gst.period` | `{"start": {"month": 4, "day": 1}, "end": {"month": 10, "day": 31}}` | Averaging period, April 1 - October 31 (Jones, 2006). |
| `analytics.indices.gst.classes.bounds` | `[{"label": "too_cool", "upper": 13.0}, {"label": "cool", "upper": 15.0}, {"label": "intermediate", "upper": 17.0}, {"label": "warm", "upper": 19.0}, {"label": "hot", "upper": 24.0}]` | Classes with strictly increasing inclusive upper bounds. |
| `analytics.indices.gst.classes.top_label` | `"too_hot"` | Label of values above the last bound. |
| `analytics.indices.heat_hours.period_start` | `"04-01"` | First day of the period (MM-DD); April 1, growing season (Amerine & Winkler 1944). |
| `analytics.indices.heat_hours.period_end` | `"10-31"` | Last day of the period (MM-DD); October 31, growing season (Amerine & Winkler 1944). |
| `analytics.indices.heat_hours.optimum_min_c` | `20.0` | Lower bound of the optimum band in °C (inclusive). Project default (plan §3.2), not a literature value. |
| `analytics.indices.heat_hours.optimum_max_c` | `30.0` | Upper bound of the optimum band in °C (inclusive). Project default (plan §3.2), not a literature value. |
| `analytics.indices.heat_hours.heat_stress_c` | `30.0` | Heat-stress threshold in °C (T above it). Project default (plan §3.2); light-saturated leaf photosynthesis of Semillon was optimal at 30 °C (Greer & Weedon 2012, abstract). |
| `analytics.indices.heat_hours.extreme_heat_c` | `35.0` | Extreme-heat threshold in °C (T above it). Project default (plan §3.2); a 35 °C daily maximum halved berry anthocyanins vs 25 °C (Mori et al. 2007, abstract). |
| `analytics.indices.heat_hours.sampling.max_sample_duration_s` | = `2.5 x time.expected_interval_s` | Longest step to the next sample (s) that the sample represents in full; a longer step is a gap and the sample counts only nominal_interval_s. Project default 4575 s = 2.5 x 1830 s [to be tuned]. |
| `analytics.indices.heat_hours.sampling.nominal_interval_s` | = `time.expected_interval_s` | Time (s) represented by a sample followed by a gap and by the last sample of a series. Set from time.expected_interval_s by the configuration (WP-1.7); default the nominal sampling interval of 1830 s (median step of the first real export). |
| `analytics.indices.huglin.daily_mean` | `"minmax"` | Definition of the daily mean temperature (°C): 'minmax' = (T_max + T_min) / 2, the Winkler convention (Amerine and Winkler, 1944), or 'sample_mean' = mean of all valid samples of the local day. |
| `analytics.indices.huglin.max_missing_days` | `0` | Maximum number of incomplete days (d) in the period for which the sum is still classified; incomplete days contribute nothing, so the sum is biased low. Project default 0, to be tuned on real data. |
| `analytics.indices.huglin.base_temp_c` | `10.0` | Base temperature in °C (Huglin, 1978). |
| `analytics.indices.huglin.period` | `{"start": {"month": 4, "day": 1}, "end": {"month": 9, "day": 30}}` | Accumulation period, April 1 - September 30 (Huglin, 1978). |
| `analytics.indices.huglin.k_bands` | `[{"min_lat_deg": 40.0, "max_lat_deg": 42.0, "k": 1.02}, {"min_lat_deg": 42.0, "max_lat_deg": 44.0, "k": 1.03}, {"min_lat_deg": 44.0, "max_lat_deg": 46.0, "k": 1.04}, {"min_lat_deg": 46.0, "max_lat_deg": 48.0, "k": 1.05}, {"min_lat_deg": 48.0, "max_lat_deg": 50.0, "k": 1.06}]` | Day-length coefficient K (dimensionless) by latitude band in degrees north, after Huglin (1978) and Tonietto and Carbonneau (2004). |
| `analytics.indices.huglin.k_override` | `null` | Fixed K (dimensionless) used instead of the latitude lookup; the legacy vineyard_analyst used 1.05. |
| `analytics.indices.huglin.classes.bounds` | `[{"label": "very_cool", "upper": 1500.0}, {"label": "cool", "upper": 1800.0}, {"label": "temperate", "upper": 2100.0}, {"label": "temperate_warm", "upper": 2400.0}, {"label": "warm", "upper": 3000.0}]` | Classes with strictly increasing inclusive upper bounds. |
| `analytics.indices.huglin.classes.top_label` | `"very_warm"` | Label of values above the last bound. |
| `analytics.indices.powdery_mildew_gt.band_min_temp_c` | `21.11111111111111` | Lower bound (inclusive) of the favourable band in °C; 70 °F (Gubler 1999). |
| `analytics.indices.powdery_mildew_gt.band_max_temp_c` | `29.444444444444443` | Upper bound (inclusive) of the favourable band in °C; 85 °F (Gubler 1999). |
| `analytics.indices.powdery_mildew_gt.min_favourable_run_h` | `6.0` | Consecutive hours (h) in the band that make a day favourable (Gubler 1999). |
| `analytics.indices.powdery_mildew_gt.onset_days` | `3` | Consecutive favourable days (d) that start the index (Gubler 1999). |
| `analytics.indices.powdery_mildew_gt.onset_index_points` | `60` | Index value (points) on the onset day: 3 onset days x 20 points (UC IPM model description: each of the three onset days earns 20 points). |
| `analytics.indices.powdery_mildew_gt.max_undetermined_carry_days` | `1` | Consecutive undetermined days (d) that may carry the onset streak; a longer run of them resets it. Project default [to be tuned]. |
| `analytics.indices.powdery_mildew_gt.favourable_day_points` | `20` | Points added for a favourable day after onset (Gubler 1999). |
| `analytics.indices.powdery_mildew_gt.unfavourable_day_points` | `10` | Points subtracted for a non-favourable day (Gubler 1999). |
| `analytics.indices.powdery_mildew_gt.heat_temp_c` | `35.0` | Heat threshold (inclusive) in °C; 95 °F (Gubler 1999). |
| `analytics.indices.powdery_mildew_gt.min_heat_duration_min` | `15.0` | Minutes (min) at or above the heat threshold for the penalty (Gubler 1999). |
| `analytics.indices.powdery_mildew_gt.heat_points` | `10` | Points subtracted for a heat day after onset (Gubler 1999). |
| `analytics.indices.powdery_mildew_gt.min_index_points` | `0` | Lower bound of the index (points), UC IPM. |
| `analytics.indices.powdery_mildew_gt.max_index_points` | `100` | Upper bound of the index (points), UC IPM. |
| `analytics.indices.powdery_mildew_gt.moderate_from_points` | `40` | Lowest index (points) of the class 'moderate' (UC IPM: 40-50). |
| `analytics.indices.powdery_mildew_gt.high_from_points` | `60` | Lowest index (points) of the class 'high' (UC IPM: 60-100). |
| `analytics.indices.powdery_mildew_gt.season.start_month` | `4` | Month of the first day (1-12). |
| `analytics.indices.powdery_mildew_gt.season.start_day` | `1` | Day of month of the first day (1-31). |
| `analytics.indices.powdery_mildew_gt.season.end_month` | `10` | Month of the last day (1-12). |
| `analytics.indices.powdery_mildew_gt.season.end_day` | `31` | Day of month of the last day (1-31). |
| `analytics.indices.powdery_mildew_gt.sampling.nominal_interval_s` | = `time.expected_interval_s` | Nominal sampling interval in seconds (s). Duration of the last sample of a series and of a sample followed by a data gap. Set from time.expected_interval_s by the configuration (WP-1.7); default 1830 s, the median step of the first real export (sivin.core.defaults.DEFAULT_SAMPLING_INTERVAL_S). |
| `analytics.indices.powdery_mildew_gt.sampling.max_sample_duration_s` | = `2.5 x time.expected_interval_s` | Longest step to the next sample in seconds (s) that still counts as continuous data; a longer step is a data gap. Default 2.5 x 1830 s = 4575 s (project default: bridges one missing sample), to be tuned on real data. |
| `analytics.indices.tropical_days_nights.period_start` | `"01-01"` | First day of the counting period (MM-DD); January 1 (calendar year). |
| `analytics.indices.tropical_days_nights.period_end` | `"12-31"` | Last day of the counting period (MM-DD); December 31 (calendar year). |
| `analytics.indices.tropical_days_nights.tropical_day_tmax_c` | `30.0` | Tropical day: daily T_max >= this value, °C (ČHMÚ). |
| `analytics.indices.tropical_days_nights.tropical_night_tmin_c` | `20.0` | Tropical night: daily T_min >= this value, °C (ČHMÚ). |
| `analytics.indices.tropical_days_nights.summer_day_tmax_c` | `25.0` | Summer day: daily T_max >= this value, °C (ČHMÚ). |
| `analytics.indices.tropical_days_nights.frost_day_tmin_c` | `0.0` | Frost day: daily T_min < this value, °C (ČHMÚ). |
| `analytics.indices.tropical_days_nights.ice_day_tmax_c` | `0.0` | Ice day: daily T_max < this value, °C (ČHMÚ). |
| `analytics.indices.vpd.period_start` | `"04-01"` | First day of the period (MM-DD); April 1, growing season (Amerine & Winkler 1944). Project choice [to be tuned]. |
| `analytics.indices.vpd.period_end` | `"10-31"` | Last day of the period (MM-DD); October 31, growing season (Amerine & Winkler 1944). Project choice [to be tuned]. |
| `analytics.indices.vpd.threshold_kpa` | `2.0` | VPD threshold in kPa for the hours above it. Project default [to be tuned]; not taken from literature. |
| `analytics.indices.vpd.daytime_start_hour` | `null` | First local clock hour (h, 0-23) of the daytime mean; None = no daytime mean. |
| `analytics.indices.vpd.daytime_end_hour` | `null` | Local clock hour (h, 1-24) at which the daytime window ends (exclusive). |
| `analytics.indices.vpd.sampling.max_sample_duration_s` | = `2.5 x time.expected_interval_s` | Longest step to the next sample (s) that the sample represents in full; a longer step is a gap and the sample counts only nominal_interval_s. Project default 4575 s = 2.5 x 1830 s [to be tuned]. |
| `analytics.indices.vpd.sampling.nominal_interval_s` | = `time.expected_interval_s` | Time (s) represented by a sample followed by a gap and by the last sample of a series. Set from time.expected_interval_s by the configuration (WP-1.7); default the nominal sampling interval of 1830 s (median step of the first real export). |
| `analytics.indices.winter_freeze.dormant_start` | `"11-01"` | First day of the dormant season in the previous year (MM-DD); November 1, project default [to be tuned]. |
| `analytics.indices.winter_freeze.dormant_end` | `"03-31"` | Last day of the dormant season in the season year (MM-DD); March 31, project default [to be tuned]. |
| `analytics.indices.winter_freeze.damage_threshold_c` | `-15.0` | Winter-injury threshold in °C (daily T_min below it). Project default (plan §3.2), not a literature value; background Zabadal et al. (2007). |
| `analytics.indices.winter_freeze.severe_threshold_c` | `-20.0` | Severe winter-injury threshold in °C (daily T_min below it). Project default (plan §3.2), not a literature value; background Zabadal et al. (2007). |

<!-- END GENERATED REFERENCE -->
