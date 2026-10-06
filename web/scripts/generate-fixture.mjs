/**
 * Generate the SYNTHETIC demo data set in `web/public/data/` following the static site data
 * contract (MIGRATION_PLAN.md §2.6, schema_version 1).
 *
 * The values are invented by a seeded pseudo-random model; they are NOT measurements. The output
 * is deterministic: the same SEED always produces byte-identical files.
 *
 * Model, per sensor and sample (step 1825 s with a per-sensor phase and ±3 s Gaussian clock
 * jitter, 1 Jun – 30 Sep 2026 UTC):
 *   temp_c = seasonal mean(day of year) + shared daily weather anomaly (AR(1))
 *            + diurnal cosine (maximum at 15:00 local solar time) + elevation/inversion offset
 *            + white noise
 *   rh_pct = daily base (anti-correlated with the anomaly) − 3 %/°C × (temp − daily mean) + noise,
 *            clipped to 25–100 %
 * Plus: a few nulls (qc MISSING), spikes (qc SPIKE), a stuck run (qc STUCK), a 7-hour gap,
 * one sensor taken to the office for service for about a day and a half (an `off_site` event
 * from the off-site log, MIGRATION_PLAN.md §2.8; indoor values ≈22 °C flagged PRE_DEPLOYMENT),
 * and one sensor that stops reporting early (`stale` in latest.json).
 * Scale (WP-3.5): 16 more SYNTHETIC sensors with fictional ids, names and groups and only one
 * month of data (SCALE_SENSORS), so the fixture has 20 sensors in three municipalities.
 *
 * Usage: `npm run fixture` (from `web/`).
 */
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SEED = 20261005;
const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'data');
const DISPLAY_TIMEZONE = 'Europe/Prague';
const GENERATED_AT = '2026-10-01T00:00:00Z';
const SEASON = 2026;

const STEP_S = 1825;
/** Standard deviation of the simulated clock jitter of each sample, seconds. */
const CLOCK_JITTER_S = 3;
const HOUR_S = 3600;
const DAY_S = 86_400;
const START_T = Date.UTC(2026, 5, 1) / 1000;
const END_T = Date.UTC(2026, 9, 1) / 1000;

/**
 * Sensors with a full season of data: ids and positions from the repository's
 * sensor_location.gpx (elevation rounded to 0.1 m). They are real devices, so the fixture makes
 * no claim about them: municipality, track and variety stay null (as in the registry).
 */
const SENSORS = [
  { id: '77678271', lat: 48.880215, lon: 16.673002, elevation_m: 183.9, phaseS: 0, municipality: null, track: null, variety: null },
  { id: '77680921', lat: 48.879593, lon: 16.672016, elevation_m: 201.6, phaseS: 437, municipality: null, track: null, variety: null },
  { id: '77800065', lat: 48.878895, lon: 16.6709, elevation_m: 222.4, phaseS: 911, municipality: null, track: null, variety: null },
  { id: '77799986', lat: 48.883827, lon: 16.648304, elevation_m: 219.2, phaseS: 1303, municipality: null, track: null, variety: null },
];

/**
 * SYNTHETIC sensors that exercise the sensor picker and marker clustering at a larger network
 * size: invented ids (9xxxxxxx), positions, names and data, three fictional municipalities with
 * several tracks, one sensor without a track, one without any grouping, one inactive and one
 * retired sensor. They have data only for SHORT_PERIOD, so the fixture stays small.
 */
