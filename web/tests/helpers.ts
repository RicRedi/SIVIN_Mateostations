import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { JsonFetcher } from '../src/data/DataClient';

/** Unix seconds of a UTC date-time (month 1–12). */
export function utc(year: number, month: number, day: number, hour = 0, minute = 0, second = 0): number {
  return Date.UTC(year, month - 1, day, hour, minute, second) / 1000;
}

const FIXTURE_DIR = join(import.meta.dirname, '..', 'public', 'data');

/** True if the committed fixture contains `path`. */
export function fixtureExists(path: string): boolean {
  return existsSync(join(FIXTURE_DIR, path));
}

/** Parsed JSON of a file of the committed synthetic fixture `public/data/`. */
export function fixtureJson(path: string): unknown {
  return JSON.parse(readFileSync(join(FIXTURE_DIR, path), 'utf8'));
}

/** A fetcher serving `files` (path relative to `base` → JSON); anything else is HTTP 404. */
export function fakeFetcher(base: string, files: Readonly<Record<string, unknown>>): {
  fetcher: JsonFetcher;
  requested: string[];
} {
  const requested: string[] = [];
  const fetcher: JsonFetcher = (url) => {
    requested.push(url);
    const path = url.slice(base.length);
    const found = url.startsWith(base) && path in files;
    return Promise.resolve({
      ok: found,
      status: found ? 200 : 404,
      json: () => Promise.resolve(files[path]),
    });
  };
  return { fetcher, requested };
}

/** The synthetic off-site period of sensor 77799986 in the committed fixture (generate-fixture.mjs). */
export const OFF_SITE_START = utc(2026, 6, 4, 6);
export const OFF_SITE_END = utc(2026, 6, 5, 14);
export const OFF_SITE_DETAIL = 'service';
