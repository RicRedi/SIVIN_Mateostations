/**
 * Take the hand-off screenshots of the built portal with Playwright (Chromium).
 *
 * Prerequisite: `npm run build && npm run preview` running on PREVIEW_URL. Chromium comes from
 * CHROMIUM_PATH (default: the sandbox copy under /opt/pw-browsers); nothing is downloaded.
 * Map tiles are requested from the internet and may stay blank in an offline sandbox.
 *
 * Usage: `npm run screenshot` (from `web/`); writes to ../docs/wp_log/img/.
 */
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const PREVIEW_URL = process.env.PREVIEW_URL ?? 'http://localhost:4173/SIVIN_Mateostations/';
const CHROMIUM_PATH = process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'docs', 'wp_log', 'img');
const TILE_TIMEOUT_MS = 3000;

const SHOTS = [
  {
    file: 'WP-3.1-desktop.png',
    viewport: { width: 1440, height: 900 },
    hash: '#s=77678271,77799986&w=custom&from=2026-06-01&to=2026-06-07&lang=cs',
  },
  {
    file: 'WP-3.1-mobile.png',
    viewport: { width: 390, height: 844 },
    hash: '#s=77678271,77680921&w=30d&lang=cs',
    scrollToChart: true,
  },
];

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ executablePath: CHROMIUM_PATH });
  try {
    for (const shot of SHOTS) {
      const page = await browser.newPage({ viewport: shot.viewport, deviceScaleFactor: 1 });
      page.on('pageerror', (error) => console.error(`page error: ${error.message}`));
      await page.goto(`${PREVIEW_URL}${shot.hash}`);
      await page.waitForSelector('.uplot canvas');
      await page.waitForTimeout(TILE_TIMEOUT_MS);
      if (shot.scrollToChart) {
        await page.evaluate("document.querySelector('.chart').scrollIntoView({ block: 'end' })");
      }
      const scrollWidth = await page.evaluate('document.documentElement.scrollWidth');
      console.log(`${shot.file}: viewport ${shot.viewport.width}px, document scrollWidth ${scrollWidth}px`);
      await page.screenshot({ path: join(OUT_DIR, shot.file) });
      await page.close();
    }
  } finally {
    await browser.close();
  }
}

await main();