const SCALE_SENSORS = [
  { id: '90000101', lat: 48.8826, lon: 16.6761, elevation_m: 190.2, municipality: 'Obec A', track: 'Trať 1', variety: 'Pálava' },
  { id: '90000111', lat: 48.8722, lon: 16.6598, elevation_m: 205.0, municipality: 'Obec A', track: 'Trať 2', variety: 'Müller Thurgau' },
  { id: '90000112', lat: 48.8741, lon: 16.6627, elevation_m: 211.4, municipality: 'Obec A', track: 'Trať 2', variety: 'Müller Thurgau' },
  { id: '90000113', lat: 48.8705, lon: 16.6571, elevation_m: 198.7, municipality: 'Obec A', track: 'Trať 2', variety: 'Frankovka' },
  { id: '90000201', lat: 48.8512, lon: 16.7418, elevation_m: 176.3, municipality: 'Obec B', track: 'Trať 3', variety: 'Ryzlink vlašský' },
  { id: '90000202', lat: 48.8534, lon: 16.7446, elevation_m: 181.9, municipality: 'Obec B', track: 'Trať 3', variety: 'Ryzlink vlašský' },
  { id: '90000203', lat: 48.8497, lon: 16.7392, elevation_m: 173.5, municipality: 'Obec B', track: 'Trať 3', variety: 'Sauvignon', status: 'inactive', endT: Date.UTC(2026, 8, 20, 8) / 1000 },
  { id: '90000301', lat: 48.8431, lon: 16.7512, elevation_m: 230.8, municipality: 'Obec B', track: 'Trať 4', variety: 'Zweigeltrebe' },
  { id: '90000302', lat: 48.8452, lon: 16.7547, elevation_m: 241.2, municipality: 'Obec B', track: 'Trať 4', variety: 'Zweigeltrebe', status: 'retired', endT: Date.UTC(2026, 8, 15, 10) / 1000 },
  { id: '90000303', lat: 48.8418, lon: 16.7486, elevation_m: 226.0, municipality: 'Obec B', track: 'Trať 4', variety: 'Modrý Portugal' },
  { id: '90000401', lat: 48.9213, lon: 16.5982, elevation_m: 258.4, municipality: 'Obec C', track: 'Trať 5', variety: 'Tramín červený' },
  { id: '90000402', lat: 48.9236, lon: 16.6011, elevation_m: 262.9, municipality: 'Obec C', track: 'Trať 5', variety: null },
  { id: '90000411', lat: 48.9164, lon: 16.5915, elevation_m: 247.1, municipality: 'Obec C', track: 'Trať 6', variety: 'Chardonnay' },
  { id: '90000412', lat: 48.9147, lon: 16.5943, elevation_m: 244.6, municipality: 'Obec C', track: 'Trať 6', variety: 'Chardonnay' },
  { id: '90000421', lat: 48.9258, lon: 16.6074, elevation_m: 266.0, municipality: 'Obec C', track: null, variety: null },
  { id: '90000501', lat: 48.9003, lon: 16.7005, elevation_m: 195.5, municipality: null, track: null, variety: 'Neuburské' },
];
/** Period of the SCALE_SENSORS data, [start, end) in Unix seconds (UTC). */
const SHORT_PERIOD = [Date.UTC(2026, 8, 1) / 1000, Date.UTC(2026, 9, 1) / 1000];
/** Clock phase spacing of the SCALE_SENSORS, seconds (co-prime with STEP_S). */
const SCALE_PHASE_STEP_S = 389;
const PORTAL_PREFIX = '8615620';

const OFFICE_SENSOR = '77799986';
/** Synthetic off-site period of OFFICE_SENSOR, [start, end) in Unix seconds (UTC). */
const OFF_SITE = [Date.UTC(2026, 5, 4, 6, 0) / 1000, Date.UTC(2026, 5, 5, 14, 0) / 1000];
/** The site publishes only the reason of an off-site period, never the log's note (WP-3.5). */
const OFF_SITE_DETAIL = 'service';
const OFFICE_TEMP_C = 22;
const OFFICE_AMPLITUDE_C = 0.6;
const OFFICE_RH_PCT = 42;
const GAP_SENSOR = '77680921';
const GAP = [Date.UTC(2026, 6, 14, 9) / 1000, Date.UTC(2026, 6, 14, 16) / 1000];
const STEP_EVENT_T = Date.UTC(2026, 7, 22, 10) / 1000;
const STUCK_SENSOR = '77678271';
const STUCK_START_T = Date.UTC(2026, 7, 10, 2) / 1000;
const STUCK_SAMPLES = 10;
const STALE_SENSOR = '77800065';
const STALE_END_T = Date.UTC(2026, 8, 27, 12) / 1000;

