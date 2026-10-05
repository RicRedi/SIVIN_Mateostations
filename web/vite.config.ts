import { defineConfig } from 'vitest/config';

/**
 * Public base path of the deployed site.
 *
 * GitHub Pages serves the project at `https://ricredi.github.io/SIVIN_Mateostations/`, so every
 * asset URL (and the data base URL, see `src/main.ts`) is prefixed with this path. Override it
 * with the `SITE_BASE` environment variable, e.g. `SITE_BASE=/ npm run build` for a root deploy.
 */
const DEFAULT_SITE_BASE = '/SIVIN_Mateostations/';

/** Minimum share of `src/` lines that tests must execute (CONTRIBUTING.md, Tests). */
const MIN_LINE_COVERAGE_PCT = 85;

export default defineConfig({
  base: process.env.SITE_BASE ?? DEFAULT_SITE_BASE,
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      exclude: [
        'src/main.ts',
        'src/vite-env.d.ts',
        'src/ui/MapView.ts',
        'src/ui/SeriesChart.ts',
        'src/ui/App.ts',
      ],
      reporter: ['text-summary', 'text'],
      thresholds: { lines: MIN_LINE_COVERAGE_PCT },
    },
  },
});
