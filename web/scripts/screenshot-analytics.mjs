/**
 * Take the WP-3.4 screenshots of the "Ukazatele" section (season cards, daily risk strips,
 * records) of the built portal on the SYNTHETIC demo data, at 1280 px and 390 px.
 *
 * Prerequisite: `npm run build && npm run preview` running on PREVIEW_URL; Chromium from
 * CHROMIUM_PATH (nothing is downloaded). Writes ../docs/wp_log/img/WP-3.4-*.png and prints the
 * document's scroll width, which must equal the viewport width (no horizontal page scroll).
 *
 * Usage: `node scripts/screenshot-analytics.mjs` (from `web/`).
 */
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const PREVIEW_URL = process.env.PREVIEW_URL ?? 'http://localhost:4173/SIVIN_Mateostations/';
const CHROMIUM_PATH = process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'docs', 'wp_log', 'img');
const HASH = '#s=77678271,77680921&w=season&y=2026&lang=cs';
/** Tall viewports, so the whole section fits without scrolling inside the panel. */
const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 3200 },
  { name: 'mobile', width: 390, height: 5200 },
];
const PARTS = [
  ['cards', '.analytics__block:nth-of-type(1)'],
  ['risk', '.analytics__block:nth-of-type(2)'],
  ['records', '.analytics__block:nth-of-type(3)'],
];

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ executablePath: CHROMIUM_PATH });
  try {
    for (const viewport of VIEWPORTS) {
      const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
      page.on('pageerror', (error) => console.error(`page error: ${error.message}`));
      await page.goto(`${PREVIEW_URL}${HASH}`);
      await page.waitForSelector('.records__table');
      const scrollWidth = await page.evaluate('document.documentElement.scrollWidth');
      console.log(`${viewport.name}: viewport ${viewport.width}px, document scrollWidth ${scrollWidth}px`);
      for (const [part, selector] of PARTS) {
        const file = `WP-3.4-${part}-${viewport.name}.png`;
        await page.locator(`.analytics__body > ${selector}`).screenshot({ path: join(OUT_DIR, file) });
        console.log(`wrote ${file}`);
      }
      await page.close();
    }
  } finally {
    await browser.close();
  }
}

await main();