const SEASONAL_BASE_C = 11.5;
const SEASONAL_AMPLITUDE_C = 10;
const WARMEST_DAY_OF_YEAR = 200;
const DAYS_PER_YEAR = 365;
const ANOMALY_PERSISTENCE = 0.7;
const ANOMALY_SD_C = 2;
const DIURNAL_AMPLITUDE_C = 5.5;
const DIURNAL_AMPLITUDE_SD_C = 1.5;
const DIURNAL_AMPLITUDE_LIMITS_C = [2, 8];
const WARMEST_SOLAR_HOUR = 15;
const LAPSE_RATE_C_PER_M = 0.0065;
const NIGHT_INVERSION_C_PER_M = 0.03;
const REFERENCE_ELEVATION_M = 200;
const SAMPLE_NOISE_C = 0.15;
const RH_BASE_PCT = 70;
const RH_PER_ANOMALY_PCT = 1.5;
const RH_DAILY_SD_PCT = 5;
const RH_PER_DEGREE_PCT = 3;
const RH_NOISE_PCT = 2;
const RH_LIMITS_PCT = [25, 100];
const NULL_PROBABILITY = 0.003;
const SPIKES_PER_SENSOR = 3;
const SPIKE_C = 8;

const QC = { MISSING: 1, SPIKE: 4, STEP: 8, STUCK: 16, PRE_DEPLOYMENT: 32 };
/** MISSING | OUT_OF_RANGE | SPIKE | STUCK | PRE_DEPLOYMENT | MANUAL_EXCLUDE (plan §2.7). */
const EXCLUDE_MASK = 1 | 2 | 4 | 16 | 32 | 256;

/** Season windows used by the placeholder indices (local calendar days, inclusive). */
const GDD_SEASON_DAYS = 214;
const HUGLIN_SEASON_DAYS = 183;
const BASE_TEMP_C = 10;

/** Mulberry32: small, fast, deterministic 32-bit PRNG returning floats in [0, 1). */
function mulberry32(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let x = state;
    x = Math.imul(x ^ (x >>> 15), x | 1);
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

const random = mulberry32(SEED);

/** Standard normal deviate (Box–Muller). */
function gaussian() {
  const u = 1 - random();
  const v = random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

const clamp = (value, [low, high]) => Math.min(high, Math.max(low, value));
const round1 = (value) => (value === null ? null : Math.round(value * 10) / 10);
const round2 = (value) => Math.round(value * 100) / 100;
const dayOfYear = (t) => Math.floor((t - Date.UTC(2026, 0, 1) / 1000) / DAY_S) + 1;

/** Shared daily weather: temperature anomaly, diurnal amplitude and humidity base per UTC day. */
function dailyWeather() {
  const days = Math.ceil((END_T - START_T) / DAY_S) + 1;
  const weather = [];
  let anomaly = 0;
  for (let day = 0; day < days; day++) {
    anomaly = ANOMALY_PERSISTENCE * anomaly + ANOMALY_SD_C * gaussian();
    const amplitude = clamp(
      DIURNAL_AMPLITUDE_C + DIURNAL_AMPLITUDE_SD_C * gaussian() + 0.3 * anomaly,
      DIURNAL_AMPLITUDE_LIMITS_C,
    );
    const rhBase = RH_BASE_PCT - RH_PER_ANOMALY_PCT * anomaly + RH_DAILY_SD_PCT * gaussian();
    weather.push({ anomaly, amplitude, rhBase });
  }
  return weather;
}

/** Linear interpolation of a daily field between day midpoints, so the signal has no jumps. */
function interpolate(weather, t, field) {
  const position = (t - START_T) / DAY_S - 0.5;
  const index = Math.max(0, Math.floor(position));
  const fraction = clamp(position - index, [0, 1]);
  const a = weather[index][field];
  const b = weather[Math.min(index + 1, weather.length - 1)][field];
  return a + (b - a) * fraction;
}

function outdoorSample(sensor, t, weather) {
  const meanC =
    SEASONAL_BASE_C +
    SEASONAL_AMPLITUDE_C * Math.cos((2 * Math.PI * (dayOfYear(t) - WARMEST_DAY_OF_YEAR)) / DAYS_PER_YEAR) +
    interpolate(weather, t, 'anomaly');
  const solarHour = ((t % DAY_S) / HOUR_S + sensor.lon / 15) % 24;
  const diurnal = Math.cos((2 * Math.PI * (solarHour - WARMEST_SOLAR_HOUR)) / 24);
  const elevationDelta = sensor.elevation_m - REFERENCE_ELEVATION_M;
  const nightFactor = Math.max(0, -diurnal);
  const offsetC = -LAPSE_RATE_C_PER_M * elevationDelta + NIGHT_INVERSION_C_PER_M * elevationDelta * nightFactor;
  const tempC = meanC + interpolate(weather, t, 'amplitude') * diurnal + offsetC + SAMPLE_NOISE_C * gaussian();
  const rhPct = clamp(
    interpolate(weather, t, 'rhBase') - RH_PER_DEGREE_PCT * (tempC - meanC) + RH_NOISE_PCT * gaussian(),
    RH_LIMITS_PCT,
  );
  return { tempC, rhPct };
}

function officeSample(t) {
  const hour = (t % DAY_S) / HOUR_S;
  const tempC = OFFICE_TEMP_C + OFFICE_AMPLITUDE_C * Math.cos((2 * Math.PI * (hour - 13)) / 24) + 0.1 * gaussian();
  return { tempC, rhPct: OFFICE_RH_PCT + 1.5 * gaussian() };
}

function isInGap(sensor, t) {
  return sensor.id === GAP_SENSOR && t >= GAP[0] && t < GAP[1];
}

function sensorSamples(sensor, weather) {
  const startT = sensor.startT ?? START_T;
  const endT = sensor.id === STALE_SENSOR ? STALE_END_T : (sensor.endT ?? END_T);
  const rows = [];
  for (let nominalT = startT + sensor.phaseS; nominalT < endT; nominalT += STEP_S) {
    const t = Math.max(startT, nominalT + Math.round(CLOCK_JITTER_S * gaussian()));
    if (isInGap(sensor, t)) {
      continue;
    }
    const indoors = sensor.id === OFFICE_SENSOR && t >= OFF_SITE[0] && t < OFF_SITE[1];
    const { tempC, rhPct } = indoors ? officeSample(t) : outdoorSample(sensor, t, weather);
    const row = { t, temp_c: round1(tempC), rh_pct: round1(rhPct), qc: indoors ? QC.PRE_DEPLOYMENT : 0 };
    if (random() < NULL_PROBABILITY) {
      row.temp_c = null;
      row.qc |= QC.MISSING;
    }
    if (random() < NULL_PROBABILITY) {
      row.rh_pct = null;
      row.qc |= QC.MISSING;
    }
    rows.push(row);
  }
  addSpikes(rows);
  if (sensor.id === STUCK_SENSOR) {
    addStuckRun(rows);
  }
  if (sensor.id === GAP_SENSOR) {
    flagFirstAtOrAfter(rows, STEP_EVENT_T, QC.STEP);
  }
  return rows;
}

function addSpikes(rows) {
  for (let i = 0; i < SPIKES_PER_SENSOR; i++) {
    const row = rows[Math.floor(random() * rows.length)];
    if (row.temp_c !== null && (row.qc & QC.PRE_DEPLOYMENT) === 0) {
      row.temp_c = round1(row.temp_c + (random() < 0.5 ? -SPIKE_C : SPIKE_C));
      row.qc |= QC.SPIKE;
    }
  }
}

function addStuckRun(rows) {
  const first = rows.findIndex((row) => row.t >= STUCK_START_T);
  const value = rows[first].temp_c;
  for (const row of rows.slice(first, first + STUCK_SAMPLES)) {
    row.temp_c = value;
    row.qc |= QC.STUCK;
  }
}

function flagFirstAtOrAfter(rows, t, flag) {
  const row = rows.find((candidate) => candidate.t >= t);
  row.qc |= flag;
  return row;
}

const monthKey = (t) => new Date(t * 1000).toISOString().slice(0, 7);

function rawMonthFiles(sensorId, rows) {
  const months = new Map();
  for (const row of rows) {
    const key = monthKey(row.t);
    if (!months.has(key)) {
      months.set(key, { sensor_id: sensorId, t: [], temp_c: [], rh_pct: [], qc: [] });
    }
    const file = months.get(key);
    file.t.push(row.t);
    file.temp_c.push(row.temp_c);
    file.rh_pct.push(row.rh_pct);
    file.qc.push(row.qc);
  }
  return months;
}

const localDateFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: DISPLAY_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});
const localDate = (t) => localDateFormat.format(new Date(t * 1000));

/** Length of a local calendar day in seconds (23 h / 24 h / 25 h around DST changes). */
function localDayLengthS(date) {
  const offsetAt = (t) => {
    const local = new Intl.DateTimeFormat('en-US', {
      timeZone: DISPLAY_TIMEZONE,
      hourCycle: 'h23',
      year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric',
    }).formatToParts(new Date(t * 1000));
    const part = (type) => Number(local.find((p) => p.type === type).value);
    return Date.UTC(part('year'), part('month') - 1, part('day'), part('hour'), part('minute')) / 1000 - t;
  };
  const naive = Date.parse(`${date}T00:00:00Z`) / 1000;
  return DAY_S - (offsetAt(naive + DAY_S) - offsetAt(naive));
}

function stats(values) {
  if (values.length === 0) {
    return [null, null, null];
  }
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return [round1(Math.min(...values)), round1(mean), round1(Math.max(...values))];
}

function dailyFile(sensorId, rows) {
  const days = new Map();
  for (const row of rows) {
    const date = localDate(row.t);
    if (!days.has(date)) {
      days.set(date, { temp: [], rh: [] });
    }
    if ((row.qc & EXCLUDE_MASK) === 0) {
      if (row.temp_c !== null) days.get(date).temp.push(row.temp_c);
      if (row.rh_pct !== null) days.get(date).rh.push(row.rh_pct);
    }
  }
  const file = { sensor_id: sensorId, date: [], temp_min: [], temp_mean: [], temp_max: [], rh_min: [], rh_mean: [], rh_max: [], coverage: [] };
  for (const [date, { temp, rh }] of days) {
    const [tMin, tMean, tMax] = stats(temp);
    const [rMin, rMean, rMax] = stats(rh);
    file.date.push(date);
    file.temp_min.push(tMin);
    file.temp_mean.push(tMean);
    file.temp_max.push(tMax);
    file.rh_min.push(rMin);
    file.rh_mean.push(rMean);
    file.rh_max.push(rMax);
    file.coverage.push(round2(Math.min(1, temp.length / (localDayLengthS(date) / STEP_S))));
  }
  return file;
}

function placeholderIndices(daily) {
  let gdd = 0;
  let huglin = 0;
  let gddDays = 0;
  let huglinDays = 0;
  daily.date.forEach((date, i) => {
    const mean = daily.temp_mean[i];
    const max = daily.temp_max[i];
    if (mean === null || max === null) return;
    gdd += Math.max(0, mean - BASE_TEMP_C);
    gddDays += 1;
    if (date < `${SEASON}-10-01`) {
      huglin += Math.max(0, (mean - BASE_TEMP_C + (max - BASE_TEMP_C)) / 2);
      huglinDays += 1;
    }
  });
  return {
    gdd_winkler: { value: round1(gdd), unit: '°C·d', coverage: round2(gddDays / GDD_SEASON_DAYS), complete: false, class: null },
    huglin: { value: round1(huglin), unit: '°C·d', coverage: round2(huglinDays / HUGLIN_SEASON_DAYS), complete: false, class: null },
  };
}

const isoSeconds = (t) => new Date(t * 1000).toISOString().replace('.000Z', 'Z');

/**
 * Registry feature as the site publishes it: the public projection with `notes` and every
 * placement's `note` set to null (owner decision 2026-10-05).
 */
function registryFeature(sensor) {
  const closed = sensor.status === 'inactive' || sensor.status === 'retired';
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [sensor.lon, sensor.lat] },
    properties: {
      id: sensor.id,
      portal_name: `${PORTAL_PREFIX} ${sensor.id}`,
      label: sensor.label,
      municipality: sensor.municipality,
      track: sensor.track,
      variety: sensor.variety,
      status: sensor.status,
      placements: [
        {
          from: isoSeconds(sensor.startT),
          to: closed ? isoSeconds(sensor.endT) : null,
          lon: sensor.lon,
          lat: sensor.lat,
          elevation_m: sensor.elevation_m,
          note: null,
        },
      ],
      notes: null,
    },
  };
}

/** Every sensor of the fixture with its defaults filled in, the full-season sensors first. */
function allSensors() {
  const full = SENSORS.map((sensor) => ({ ...sensor, label: `${sensor.id} (VUT)`, status: 'active', startT: START_T }));
  const scale = SCALE_SENSORS.map((sensor, index) => ({
    status: 'active',
    endT: SHORT_PERIOD[1],
    ...sensor,
    label: `${sensor.id} (demo)`,
    startT: SHORT_PERIOD[0],
    phaseS: ((index + 1) * SCALE_PHASE_STEP_S) % STEP_S,
  }));
  return [...full, ...scale];
}

function eventsFile(sensorId, rows) {
  const events = [];
  if (sensorId === OFFICE_SENSOR) {
    events.push({ type: 'off_site', t: OFF_SITE[0], t_end: OFF_SITE[1], source: 'log', detail: OFF_SITE_DETAIL });
  }
  if (sensorId === GAP_SENSOR) {
    const row = rows.find((candidate) => candidate.t >= STEP_EVENT_T);
    events.push({ type: 'step', t: row.t, source: 'detected', confidence: 0.61, detail: 'synthetic example event' });
  }
  return { sensor_id: sensorId, events };
}

const README = `# Synthetic demo data — NOT measurements

Every file in this directory was generated by \`web/scripts/generate-fixture.mjs\`
(seeded pseudo-random model, seed ${SEED}). The numbers are **invented** and only
exercise the web portal; they are **not measurements** from the SIVIN sensors and
must not be used for any analysis.

Only the ids and positions of the first four sensors (from \`sensor_location.gpx\`) are
real; their municipality, track and variety are null. The other 16 sensors (ids 9xxxxxxx,
\`(demo)\` in the label), all municipality and vineyard-track names ("Obec A", "Trať 1", …)
and all varieties are **fictional**; they exist to exercise the sensor picker and marker
clustering at a larger network size and have data only for September 2026. Placement dates,
events and index values are placeholders. The placeholder indices use simplified formulas
(Huglin without the latitude coefficient) and are marked \`complete: false\`.

The layout follows the static site data contract, MIGRATION_PLAN.md §2.6
(\`schema_version: 1\`). Regenerate with \`npm run fixture\` in \`web/\`.
`;

function writeJson(path, value) {
  const file = join(OUT_DIR, path);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(value)}\n`);
}

function main() {
  rmSync(OUT_DIR, { recursive: true, force: true });
  const weather = dailyWeather();
  const manifestSensors = {};
  const latest = {};
  const indices = {};
  const sensors = allSensors();
  for (const sensor of sensors) {
    const rows = sensorSamples(sensor, weather);
    const months = rawMonthFiles(sensor.id, rows);
    for (const [key, file] of months) {
      writeJson(`series/${sensor.id}/raw/${key}.json`, file);
    }
    const daily = dailyFile(sensor.id, rows);
    writeJson(`series/${sensor.id}/daily.json`, daily);
    writeJson(`events/${sensor.id}.json`, eventsFile(sensor.id, rows));
    const last = rows.at(-1);
    manifestSensors[sensor.id] = { first_t: rows[0].t, last_t: last.t, raw_months: [...months.keys()], status: sensor.status };
    const stale = sensor.id === STALE_SENSOR || sensor.status !== 'active';
    latest[sensor.id] = { t: last.t, temp_c: last.temp_c, rh_pct: last.rh_pct, qc: last.qc, stale };
    indices[sensor.id] = placeholderIndices(daily);
  }
  writeJson('manifest.json', {
    schema_version: 1,
    generated_at: GENERATED_AT,
    display_timezone: DISPLAY_TIMEZONE,
    variables: [
      { id: 'temp_c', unit: '°C', label: { cs: 'Teplota', de: 'Temperatur', en: 'Temperature' } },
      { id: 'rh_pct', unit: '%', label: { cs: 'Vlhkost', de: 'Feuchtigkeit', en: 'Humidity' } },
    ],
    sensors: manifestSensors,
    seasons: [SEASON],
    indices: [
      { id: 'gdd_winkler', unit: '°C·d', doc: 'docs/indices/gdd_winkler.md', label: { cs: 'Winklerův index (GDD)', de: 'Winkler-Index (GDD)', en: 'Winkler index (GDD)' } },
      { id: 'huglin', unit: '°C·d', doc: 'docs/indices/huglin.md', label: { cs: 'Huglinův index', de: 'Huglin-Index', en: 'Huglin index' } },
    ],
  });
  writeJson('latest.json', { generated_at: GENERATED_AT, sensors: latest });
  writeJson('sensors.geojson', { type: 'FeatureCollection', features: sensors.map(registryFeature) });
  writeJson(`indices/${SEASON}.json`, { season: SEASON, computed_at: GENERATED_AT, sensors: indices });
  writeFileSync(join(OUT_DIR, 'README.md'), README);
}

main();
